"""Monitoring stage on the lakehouse: drift tables, score summaries, alerts and retraining advice.

Reads the prospective features of the current and the reference snapshot (the champion's
training snapshot unless another is given), the champion scores for both, and the matured labels
since the champion was trained. Writes ``monitoring.drift``, ``monitoring.score_summary`` and
``monitoring.alerts``, replacing earlier rows for the same snapshot and scenario, so a rerun is
idempotent. The alert stage then fails when alert-level records exist.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from foretaksrisiko.config import MonitoringConfig, Settings
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, table_exists
from foretaksrisiko.monitoring.alerts import (
    ALERT_COLUMNS,
    Alert,
    alert_frame,
    alerts_from_drift,
    raise_on_alerts,
    retraining_decision,
)
from foretaksrisiko.monitoring.drift import (
    DRIFT_COLUMNS,
    drift_table,
    flag_threshold,
    monitored_columns,
    score_drift,
    score_summary,
)
from foretaksrisiko.registry.client import Registry

log = logging.getLogger(__name__)

MAX_ROWS_PER_SIDE = 200_000
DRIFT_SCHEMA = (
    "feature STRING, kind STRING, metric STRING, reference_value DOUBLE, current_value DOUBLE, "
    "value DOUBLE, warn_threshold DOUBLE, alert_threshold DOUBLE, severity STRING, level STRING, "
    "rows_reference BIGINT, rows_current BIGINT"
)
ALERT_SCHEMA = (
    "alert_type STRING, feature STRING, value DOUBLE, threshold DOUBLE, severity STRING, "
    "message STRING"
)
SUMMARY_COLUMNS = [
    "side",
    "scored_snapshot_id",
    "rows",
    "mean_score",
    "flag_threshold",
    "flag_share",
    "p50",
    "p90",
    "p99",
]
SUMMARY_SCHEMA = (
    "side STRING, scored_snapshot_id INT, rows BIGINT, mean_score DOUBLE, flag_threshold DOUBLE, "
    "flag_share DOUBLE, p50 DOUBLE, p90 DOUBLE, p99 DOUBLE"
)
STAMP_TYPES = {
    "snapshot_id": "int",
    "reference_snapshot_id": "int",
    "design": "string",
    "scenario": "string",
    "model_version": "string",
}


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return None if isinstance(value, float) and np.isnan(value) else value


def _rows(pdf: pd.DataFrame, columns: list[str]) -> list[list]:
    return [[_clean(v) for v in row] for row in pdf[columns].itertuples(index=False, name=None)]


def _feature_frame(spark, names: Names, snapshot_id: int, design: str) -> pd.DataFrame:
    """Monitored feature columns of one snapshot, deterministically thinned when very large."""
    from pyspark.sql import functions as F

    frame = spark.table(names.table("gold", "features")).where(
        f"design = '{design}' AND reference_snapshot_id = {snapshot_id}"
    )
    frame = frame.select(*[c for c in frame.columns if not c.startswith("masked_")])
    rows = frame.count()
    if rows > MAX_ROWS_PER_SIDE:
        keep = int(MAX_ROWS_PER_SIDE / rows * 10_000)
        frame = frame.where(
            F.pmod(F.xxhash64(F.col("organisasjonsnummer")), F.lit(10_000)) < F.lit(keep)
        )
    return frame.toPandas()


def _scores(spark, names: Names, snapshot_id: int, design: str, version: str) -> np.ndarray | None:
    table = names.table("gold", "champion_scores")
    if not table_exists(spark, table):
        return None
    pdf = (
        spark.table(table)
        .where(
            f"snapshot_id = {snapshot_id} AND design = '{design}' AND model_version = '{version}'"
        )
        .select("score")
        .toPandas()
    )
    return None if pdf.empty else pdf["score"].to_numpy(dtype="float64")


def _new_positives(
    spark, names: Names, design: str, after_snapshot: int | None, up_to_snapshot: int
) -> int | None:
    """Fully observed strict positives in snapshots after the champion's training snapshot."""
    table = names.table("gold", "labels")
    if after_snapshot is None or not table_exists(spark, table):
        return None
    row = spark.sql(
        f"""
        SELECT count(*) AS n FROM {table}
        WHERE design = '{design}' AND fully_observed AND label_strict AND eligible
          AND reference_snapshot_id > {after_snapshot} AND reference_snapshot_id <= {up_to_snapshot}
        """
    ).first()
    return int(row["n"])


def _previous_snapshot(spark, names: Names, snapshot_id: int, design: str) -> int | None:
    row = spark.sql(
        f"SELECT max(reference_snapshot_id) AS s FROM {names.table('gold', 'features')} "
        f"WHERE design = '{design}' AND reference_snapshot_id < {snapshot_id}"
    ).first()
    return None if row is None or row["s"] is None else int(row["s"])


