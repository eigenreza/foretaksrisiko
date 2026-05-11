"""Score a snapshot with the champion model and write gold.champion_scores."""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from foretaksrisiko.config import Settings
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, table_exists, write_partitions
from foretaksrisiko.registry.client import Registry

log = logging.getLogger(__name__)

CHUNK_ROWS = 100_000
SCORE_COLUMNS = [
    "organisasjonsnummer",
    "design",
    "snapshot_id",
    "model_name",
    "model_version",
    "score",
]


def load_champion(registry: Registry):
    """The champion model version and the loaded pyfunc model, or (None, None)."""
    import mlflow

    champion = registry.version_by_alias(registry.cfg.champion_alias)
    if champion is None:
        return None, None
    model = mlflow.pyfunc.load_model(f"models:/{registry.model_name}/{champion.version}")
    return champion, model


def predict_scores(model, frame: pd.DataFrame) -> np.ndarray:
    """Calibrated probabilities from a loaded pyfunc model.

    The packaged scoring pipeline coerces types itself, so it is called directly when present;
    this avoids MLflow's signature enforcement rejecting integer columns that carry nulls.
    """
    unwrap = getattr(model, "unwrap_python_model", None)
    inner = unwrap() if callable(unwrap) else None
    pipeline = getattr(inner, "pipeline", None)
    if pipeline is not None:
        return np.asarray(pipeline.predict(frame), dtype="float64")
    return np.asarray(model.predict(frame), dtype="float64").reshape(-1)


def already_scored(spark, names: Names, snapshot_id: int, design: str, version: str) -> bool:
    table = names.table("gold", "champion_scores")
    if not table_exists(spark, table):
        return False
    return (
        spark.table(table)
        .where(
            f"snapshot_id = {snapshot_id} AND design = '{design}' AND model_version = '{version}'"
        )
        .limit(1)
        .count()
        > 0
    )


def score_snapshot(
    spark, names: Names, snapshot_id: int, design: str, model, model_name: str, version: str
) -> dict:
    """Score every company in the snapshot's feature table and replace that snapshot partition."""
    from pyspark.sql import functions as F

    features = names.table("gold", "features")
    frame = spark.table(features).where(
        f"design = '{design}' AND reference_snapshot_id = {snapshot_id}"
    )
    rows = frame.count()
    if rows == 0:
        raise ValueError(f"no {design} features for snapshot {snapshot_id}")
    chunks = max(1, math.ceil(rows / CHUNK_ROWS))
    frame = frame.withColumn(
        "_chunk", F.pmod(F.xxhash64(F.col("organisasjonsnummer")), F.lit(chunks))
    )
    parts: list[pd.DataFrame] = []
    for chunk in range(chunks):
        pdf = frame.where(F.col("_chunk") == chunk).drop("_chunk").toPandas()
        if pdf.empty:
            continue
        parts.append(
            pd.DataFrame(
                {
                    "organisasjonsnummer": pdf["organisasjonsnummer"].to_numpy(),
                    "design": design,
                    "snapshot_id": int(snapshot_id),
                    "model_name": model_name,
                    "model_version": str(version),
                    "score": predict_scores(model, pdf),
                }
            )
        )
    scores = pd.concat(parts, ignore_index=True)
    sdf = spark.createDataFrame(
        scores,
        "organisasjonsnummer STRING, design STRING, snapshot_id INT, model_name STRING, "
        "model_version STRING, score DOUBLE",
    ).withColumn("scored_at", F.current_timestamp())
    ensure_schemas(spark, names, ("gold",))
    write_partitions(
        sdf,
        names.table("gold", "champion_scores"),
        ["snapshot_id"],
        f"snapshot_id = {snapshot_id}",
    )
    log.info(
        "scored snapshot %d with %s version %s: %d rows", snapshot_id, model_name, version, rows
    )
    return {"snapshot_id": snapshot_id, "rows": int(rows), "model_version": str(version)}


def score_with_champion(
    spark, names: Names, settings: Settings, registry: Registry, snapshot_id: int
) -> dict:
    """Score the snapshot, and the champion's training snapshot when it has no scores yet.

    The training snapshot is the monitoring reference, so its scores by the same version must
    exist before prediction drift can be computed. Without a champion the stage writes nothing
    and reports it; the monitoring stage records that as a warning.
    """
    design = settings.monitoring.design
    champion, model = load_champion(registry)
    if champion is None:
        log.warning("no champion alias on %s; scoring skipped", registry.model_name)
        return {"status": "no_champion", "snapshot_id": snapshot_id, "scored": []}
    version = str(champion.version)
    tags = dict(champion.tags or {})
    training_snapshot = int(tags["snapshot_id"]) if tags.get("snapshot_id") else None
    scored = []
    targets = [s for s in (training_snapshot, snapshot_id) if s is not None]
    for sid in dict.fromkeys(targets):
        if sid != snapshot_id and already_scored(spark, names, sid, design, version):
            continue
        scored.append(
            score_snapshot(spark, names, sid, design, model, registry.model_name, version)
        )
    return {
        "status": "scored",
        "snapshot_id": snapshot_id,
        "model_version": version,
        "training_snapshot_id": training_snapshot,
        "scored": scored,
    }
