"""Global explanations only: mean absolute SHAP per feature for the supervised model."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def _encode(matrix: pd.DataFrame, categorical: list[str]) -> pd.DataFrame:
    """Categorical columns as integer codes so the explainer sees numbers only."""
    encoded = matrix.copy()
    for column in categorical:
        encoded[column] = matrix[column].cat.codes.astype("float32")
    return encoded.astype("float32")


def _decoder(columns: list[str], categorical: list[str], categories: dict[str, list[str]]):
    def decode(values: np.ndarray) -> pd.DataFrame:
        frame = pd.DataFrame(np.asarray(values, dtype="float32"), columns=columns)
        for column in categorical:
            codes = frame[column].round().fillna(-1).astype(int).to_numpy()
            codes = np.where((codes >= 0) & (codes < len(categories[column])), codes, -1)
            frame[column] = pd.Categorical.from_codes(codes, categories=categories[column])
        return frame

    return decode


def shap_summary(
    predict: Callable[[pd.DataFrame], np.ndarray],
    matrix: pd.DataFrame,
    categorical: list[str],
    categories: dict[str, list[str]],
    rows: int,
    seed: int = 0,
) -> pd.DataFrame:
    """Mean absolute SHAP per feature from a permutation explainer on a random sample of rows.

    The permutation explainer is model-agnostic, so categorical splits are explained correctly;
    the tree explainer cannot read this model's categorical bitsets.
    """
    import shap

    rng = np.random.default_rng(seed)
    encoded = _encode(matrix, categorical)
    sample_idx = rng.choice(len(encoded), size=min(rows, len(encoded)), replace=False)
    background_idx = rng.choice(len(encoded), size=min(100, len(encoded)), replace=False)
    decode = _decoder(list(encoded.columns), categorical, categories)
    masker = shap.maskers.Independent(encoded.iloc[background_idx].to_numpy(), max_samples=100)
    explainer = shap.PermutationExplainer(lambda values: predict(decode(values)), masker, seed=seed)
    explanation = explainer(encoded.iloc[sample_idx].to_numpy(), max_evals=2 * encoded.shape[1] + 1)
    values = np.asarray(explanation.values)
    if values.ndim == 3:
        values = values[:, :, -1]
    table = pd.DataFrame(
        {
            "feature": list(encoded.columns),
            "mean_abs_shap": np.abs(values).mean(axis=0),
            "mean_shap": values.mean(axis=0),
        }
    )
    return table.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
