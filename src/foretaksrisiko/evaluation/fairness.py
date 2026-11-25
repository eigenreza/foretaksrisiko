"""Flag rates and precision across groups, with small groups suppressed."""

from __future__ import annotations

import numpy as np
import pandas as pd

from foretaksrisiko.evaluation.metrics import top_indices

AGE_BANDS = [(0, 2, "0-2"), (2, 5, "2-5"), (5, 10, "5-10"), (10, 10_000, "10+")]


def age_band(age_years: pd.Series) -> pd.Series:
    out = pd.Series("missing", index=age_years.index, dtype="object")
    for low, high, label in AGE_BANDS:
        out[(age_years >= low) & (age_years < high)] = label
    return out


def group_columns(frame: pd.DataFrame) -> dict[str, pd.Series]:
    groups: dict[str, pd.Series] = {}
    if "fylke_code" in frame:
        groups["fylke"] = frame["fylke_code"].astype("string").fillna("missing")
    if "nace_section" in frame:
        groups["nace_section"] = frame["nace_section"].astype("string").fillna("missing")
    if "age_years" in frame:
        groups["age_band"] = age_band(frame["age_years"].astype("float64"))
    if "size_band" in frame:
        groups["size_band"] = frame["size_band"].astype("string").fillna("missing")
    return groups


def fairness_table(
    frame: pd.DataFrame,
    y: np.ndarray,
    score: np.ndarray,
    top_share: float,
    min_group_size: int,
    thresholds_per_group: bool = False,
) -> pd.DataFrame:
    """Per group: size, base rate, share flagged in the top share, precision among flagged.

    With ``thresholds_per_group`` the top share is applied inside each group (the mitigation
    tested in the plan), otherwise one global threshold is used.
    """
    flagged = np.zeros(len(score), dtype=bool)
    if not thresholds_per_group:
        flagged[top_indices(score, top_share)] = True
    rows = []
    for group_type, values in group_columns(frame).items():
        for value in sorted(values.unique()):
            mask = (values == value).to_numpy()
            n = int(mask.sum())
            if thresholds_per_group:
                local = np.zeros(len(score), dtype=bool)
                idx = np.flatnonzero(mask)
                local[idx[top_indices(score[mask], top_share)]] = True
                group_flagged = local & mask
            else:
                group_flagged = flagged & mask
            suppressed = n < min_group_size
            n_flagged = int(group_flagged.sum())
            rows.append(
                {
                    "group_type": group_type,
                    "group_value": None if suppressed else str(value),
                    "n": None if suppressed else n,
                    "base_rate": None if suppressed else float(y[mask].mean()),
                    "flag_rate": None if suppressed else n_flagged / n,
                    "precision": None
                    if suppressed or n_flagged == 0
                    else float(y[group_flagged].mean()),
                    "positives_flagged": None if suppressed else int(y[group_flagged].sum()),
                    "suppressed": suppressed,
                    "per_group_threshold": thresholds_per_group,
                }
            )
    table = pd.DataFrame(rows)
    return table.drop_duplicates(
        subset=["group_type", "group_value", "per_group_threshold", "suppressed"]
    )