def _replace_rows(
    spark, names: Names, table: str, pdf: pd.DataFrame, columns: list[str], schema: str, stamp: dict
) -> None:
    """Delete this snapshot and scenario's earlier rows, then append the new ones."""
    from pyspark.sql import functions as F

    name = names.table("monitoring", table)
    if table_exists(spark, name):
        spark.sql(
            f"DELETE FROM {name} WHERE snapshot_id = {stamp['snapshot_id']} "
            f"AND scenario = '{stamp['scenario']}'"
        )
    if pdf.empty:
        return
    sdf = spark.createDataFrame(_rows(pdf, columns), schema)
    for key, value in stamp.items():
        sdf = sdf.withColumn(key, F.lit(value).cast(STAMP_TYPES[key]))
    sdf = sdf.withColumn("logged_at", F.current_timestamp())
    sdf.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(name)


def monitor_snapshot(
    spark,
    names: Names,
    settings: Settings,
    registry: Registry,
    snapshot_id: int,
    reference_snapshot_id: int | None = None,
    scenario: str = "default",
) -> dict:
    cfg: MonitoringConfig = settings.monitoring.with_scenario(scenario)
    design = cfg.design
    champion = registry.version_by_alias(registry.cfg.champion_alias)
    version = None if champion is None else str(champion.version)
    tags = dict(champion.tags or {}) if champion is not None else {}
    champion_snapshot = int(tags["snapshot_id"]) if tags.get("snapshot_id") else None
    reference = reference_snapshot_id or champion_snapshot
    if reference is None or reference == snapshot_id:
        reference = _previous_snapshot(spark, names, snapshot_id, design)
    ensure_schemas(spark, names, ("monitoring",))
    stamp = {
        "snapshot_id": int(snapshot_id),
        "reference_snapshot_id": None if reference is None else int(reference),
        "design": design,
        "scenario": scenario,
        "model_version": version,
    }
    extra: list[Alert] = []
    if reference is None:
        extra.append(
            Alert("no_reference", None, None, None, "warn", "no reference snapshot to compare with")
        )
        alerts = alert_frame(extra)
        _replace_rows(spark, names, "alerts", alerts, ALERT_COLUMNS, ALERT_SCHEMA, stamp)
        return {**stamp, "status": "no_reference", "alerts_warn": int(len(alerts))}

    current = _feature_frame(spark, names, snapshot_id, design)
    previous = _feature_frame(spark, names, reference, design)
    drift = drift_table(previous, current, cfg)
    numeric, categorical = monitored_columns(previous)
    summaries = pd.DataFrame(columns=SUMMARY_COLUMNS)
    if version is None:
        extra.append(Alert("no_champion", None, None, None, "warn", "no champion to score with"))
    else:
        ref_scores = _scores(spark, names, reference, design, version)
        cur_scores = _scores(spark, names, snapshot_id, design, version)
        if ref_scores is None or cur_scores is None:
            extra.append(
                Alert(
                    "no_champion_scores",
                    None,
                    None,
                    None,
                    "warn",
                    f"champion version {version} has not scored both snapshots",
                )
            )
        else:
            drift = pd.concat([drift, score_drift(ref_scores, cur_scores, cfg)], ignore_index=True)
            threshold = flag_threshold(ref_scores, cfg.flag_share)
            summaries = pd.DataFrame(
                [
                    {
                        "side": "reference",
                        "scored_snapshot_id": reference,
                        **score_summary(ref_scores, threshold),
                    },
                    {
                        "side": "current",
                        "scored_snapshot_id": snapshot_id,
                        **score_summary(cur_scores, threshold),
                    },
                ]
            )
    age = None if champion_snapshot is None else int(snapshot_id) - champion_snapshot
    new_positives = _new_positives(spark, names, design, champion_snapshot, snapshot_id)
    decision = retraining_decision(drift, cfg, age, new_positives)
    alerts = alert_frame(alerts_from_drift(drift) + extra, decision)

    _replace_rows(spark, names, "drift", drift, DRIFT_COLUMNS, DRIFT_SCHEMA, stamp)
    _replace_rows(spark, names, "score_summary", summaries, SUMMARY_COLUMNS, SUMMARY_SCHEMA, stamp)
    _replace_rows(spark, names, "alerts", alerts, ALERT_COLUMNS, ALERT_SCHEMA, stamp)
    counts = alerts["severity"].value_counts().to_dict() if not alerts.empty else {}
    summary = {
        **stamp,
        "status": "monitored",
        "rows_reference": int(len(previous)),
        "rows_current": int(len(current)),
        "features_monitored": len(numeric) + len(categorical),
        "drift_rows": int(len(drift)),
        "alerts_alert": int(counts.get("alert", 0)),
        "alerts_warn": int(counts.get("warn", 0)),
        "champion_age_snapshots": age,
        "new_positives": new_positives,
        "retraining_recommended": decision.recommended,
        "retraining_reasons": decision.reasons,
    }
    log.info("monitoring done: %s", summary)
    return summary


def check_alerts(spark, names: Names, snapshot_id: int, scenario: str = "default") -> int:
    """Raise ``AlertBreach`` when alert-level records exist; return the number of records read."""
    table = names.table("monitoring", "alerts")
    if not table_exists(spark, table):
        return 0
    pdf = (
        spark.table(table)
        .where(f"snapshot_id = {snapshot_id} AND scenario = '{scenario}'")
        .select(*ALERT_COLUMNS)
        .toPandas()
    )
    raise_on_alerts(pdf, snapshot_id, scenario)
    return int(len(pdf))
