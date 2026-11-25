"""Anomaly scores without labels: rule baseline, Isolation Forest, robust Mahalanobis distance."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from foretaksrisiko.config import ModelConfig


def z_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if c.startswith("z_")]


def rule_score(frame: pd.DataFrame, extreme: float = 3.0) -> np.ndarray:
    """Number of peer z-scores beyond the threshold, with the largest absolute z as tie-breaker."""
    z = frame[z_columns(list(frame.columns))].astype("float64")
    count = (z.abs() > extreme).sum(axis=1).to_numpy(dtype=float)
    largest = z.abs().max(axis=1).fillna(0.0).to_numpy(dtype=float)
    return count + largest / 1000.0


def fit_isolation_forest(matrix: pd.DataFrame, cfg: ModelConfig, seed: int):
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(
        n_estimators=cfg.iforest_estimators,
        max_samples=min(cfg.iforest_max_samples, len(matrix)),
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(matrix)
    return model


def isolation_scores(model, matrix: pd.DataFrame) -> np.ndarray:
    """Higher means more unusual."""
    return -model.score_samples(matrix)


@dataclass
class RobustMahalanobis:
    """Mahalanobis distance with a robust (MCD) covariance on robustly scaled peer z-scores."""

    columns: list[str]
    center: np.ndarray
    scale: np.ndarray
    estimator: object

    @classmethod
    def fit(cls, matrix: pd.DataFrame, cfg: ModelConfig, seed: int) -> RobustMahalanobis:
        from sklearn.covariance import MinCovDet

        columns = z_columns(list(matrix.columns)) or list(matrix.columns)
        values = matrix[columns].astype("float64").to_numpy()
        center = np.nanmedian(values, axis=0)
        q75, q25 = np.nanpercentile(values, [75, 25], axis=0)
        scale = np.where((q75 - q25) > 0, (q75 - q25) / 1.349, 1.0)
        keep = np.isfinite(scale) & (scale > 0)
        columns = [c for c, k in zip(columns, keep, strict=True) if k]
        center, scale = center[keep], scale[keep]
        scaled = (values[:, keep] - center) / scale
        scaled = np.nan_to_num(scaled, nan=0.0)
        rng = np.random.default_rng(seed)
        rows = min(cfg.mahalanobis_fit_rows, len(scaled))
        sample = scaled[rng.choice(len(scaled), size=rows, replace=False)]
        estimator = MinCovDet(random_state=seed, support_fraction=0.9).fit(sample)
        return cls(columns=columns, center=center, scale=scale, estimator=estimator)

    def score(self, matrix: pd.DataFrame) -> np.ndarray:
        values = matrix[self.columns].astype("float64").to_numpy()
        scaled = np.nan_to_num((values - self.center) / self.scale, nan=0.0)
        return np.sqrt(np.maximum(self.estimator.mahalanobis(scaled), 0.0))


def robust_contributions(frame: pd.DataFrame, score: np.ndarray, top_share: float) -> pd.DataFrame:
    """Mean absolute z per feature among the top-scored companies versus all companies."""
    z = frame[z_columns(list(frame.columns))].astype("float64").abs()
    k = max(1, int(np.ceil(top_share * len(z))))
    top = np.argsort(-score)[:k]
    table = pd.DataFrame(
        {
            "feature": z.columns,
            "mean_abs_z_top": z.iloc[top].mean().to_numpy(),
            "mean_abs_z_all": z.mean().to_numpy(),
        }
    )
    table["ratio"] = table["mean_abs_z_top"] / table["mean_abs_z_all"].replace(0, np.nan)
    return table.sort_values("mean_abs_z_top", ascending=False).reset_index(drop=True)
