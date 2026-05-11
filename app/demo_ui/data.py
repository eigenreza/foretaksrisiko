"""Cached loading of the public demo data, the figures and the model artefacts.

The app reads only the files in ``demo_data/`` and ``figures/``. The root directory can be
overridden with the environment variable ``FORETAKSRISIKO_DEMO_ROOT``, which the tests use.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from foretaksrisiko.demo.synthetic import Artefacts

TEXT_COLUMNS = {
    "fylke_code": str,
    "nace_section": str,
    "group_value": str,
    "group_type": str,
    "model": str,
    "split": str,
    "ablation": str,
    "kind": str,
    "size_bin": str,
    "feature": str,
    "metric": str,
    "scenario": str,
    "severity": str,
    "side": str,
    "fylke_name": str,
    "group_label_no": str,
    "group_label_en": str,
}


def root() -> Path:
    return Path(os.environ.get("FORETAKSRISIKO_DEMO_ROOT", Path(__file__).resolve().parents[2]))


@st.cache_data(show_spinner=False)
def load_table(name: str, root_dir: str) -> pd.DataFrame | None:
    """One demo CSV as a data frame, or None when the file does not exist."""
    path = Path(root_dir) / "demo_data" / f"{name}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, dtype=TEXT_COLUMNS)


def table(name: str) -> pd.DataFrame | None:
    return load_table(name, str(root()))


@st.cache_resource(show_spinner=False)
def load_artefacts(root_dir: str) -> Artefacts | None:
    path = Path(root_dir) / "demo_data" / "model"
    if not (path / "hgb_meta.json").exists():
        return None
    return Artefacts.load(path)


def artefacts() -> Artefacts | None:
    return load_artefacts(str(root()))


def probability_quantiles() -> dict[str, float] | None:
    """Quantiles of the calibrated probability on the test split, keyed by quantile text."""
    frame = table("score_quantiles")
    if frame is None:
        return None
    rows = frame[(frame["model"] == "hgb_calibrated") & (frame["split"] == "test")]
    if rows.empty:
        return None
    pairs = zip(rows["quantile"], rows["value"], strict=True)
    return {f"{float(q):.2f}": float(v) for q, v in pairs}


def figure_path(name: str, lang: str) -> Path | None:
    path = root() / "figures" / f"{name}_{lang}.svg"
    return path if path.exists() else None
