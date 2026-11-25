"""Export the demo's model artefacts: fitted parameters and aggregates, never training rows.

Everything is written to one directory (``demo_data/model`` by default) and shipped with the
Streamlit demo:

- ``hgb_calibrated.joblib``: the champion's gradient boosting model and its isotonic calibrator.
  Both store split thresholds and fitted statistics, not rows.
- ``hgb_meta.json``: feature list, categorical levels, fill values, hyperparameters and the
  registry version the model came from.
- ``mahalanobis.json``: robust centre, scale and precision matrix for the peer z-scores, the
  medians used to impute missing z-scores, and the quantiles of the distance on reference rows.
- ``peer_stats.csv``: median and MAD per peer group and ratio feature, groups of at least 20.
- ``peer_quantiles.csv``: a quantile grid per peer group and ratio feature, groups of at least 20.
- ``feature_defaults.csv``: the population median or mode of every model feature.
- ``size_bands.csv``: the range of log total assets per size band.
- ``nace_divisions.csv`` and ``fylker.csv``: code lists from Klass in Norwegian and English.

Floats are written with six significant digits, so that no file can contain a nine-digit
number that looks like an organisation number.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from foretaksrisiko.config import HttpConfig, KlassConfig, ModelConfig, Settings
from foretaksrisiko.demo.synthetic import (
    DEFAULTS_FILE,
    DIVISIONS_FILE,
    FYLKER_FILE,
    MAHALANOBIS_FILE,
    META_FILE,
    MODEL_FILE,
    PEER_QUANTILES_FILE,
    PEER_STATS_FILE,
    QUANTILE_GRID,
    RATIO_FEATURES,
    SIZE_BANDS_FILE,
    SVALBARD,
    quantile_column,
)
from foretaksrisiko.figures.export import MIN_GROUP, Query, write_csv
from foretaksrisiko.lakehouse.session import Names
from foretaksrisiko.models.anomaly import RobustMahalanobis
from foretaksrisiko.models.supervised import FittedSupervised

log = logging.getLogger(__name__)

SCORE_QUANTILES = [round(i / 100, 2) for i in range(1, 100)]


NINE_DIGITS = re.compile(r"\d{9}")


def _fmt(value) -> str | None:
    """Six significant digits as text, never nine digits in a row: scientific notation otherwise."""
    if value is None or value == "":
        return None
    number = float(value)
    if np.isnan(number):
        return None
    text = format(number, ".6g")
    return format(number, ".6e") if NINE_DIGITS.search(text) else text


def _num(value) -> float | str | None:
    """A float whose JSON form shows no nine digits in a row, else scientific-notation text."""
    text = _fmt(value)
    if text is None:
        return None
    for digits in (6, 5, 4, 3):
        number = float(format(float(text), f".{digits}g"))
        if not NINE_DIGITS.search(repr(number)):
            return number
    return format(float(text), ".6e")


def _int(value) -> int | None:
    return None if value in (None, "") else int(float(value))


def _array(value) -> list[float | None]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    return [None if v is None else float(v) for v in value]


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


# -- champion model ------------------------------------------------------------------------------


def load_champion(model_name: str, alias: str) -> tuple[FittedSupervised, dict]:
    """Load the fitted supervised model behind a registry alias, plus its version metadata."""
    import mlflow
    from mlflow import MlflowClient

    version = MlflowClient().get_model_version_by_alias(model_name, alias)
    model = mlflow.pyfunc.load_model(f"models:/{model_name}@{alias}")
    fitted = model._model_impl.python_model.pipeline.fitted
    info = {
        "model_name": model_name,
        "alias": alias,
        "version": str(version.version),
        "tags": dict(version.tags),
    }
    return fitted, info


def save_model(fitted: FittedSupervised, info: dict, out: Path) -> int:
    """Write the estimators and a JSON description. Returns the number of features."""
    import joblib
    import sklearn

    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": fitted.model, "calibrated": fitted.calibrated}, out / MODEL_FILE, compress=3
    )
    meta = {
        **info,
        "features": list(fitted.features),
        "categorical": list(fitted.categorical),
        "categories": {k: list(v) for k, v in fitted.categories.items()},
        "fill_values": dict(fitted.fill_values),
        "params": dict(fitted.params),
        "sklearn_version": sklearn.__version__,
    }
    (out / META_FILE).write_text(
        json.dumps(meta, indent=1, default=_json_default, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(fitted.features)


# -- aggregates from the gold layer ----------------------------------------------------------------


def _where(design: str, snapshot_id: int) -> str:
    return f"design = '{design}' AND reference_snapshot_id = {snapshot_id}"


def _reference_where(names: Names, design: str, snapshot_id: int, scope: str) -> str:
    """Rows that match the champion's training frame: eligible companies, and only the
    development sample when the model was trained on it."""
    labels = names.table("gold", "labels")
    company = names.table("gold", "company_snapshot")
    where = (
        f"{_where(design, snapshot_id)} AND organisasjonsnummer IN "
        f"(SELECT organisasjonsnummer FROM {labels} WHERE {_where(design, snapshot_id)} "
        "AND eligible)"
    )
    if scope == "sample":
        where += (
            f" AND organisasjonsnummer IN (SELECT organisasjonsnummer FROM {company} "
            f"WHERE snapshot_id = {snapshot_id} AND in_dev_sample)"
        )
    return where


def export_peer_stats(query: Query, names: Names, design: str, snapshot_id: int, out: Path) -> int:
    rows = query(
        "SELECT peer_group, feature, n, median, mad "
        f"FROM {names.table('gold', 'peer_stats')} WHERE {_where(design, snapshot_id)} "
        f"AND n >= {MIN_GROUP} ORDER BY peer_group, feature"
    )
    table = [
        {
            "peer_group": r["peer_group"],
            "feature": r["feature"],
            "n": _int(r["n"]),
            "median": _fmt(r["median"]),
            "mad": _fmt(r["mad"]),
        }
        for r in rows
    ]
    return write_csv(out / PEER_STATS_FILE, table, ["peer_group", "feature", "n", "median", "mad"])


def export_peer_quantiles(
    query: Query, names: Names, design: str, snapshot_id: int, out: Path
) -> int:
    features = names.table("gold", "features")
    grid = ", ".join(str(q) for q in QUANTILE_GRID)
    columns = ["peer_group", "feature", "n"] + [quantile_column(q) for q in QUANTILE_GRID]
    table: list[dict] = []
    for feature in RATIO_FEATURES:
        rows = query(
            f"SELECT peer_group, count({feature}) AS n, "
            f"percentile_approx({feature}, array({grid}), 10000) AS q "
            f"FROM {features} WHERE {_where(design, snapshot_id)} AND {feature} IS NOT NULL "
            f"GROUP BY peer_group HAVING count({feature}) >= {MIN_GROUP} ORDER BY peer_group"
        )
        for r in rows:
            row = {"peer_group": r["peer_group"], "feature": feature, "n": _int(r["n"])}
            for q, value in zip(QUANTILE_GRID, _array(r["q"]), strict=True):
                row[quantile_column(q)] = _fmt(value)
            table.append(row)
    return write_csv(out / PEER_QUANTILES_FILE, table, columns)


def export_feature_defaults(
    query: Query,
    names: Names,
    design: str,
    snapshot_id: int,
    fitted: FittedSupervised,
    out: Path,
    scope: str = "population",
) -> int:
    """Median of every numeric feature and mode of every categorical feature, over the rows
    the champion was trained on."""
    features = names.table("gold", "features")
    where = _reference_where(names, design, snapshot_id, scope)
    numeric = [
        c
        for c in fitted.features
        if c not in fitted.categorical and not c.startswith(("z_", "pct_")) and c != "n_extreme_z"
    ]
    table: list[dict] = []
    for start in range(0, len(numeric), 60):
        batch = numeric[start : start + 60]
        exprs = ", ".join(
            f"percentile_approx(CAST({c} AS DOUBLE), 0.5, 1000) AS {c}" for c in batch
        )
        medians = query(f"SELECT {exprs} FROM {features} WHERE {where}")[0]
        table.extend({"feature": c, "kind": "numeric", "value": _fmt(medians[c])} for c in batch)
    for column in fitted.categorical:
        top = query(
            f"SELECT {column} AS value, count(*) AS n FROM {features} WHERE {where} "
            f"AND {column} IS NOT NULL GROUP BY {column} ORDER BY n DESC LIMIT 1"
        )
        table.append(
            {"feature": column, "kind": "categorical", "value": top[0]["value"] if top else ""}
        )
    return write_csv(out / DEFAULTS_FILE, table, ["feature", "kind", "value"])


def export_size_bands(query: Query, names: Names, design: str, snapshot_id: int, out: Path) -> int:
    rows = query(
        "SELECT size_band, min(log_assets) AS lo, max(log_assets) AS hi, count(*) AS n "
        f"FROM {names.table('gold', 'features')} WHERE {_where(design, snapshot_id)} "
        "GROUP BY size_band ORDER BY size_band"
    )
    table = [
        {"band": str(r["size_band"]), "lo": _fmt(r["lo"]), "hi": _fmt(r["hi"]), "n": _int(r["n"])}
        for r in rows
    ]
    return write_csv(out / SIZE_BANDS_FILE, table, ["band", "lo", "hi", "n"])


def fit_mahalanobis(
    query: Query,
    names: Names,
    design: str,
    snapshot_id: int,
    cfg: ModelConfig,
    out: Path,
    scope: str = "population",
) -> int:
    """Fit the robust Mahalanobis model on reference z-scores and keep only its parameters.

    The rows are read into memory, used for the fit and discarded. The file holds the centre,
    scale, imputation medians, robust location, precision matrix and distance quantiles.
    """
    columns = [f"z_{f}" for f in RATIO_FEATURES]
    rows = query(
        f"SELECT {', '.join(columns)} FROM {names.table('gold', 'features')} "
        f"WHERE {_reference_where(names, design, snapshot_id, scope)} "
        f"ORDER BY xxhash64(organisasjonsnummer) LIMIT {cfg.mahalanobis_fit_rows}"
    )
    matrix = pd.DataFrame(rows, columns=columns).apply(pd.to_numeric, errors="coerce")
    matrix = matrix.astype("float64")
    impute = matrix.median()
    matrix = matrix.fillna(impute).fillna(0.0)
    fitted = RobustMahalanobis.fit(matrix, cfg, cfg.seeds[0])
    distances = fitted.score(matrix)
    payload = {
        "columns": list(fitted.columns),
        "center": [_num(v) for v in fitted.center],
        "scale": [_num(v) for v in fitted.scale],
        "impute": {c: _num(impute[c]) for c in fitted.columns},
        "location": [_num(v) for v in fitted.estimator.location_],
        "precision": [[_num(v) for v in row] for row in fitted.estimator.precision_],
        "n_rows": int(len(matrix)),
        "score_quantiles": {f"{q:.2f}": _num(np.quantile(distances, q)) for q in SCORE_QUANTILES},
    }
    (out / MAHALANOBIS_FILE).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return int(len(matrix))


# -- code lists from Klass ----------------------------------------------------------------------


def export_code_lists(http: HttpConfig, klass: KlassConfig, out: Path) -> dict[str, int]:
    """Industry divisions and counties in Norwegian and English, from SSB Klass (CC BY 4.0)."""
    import httpx

    def fetch(version: int, language: str) -> list[dict]:
        response = httpx.get(
            f"{klass.base_url}/versions/{version}",
            params={"language": language},
            headers={"User-Agent": http.user_agent, "Accept": "application/json"},
            timeout=http.timeout_seconds,
        )
        response.raise_for_status()
        time.sleep(1.0 / http.requests_per_second)
        return response.json()["classificationItems"]

    sn_no = fetch(klass.sn2025_version, "nb")
    sn_en = {i["code"]: i["name"] for i in fetch(klass.sn2025_version, "en")}
    divisions = [
        {
            "code": i["code"],
            "section": i["parentCode"],
            "name_no": i["name"],
            "name_en": sn_en.get(i["code"], i["name"]),
        }
        for i in sn_no
        if i["level"] == "2"
    ]
    fylke_no = fetch(klass.fylke_version, "nb")
    fylke_en = {i["code"]: i["name"] for i in fetch(klass.fylke_version, "en")}
    fylker = [
        {"code": i["code"], "name_no": i["name"], "name_en": fylke_en.get(i["code"], i["name"])}
        for i in fylke_no
    ]
    fylker.append({"code": SVALBARD, "name_no": "Svalbard", "name_en": "Svalbard"})
    fylker.sort(key=lambda r: r["code"])
    return {
        DIVISIONS_FILE: write_csv(
            out / DIVISIONS_FILE, divisions, ["code", "section", "name_no", "name_en"]
        ),
        FYLKER_FILE: write_csv(out / FYLKER_FILE, fylker, ["code", "name_no", "name_en"]),
    }


# -- orchestration -------------------------------------------------------------------------------


def export_all(
    query: Query,
    names: Names,
    settings: Settings,
    out: Path,
    model_name: str,
    alias: str,
    fitted: FittedSupervised | None = None,
    info: dict | None = None,
) -> dict[str, int]:
    """Write every demo artefact for the model behind ``alias``. Returns row counts per file."""
    if fitted is None or info is None:
        fitted, info = load_champion(model_name, alias)
    tags = info.get("tags", {})
    design = tags.get("design", "retro")
    snapshot_id = int(tags.get("snapshot_id", 1))
    scope = tags.get("scope", "population")
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    counts[MODEL_FILE] = save_model(fitted, info, out)
    counts[PEER_STATS_FILE] = export_peer_stats(query, names, design, snapshot_id, out)
    counts[PEER_QUANTILES_FILE] = export_peer_quantiles(query, names, design, snapshot_id, out)
    counts[DEFAULTS_FILE] = export_feature_defaults(
        query, names, design, snapshot_id, fitted, out, scope
    )
    counts[SIZE_BANDS_FILE] = export_size_bands(query, names, design, snapshot_id, out)
    counts[MAHALANOBIS_FILE] = fit_mahalanobis(
        query, names, design, snapshot_id, settings.model, out, scope
    )
    counts.update(export_code_lists(settings.http, settings.klass, out))
    log.info("demo artefacts written to %s: %s", out, counts)
    return counts
