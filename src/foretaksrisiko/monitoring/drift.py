"""Data and prediction drift between two snapshots, on pandas.

Population stability index (PSI) per feature, missingness rates and category shares, compared
with a reference snapshot. Prediction drift is the PSI of the champion's scores and the share
flagged above the reference flag threshold. Severity follows the thresholds in
``MonitoringConfig``: "ok", "warn" (recorded) or "alert" (recorded and fails the alert stage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from foretaksrisiko.config import MonitoringConfig
from foretaksrisiko.models.data import CATEGORICAL, ID_COLUMNS, LABEL_COLUMNS, NEVER_FEATURES

EPSILON = 1e-4
QUANTILES = (0.5, 0.9, 0.99)
DRIFT_COLUMNS = [
    "feature",
    "kind",
    "metric",
    "reference_value",
    "current_value",
    "value",
    "warn_threshold",
    "alert_threshold",
    "severity",
    "level",
    "rows_reference",
    "rows_current",
]


def severity(value: float | None, warn: float | None, alert: float | None) -> str:
    if value is None or warn is None or alert is None or np.isnan(value):
        return "ok"
    if value >= alert:
        return "alert"
    if value >= warn:
        return "warn"
    return "ok"


def psi_from_shares(reference: np.ndarray, current: np.ndarray) -> float:
    ref = np.clip(reference, EPSILON, None)
    cur = np.clip(current, EPSILON, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def _bin_shares(values: np.ndarray, edges: np.ndarray, width: float) -> np.ndarray:
    """Share of the values in each bin; within ``width`` of an edge a value counts on both sides."""
    if width <= 0:
        counts = np.bincount(np.searchsorted(edges, values, side="right"), minlength=len(edges) + 1)
        return counts / len(values)
    # Share counted at or above each edge, rising from 0 to 1 across the band around the edge.
    above = np.array(
        [np.clip((values - edge) / (2 * width) + 0.5, 0.0, 1.0).mean() for edge in edges]
    )
    return -np.diff(np.concatenate(([1.0], above, [0.0])))


def numeric_psi(
    reference: np.ndarray, current: np.ndarray, bins: int, smoothing: float = 0.0
) -> float | None:
    """PSI over quantile bins of the reference; None when either side has no values.

    A value shared by many rows can sit exactly on a bin edge. A small change in that value then
    moves the whole block into the neighbouring bin and inflates the index, although the
    distribution is unchanged. With ``smoothing`` above zero a value near an edge counts partly
    on both sides: the band around each edge is that share of the reference's inter-decile range.
    """
    ref = reference[~np.isnan(reference)]
    cur = current[~np.isnan(current)]
    if len(ref) == 0 or len(cur) == 0:
        return None
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)[1:-1]))
    if len(edges) == 0:
        return 0.0
    low, high = np.quantile(ref, [0.1, 0.9])
    width = smoothing * float(high - low)
    return psi_from_shares(_bin_shares(ref, edges, width), _bin_shares(cur, edges, width))


def categorical_psi(reference: pd.Series, current: pd.Series) -> tuple[float, float, str | None]:
    """PSI over category shares (missing is a level), the largest share change and its level."""
    ref = reference.astype("string").fillna("missing")
    cur = current.astype("string").fillna("missing")
    levels = pd.Index(sorted(set(ref.unique()) | set(cur.unique())))
    ref_shares = ref.value_counts(normalize=True).reindex(levels, fill_value=0.0).to_numpy()
    cur_shares = cur.value_counts(normalize=True).reindex(levels, fill_value=0.0).to_numpy()
    deltas = np.abs(cur_shares - ref_shares)
    if len(deltas) == 0:
        return 0.0, 0.0, None
    worst = int(np.argmax(deltas))
    return psi_from_shares(ref_shares, cur_shares), float(deltas[worst]), str(levels[worst])


def monitored_columns(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Numeric and categorical feature columns; identifiers, masks and labels are left out."""
    excluded = set(ID_COLUMNS) | set(LABEL_COLUMNS) | NEVER_FEATURES | {"snapshot_id"}
    numeric: list[str] = []
    categorical: list[str] = []
    for column in frame.columns:
        if column in excluded or column.startswith("masked_"):
            continue
        dtype = frame[column].dtype
        if column in CATEGORICAL or str(dtype) in (
            "bool",
            "boolean",
            "object",
            "string",
            "category",
        ):
            categorical.append(column)
        elif np.issubdtype(dtype, np.number):
            numeric.append(column)
    return numeric, categorical


def _row(
    feature: str,
    kind: str,
    metric: str,
    ref: float | None,
    cur: float | None,
    value: float | None,
    warn: float | None,
    alert: float | None,
    level: str | None = None,
) -> dict:
    return {
        "feature": feature,
        "kind": kind,
        "metric": metric,
        "reference_value": None if ref is None else float(ref),
        "current_value": None if cur is None else float(cur),
        "value": None if value is None else float(value),
        "warn_threshold": warn,
        "alert_threshold": alert,
        "severity": severity(value, warn, alert),
        "level": level,
    }


