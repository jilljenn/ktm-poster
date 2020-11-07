import numpy as np 
import pandas as pd
import os
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from scipy.optimize import brentq
from collections import Counter, defaultdict
import sys


PATH = Path('../../../data/neurips')

def sigmoid(x):
    return 1 / (1 + np.exp(-x))

def proba(th, d, bias=0):
    return sigmoid(th - d + bias)


class MyModel:
    def __init__(self):
        """
        Simple example baseline model, which will always query the most answered question available during question 
        selection, and will always predict the most common answer for each question when a student hasn't answered it.
        """
        self.most_popular_answers = None
        self.num_answers = None

    def train_model(self, extra_data=None):
        """
        Train a model.
        """
        if extra_data is not None:
            timestep = len(extra_data) // 984
        else:
            timestep = 0
        # # For local evaluation
        data_path = PATH / 'test_input/train_task_4.csv'

        # For full training
        # data_path = PATH / 'train_data/train_task_3_4.csv'  # locally
        # data_path = 'train_task_3_4.csv' # for training on the server

        estimators = [
            ('onehot', OneHotEncoder()),
            ('lr', LogisticRegression(solver='liblinear', C=1e10 if timestep == 0 else 1))
        ]
        pipe = Pipeline(estimators)
        self.pipe = pipe
        
        df = pd.read_csv(data_path)
        offset = df['UserId'].max() + 1
        if extra_data is not None:
            nb_active_users = extra_data['UserId'].nunique()
            extra_data['UserId'] += offset
            df = pd.concat([df, extra_data])
        nb_items = df['QuestionId'].nunique()
        FIELDS = ['UserId', 'QuestionId']
        pipe.fit(df[FIELDS].fillna(0), df['IsCorrect'])

        weights = pipe.named_steps['lr'].coef_[0]
        self.bias = pipe.named_steps['lr'].intercept_[0]
        self.bias = 0  # Forget the bias
        self.thetas = weights[:-nb_items]
        diff = -weights[-nb_items:]
        self.diff = diff
        
        if extra_data is not None:
            self.df = df
            self.thetas = self.thetas[-nb_active_users:].reshape(-1, 1)  # Drop inactive

    def load(self, most_popular_path, num_answers_path):
        """
        Load a model's state.
        """
        self.train_model()
        self.theta0 = np.mean(self.thetas)        
        self.thetas = None
        self.results = None
        self.logs = defaultdict(list)

    def select_feature(self, masked_data, masked_binary_data, can_query):
        """
        Select best feature from those available.
        """
        self.nb_students, self.nb_items = masked_data.shape
        if self.thetas is None or not len(self.thetas):  # First question
            self.thetas = np.array([self.theta0] * self.nb_students).reshape(-1, 1)
            
        loss = np.abs(0.5 - proba(self.thetas, self.diff, self.bias)) + (1 - can_query)
        selections = np.argmin(loss, axis=1)
        candidates = Counter()
        for k, v in candidates.most_common(1):
            self.logs[0].append((k, v))
        return selections

    def update_model(self, masked_data, masked_binary_data, can_query):
        user_ids, item_ids = np.where(masked_data > 0)
        # correctness = masked_binary_data[user_ids, item_ids]
        correctness = masked_binary_data[masked_data > 0]  # Identical ^

        extra_data = pd.DataFrame(np.column_stack((user_ids, item_ids, correctness)), columns=['UserId', 'QuestionId', 'IsCorrect'])
        self.train_model(extra_data)

    def predict(self, masked_data, masked_binary_data):
        """
        Produce binary predictions.
        """
        predictions = np.round(proba(self.thetas, self.diff, self.bias) - 0.0)
        return predictions