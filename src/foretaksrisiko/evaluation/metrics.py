"""Ranking and probability metrics with bootstrap confidence intervals."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(y, score)) if y.sum() > 0 else float("nan")


def roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    if y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    return float(roc_auc_score(y, score))


def top_indices(score: np.ndarray, share: float) -> np.ndarray:
    k = max(1, int(np.ceil(share * len(score))))
    return np.argsort(-score, kind="stable")[:k]


def precision_at_share(y: np.ndarray, score: np.ndarray, share: float) -> tuple[float, float]:
    """Precision among the top share, and lift relative to the base rate."""
    top = top_indices(score, share)
    precision = float(y[top].mean())
    base = float(y.mean())
    return precision, (precision / base if base > 0 else float("nan"))


def brier(y: np.ndarray, probability: np.ndarray) -> float:
    return float(np.mean((probability - y) ** 2))


def calibration_table(y: np.ndarray, probability: np.ndarray, bins: int) -> pd.DataFrame:
    """Equal-count bins of predicted probability with mean prediction and observed rate."""
    order = np.argsort(probability, kind="stable")
    chunks = np.array_split(order, bins)
    rows = []
    for index, chunk in enumerate(chunks):
        if len(chunk) == 0:
            continue
        rows.append(
            {
                "bin": index + 1,
                "n": int(len(chunk)),
                "mean_predicted": float(probability[chunk].mean()),
                "observed_rate": float(y[chunk].mean()),
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(y: np.ndarray, probability: np.ndarray, bins: int) -> float:
    table = calibration_table(y, probability, bins)
    weights = table["n"] / table["n"].sum()
    return float((weights * (table["mean_predicted"] - table["observed_rate"]).abs()).sum())


def summarize(
    y: np.ndarray, score: np.ndarray, top_shares: list[float], probability: bool, bins: int
) -> dict[str, float]:
    metrics = {
        "average_precision": average_precision(y, score),
        "roc_auc": roc_auc(y, score),
        "base_rate": float(y.mean()),
        "n": float(len(y)),
        "positives": float(y.sum()),
    }
    for share in top_shares:
        precision, lift = precision_at_share(y, score, share)
        label = f"{int(round(share * 100))}pct"
        metrics[f"precision_top_{label}"] = precision
        metrics[f"lift_top_{label}"] = lift
    if probability:
        metrics["brier"] = brier(y, score)
        metrics["expected_calibration_error"] = expected_calibration_error(y, score, bins)
    return metrics


def bootstrap_interval(
    y: np.ndarray,
    score: np.ndarray,
    metric: Callable[[np.ndarray, np.ndarray], float],
    samples: int,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile 95 percent interval from resampling companies with replacement."""
    rng = np.random.default_rng(seed)
    n = len(y)
    values = []
    for _ in range(samples):
        idx = rng.integers(0, n, size=n)
        value = metric(y[idx], score[idx])
        if np.isfinite(value):
            values.append(value)
    if not values:
        return float("nan"), float("nan")
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    from scipy.stats import spearmanr

    if len(a) < 3:
        return float("nan")
    return float(spearmanr(a, b).statistic)


def top_overlap(a: np.ndarray, b: np.ndarray, share: float) -> float:
    top_a = set(top_indices(a, share).tolist())
    top_b = set(top_indices(b, share).tolist())
    return len(top_a & top_b) / max(1, len(top_a))


def stability(scores_by_seed: dict[int, np.ndarray], share: float) -> dict[str, float]:
    """Mean pairwise Spearman correlation and top-share overlap across seeds."""
    seeds = sorted(scores_by_seed)
    pairs = [(a, b) for i, a in enumerate(seeds) for b in seeds[i + 1 :]]
    if not pairs:
        return {"spearman_mean": float("nan"), "top_overlap_mean": float("nan")}
    rho = [spearman(scores_by_seed[a], scores_by_seed[b]) for a, b in pairs]
    overlap = [top_overlap(scores_by_seed[a], scores_by_seed[b], share) for a, b in pairs]
    return {"spearman_mean": float(np.nanmean(rho)), "top_overlap_mean": float(np.mean(overlap))}


def agreement(a: np.ndarray, b: np.ndarray, top_shares: list[float]) -> dict[str, float]:
    out = {"spearman": spearman(a, b)}
    for share in top_shares:
        out[f"top_overlap_{int(round(share * 100))}pct"] = top_overlap(a, b, share)
    return out