def _missing_rate(series: pd.Series) -> float | None:
    return float(series.isna().mean()) if len(series) else None


def drift_table(
    reference: pd.DataFrame, current: pd.DataFrame, cfg: MonitoringConfig
) -> pd.DataFrame:
    """One row per feature and metric with reference value, current value and severity.

    Below ``cfg.min_rows`` on either side the values are left empty, so small snapshots never
    raise alerts by chance.
    """
    numeric, categorical = monitored_columns(reference)
    enough = len(reference) >= cfg.min_rows and len(current) >= cfg.min_rows
    rows: list[dict] = []
    for column in numeric:
        if column not in current:
            continue
        ref = pd.to_numeric(reference[column], errors="coerce").to_numpy(dtype="float64")
        cur = pd.to_numeric(current[column], errors="coerce").to_numpy(dtype="float64")
        ref_missing, cur_missing = _missing_rate(reference[column]), _missing_rate(current[column])
        rows.append(
            _row(
                column,
                "numeric",
                "psi",
                None,
                None,
                numeric_psi(ref, cur, cfg.psi_bins, cfg.psi_edge_smoothing) if enough else None,
                cfg.psi_warn,
                cfg.psi_alert,
            )
        )
        rows.append(
            _row(
                column,
                "numeric",
                "missing_rate",
                ref_missing,
                cur_missing,
                abs(cur_missing - ref_missing) if enough else None,
                cfg.missingness_delta_warn,
                cfg.missingness_delta_alert,
            )
        )
    for column in categorical:
        if column not in current:
            continue
        value, max_delta, level = categorical_psi(reference[column], current[column])
        ref_missing, cur_missing = _missing_rate(reference[column]), _missing_rate(current[column])
        rows.append(
            _row(
                column,
                "categorical",
                "psi",
                None,
                None,
                value if enough else None,
                cfg.psi_warn,
                cfg.psi_alert,
            )
        )
        rows.append(
            _row(
                column,
                "categorical",
                "max_share_delta",
                None,
                None,
                max_delta if enough else None,
                cfg.category_share_delta_warn,
                cfg.category_share_delta_alert,
                level,
            )
        )
        rows.append(
            _row(
                column,
                "categorical",
                "missing_rate",
                ref_missing,
                cur_missing,
                abs(cur_missing - ref_missing) if enough else None,
                cfg.missingness_delta_warn,
                cfg.missingness_delta_alert,
            )
        )
    table = pd.DataFrame(rows, columns=DRIFT_COLUMNS[:-2])
    table["rows_reference"] = len(reference)
    table["rows_current"] = len(current)
    return table


def flag_threshold(reference_scores: np.ndarray, flag_share: float) -> float:
    """Score above which the top ``flag_share`` of the reference snapshot is flagged."""
    scores = reference_scores[~np.isnan(reference_scores)]
    return float(np.quantile(scores, 1.0 - flag_share)) if len(scores) else float("nan")


def score_summary(scores: np.ndarray, threshold: float) -> dict:
    clean = scores[~np.isnan(scores)]
    summary: dict = {
        "rows": int(len(clean)),
        "mean_score": float(clean.mean()) if len(clean) else None,
        "flag_threshold": threshold,
        "flag_share": float((clean > threshold).mean()) if len(clean) else None,
    }
    for q in QUANTILES:
        summary[f"p{int(q * 100)}"] = float(np.quantile(clean, q)) if len(clean) else None
    return summary


def score_drift(
    reference_scores: np.ndarray, current_scores: np.ndarray, cfg: MonitoringConfig
) -> pd.DataFrame:
    """Score PSI and flagged share against the reference flag threshold, with severity."""
    threshold = flag_threshold(reference_scores, cfg.flag_share)
    ref = score_summary(reference_scores, threshold)
    cur = score_summary(current_scores, threshold)
    enough = ref["rows"] >= cfg.min_rows and cur["rows"] >= cfg.min_rows
    rows = [
        _row(
            "score",
            "prediction",
            "psi",
            None,
            None,
            numeric_psi(reference_scores, current_scores, cfg.psi_bins, cfg.psi_edge_smoothing)
            if enough
            else None,
            cfg.score_psi_warn,
            cfg.score_psi_alert,
        )
    ]
    relative = (
        abs(cur["flag_share"] - ref["flag_share"]) / ref["flag_share"]
        if enough and ref["flag_share"]
        else None
    )
    rows.append(
        _row(
            "score",
            "prediction",
            "flag_share",
            ref["flag_share"],
            cur["flag_share"],
            relative,
            cfg.flag_share_relative_warn,
            cfg.flag_share_relative_alert,
        )
    )
    for metric in ("mean_score", "p50", "p90", "p99"):
        rows.append(_row("score", "prediction", metric, ref[metric], cur[metric], None, None, None))
    table = pd.DataFrame(rows, columns=DRIFT_COLUMNS[:-2])
    table["rows_reference"] = ref["rows"]
    table["rows_current"] = cur["rows"]
    return table
