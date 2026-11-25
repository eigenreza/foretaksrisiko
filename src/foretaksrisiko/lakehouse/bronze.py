"""Bronze: landing Parquet as landed, plus snapshot_id, snapshot_date and ingestion time."""

from __future__ import annotations

import glob
import json
import logging
from datetime import date, datetime

from foretaksrisiko.lakehouse.session import Names, ensure_schemas, write_snapshot

log = logging.getLogger(__name__)


def read_manifest(landing_root: str) -> dict:
    with open(f"{landing_root}/manifest.json", encoding="utf-8") as handle:
        return json.load(handle)


def snapshot_date_from_manifest(manifest: dict) -> date:
    """The production date of the unit bulk file is the reference date of the snapshot."""
    section = manifest.get("enheter") or {}
    iso = (section.get("source") or {}).get("last_modified_iso") or section.get("updated_at")
    if not iso:
        raise ValueError("manifest has no time for the enheter bulk file")
    return datetime.fromisoformat(iso).date()


def has_parquet(path: str) -> bool:
    return bool(glob.glob(f"{path}/*.parquet"))


def load_bronze(
    spark,
    names: Names,
    landing_root: str,
    snapshot_id: int,
    tables: list[str],
    klass_tables: list[str],
) -> dict[str, int]:
    """Load every landing table present for the snapshot into bronze Delta tables."""
    from pyspark.sql import functions as F

    ensure_schemas(spark, names, ("bronze",))
    manifest = read_manifest(landing_root)
    snapshot_date = snapshot_date_from_manifest(manifest)
    sources = [(t, f"{landing_root}/{t}") for t in tables]
    sources += [(f"klass_{k}", f"{landing_root}/klass/{k}") for k in klass_tables]
    counts: dict[str, int] = {}
    for table, path in sources:
        if not has_parquet(path):
            log.info("bronze: %s not in landing, skipped", table)
            continue
        # Files of one table can differ in columns when a field was added between fetch runs.
        # Merging keeps every column and fills the gaps with null.
        df = spark.read.option("mergeSchema", "true").parquet(f"{path}/*.parquet")
        if table == "regnskap_status":
            # Status files written before the field existed carry no source snapshot. Those rows
            # were produced by requests made for this snapshot.
            source = (
                F.coalesce(F.col("source_snapshot_id"), F.lit(int(snapshot_id)))
                if "source_snapshot_id" in df.columns
                else F.lit(int(snapshot_id))
            )
            df = df.withColumn("source_snapshot_id", source.cast("int"))
        df = (
            df.withColumn("snapshot_id", F.lit(int(snapshot_id)))
            .withColumn("snapshot_date", F.lit(snapshot_date))
            .withColumn("ingested_at", F.current_timestamp())
        )
        target = names.table("bronze", table)
        write_snapshot(df, target, snapshot_id)
        counts[table] = spark.table(target).where(F.col("snapshot_id") == snapshot_id).count()
        log.info("bronze: %s snapshot %d rows %d", table, snapshot_id, counts[table])
    registry = spark.createDataFrame(
        [(int(snapshot_id), snapshot_date, json.dumps(manifest, default=str))],
        "snapshot_id INT, snapshot_date DATE, manifest_json STRING",
    ).withColumn("ingested_at", F.current_timestamp())
    write_snapshot(registry, names.table("bronze", "snapshots"), snapshot_id)
    return counts
