"""Supervised proxy-outcome model: histogram gradient boosting with isotonic calibration."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from foretaksrisiko.config import ModelConfig


@dataclass
class FittedSupervised:
    model: object
    calibrated: object
    params: dict
    grid: list[dict] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    categorical: list[str] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=dict)
    fill_values: dict[str, object] = field(default_factory=dict)

    def predict_proba(self, matrix: pd.DataFrame) -> np.ndarray:
        return self.calibrated.predict_proba(self._conform(matrix))[:, 1]

    def predict_raw(self, matrix: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self._conform(matrix))[:, 1]

    def _conform(self, matrix: pd.DataFrame) -> pd.DataFrame:
        """Reorder columns and pin categorical levels to those seen in training."""
        frame = matrix[self.features].copy()
        for column in self.categorical:
            frame[column] = pd.Categorical(
                frame[column].astype("string").fillna("missing"), categories=self.categories[column]
            )
        return frame


def fit_supervised(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_valid: pd.DataFrame,
    y_valid: np.ndarray,
    categorical: list[str],
    cfg: ModelConfig,
    seed: int,
    fill_values: dict[str, object] | None = None,
) -> FittedSupervised:
    """Small grid chosen on validation average precision, then isotonic calibration."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.frozen import FrozenEstimator
    from sklearn.metrics import average_precision_score

    features = list(x_train.columns)
    categories = {
        c: list(x_train[c].cat.categories.astype(str)) for c in categorical if c in features
    }
    grid: list[dict] = []
    best = None
    for lr, leaves, min_leaf in itertools.product(
        cfg.hgb_grid_learning_rate, cfg.hgb_grid_max_leaf_nodes, cfg.hgb_grid_min_samples_leaf
    ):
        candidate = HistGradientBoostingClassifier(
            learning_rate=lr,
            max_leaf_nodes=leaves,
            min_samples_leaf=min_leaf,
            max_iter=cfg.hgb_max_iter,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=30,
            categorical_features="from_dtype",
            random_state=seed,
        )
        candidate.fit(x_train, y_train)
        ap = float(average_precision_score(y_valid, candidate.predict_proba(x_valid)[:, 1]))
        params = {
            "learning_rate": lr,
            "max_leaf_nodes": leaves,
            "min_samples_leaf": min_leaf,
            "n_iter": int(candidate.n_iter_),
            "valid_average_precision": ap,
        }
        grid.append(params)
        if best is None or ap > best[0]:
            best = (ap, candidate, params)
    assert best is not None
    _, model, params = best
    calibrated = CalibratedClassifierCV(FrozenEstimator(model), method="isotonic").fit(
        x_valid, y_valid
    )
    return FittedSupervised(
        model=model,
        calibrated=calibrated,
        params=params,
        grid=grid,
        features=features,
        categorical=[c for c in categorical if c in features],
        categories=categories,
        fill_values=dict(fill_values or {}),
    )


class ScoringPipeline:
    """Serving wrapper: conforms raw feature rows and returns calibrated probabilities.

    Implemented as a plain class with a ``predict`` method so it can be wrapped as an MLflow
    pyfunc model without importing MLflow at module import time.
    """

    def __init__(self, fitted: FittedSupervised) -> None:
        self.fitted = fitted

    def predict(self, model_input: pd.DataFrame) -> np.ndarray:
        frame = model_input.copy()
        for column, value in self.fitted.fill_values.items():
            if column in frame.columns and value is not None:
                frame[column] = frame[column].fillna(value)
        for column in self.fitted.features:
            if column not in frame.columns:
                frame[column] = np.nan
            if column not in self.fitted.categorical:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float32")
        return self.fitted.predict_proba(frame)
