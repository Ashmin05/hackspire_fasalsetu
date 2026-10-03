"""Candidate forecasters, all predicting log(price_{t+h} / price_t).

Baselines first (they're what any model has to beat):
  naive            no change: tomorrow's price is today's
  moving_average   the 7-day average price
  seasonal_naive   last year's move over the same stretch of the calendar
Then learned models:
  ridge            linear regression (L2) on scaled features
  random_forest    bagged trees
  lightgbm         gradient-boosted trees (squared error)
  lightgbm_huber   the same with Huber loss (robust to price jumps)
Deep sequence models (LSTM/GRU) are deliberately not included: with a few
years of daily data per market, tree ensembles and linear models are the
appropriate tools, and validation decides between them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.price_forecast.dataset import model_features, seasonal_feature

MAX_TRAIN_ROWS = 60_000  # subsample for the slower learners
# Sanity cap on a predicted move: x0.22 .. x4.5 of today's price. Linear
# models can extrapolate wildly on unusual feature values; an estimate
# beyond this is never plausible for a mandi price within 30 days.
MAX_ABS_LOG_CHANGE = 1.5


def bounded(prediction) -> np.ndarray:
    """Model output -> finite, capped log price ratios."""
    values = np.nan_to_num(np.asarray(prediction, dtype=float), nan=0.0, posinf=MAX_ABS_LOG_CHANGE, neginf=-MAX_ABS_LOG_CHANGE)
    return np.clip(values, -MAX_ABS_LOG_CHANGE, MAX_ABS_LOG_CHANGE)


class Forecaster:
    name = "base"
    kind = "baseline"

    def __init__(self, horizon: int) -> None:
        self.horizon = horizon

    @property
    def features(self) -> list[str]:
        return []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "Forecaster":
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError


class NaiveModel(Forecaster):
    name = "naive"

    def predict(self, X):
        return np.zeros(len(X))


class MovingAverageModel(Forecaster):
    name = "moving_average"

    @property
    def features(self):
        return ["rolling_mean_7_ratio"]

    def predict(self, X):
        return X["rolling_mean_7_ratio"].fillna(0.0).to_numpy()


class SeasonalNaiveModel(Forecaster):
    """Falls back to no-change where last year's prices are missing."""

    name = "seasonal_naive"

    @property
    def features(self):
        return [seasonal_feature(self.horizon)]

    def predict(self, X):
        return X[seasonal_feature(self.horizon)].fillna(0.0).to_numpy()


class _Learned(Forecaster):
    kind = "learned"
    uses_ids = False

    @property
    def features(self):
        return model_features(self.horizon, with_ids=self.uses_ids)

    def _subsample(self, X, y):
        if len(X) <= MAX_TRAIN_ROWS:
            return X, y
        # Keep the most recent rows -- they matter most for what comes next.
        return X.iloc[-MAX_TRAIN_ROWS:], y.iloc[-MAX_TRAIN_ROWS:]

    def predict(self, X):
        return self.model.predict(X[self.features])


class RidgeModel(_Learned):
    name = "ridge"

    def fit(self, X, y):
        self.model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))
        self.model.fit(X[self.features], y)
        return self


class RandomForestModel(_Learned):
    name = "random_forest"
    uses_ids = True

    def fit(self, X, y):
        X, y = self._subsample(X, y)
        self.model = make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestRegressor(
                n_estimators=150, max_depth=14, min_samples_leaf=20, max_features=0.5, n_jobs=-1, random_state=0
            ),
        )
        self.model.fit(X[self.features], y)
        return self


class LightGBMModel(_Learned):
    name = "lightgbm"
    uses_ids = True

    def fit(self, X, y):
        from lightgbm import LGBMRegressor

        X, y = self._subsample(X, y)
        self.model = LGBMRegressor(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=31,
            min_child_samples=40,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=0,
            verbose=-1,
        )
        self.model.fit(X[self.features], y)
        return self


class LightGBMHuberModel(LightGBMModel):
    """Same trees, Huber loss: mandi prices are sticky (many unchanged
    weeks) with occasional large jumps, so a loss that doesn't chase the
    jumps suits MAE-based selection better than squared error."""

    name = "lightgbm_huber"

    def fit(self, X, y):
        from lightgbm import LGBMRegressor

        X, y = self._subsample(X, y)
        self.model = LGBMRegressor(
            objective="huber",
            alpha=0.02,  # ~2% move: beyond it errors count linearly
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=31,
            min_child_samples=40,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            random_state=0,
            verbose=-1,
        )
        self.model.fit(X[self.features], y)
        return self


BASELINES = (NaiveModel, MovingAverageModel, SeasonalNaiveModel)
LEARNED = (RidgeModel, RandomForestModel, LightGBMModel, LightGBMHuberModel)
ALL_MODELS = (*BASELINES, *LEARNED)
