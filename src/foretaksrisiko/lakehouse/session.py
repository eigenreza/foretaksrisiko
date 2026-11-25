"""One SparkSession factory and one naming scheme for local Spark and Databricks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from foretaksrisiko.config import LakehouseConfig, Settings

DATABRICKS_HINTS = ("DATABRICKS_RUNTIME_VERSION", "DB_IS_DRIVER", "SPARK_CONNECT_MODE_ENABLED")


def on_databricks() -> bool:
    """True inside a Databricks job, notebook or serverless task."""
    if os.environ.get("FORETAKSRISIKO_FORCE_LOCAL") == "1":
        return False
    return any(h in os.environ for h in DATABRICKS_HINTS) or os.path.isdir("/databricks")


@dataclass(frozen=True)
class Names:
    """Fully qualified names: ``catalog.<prefix><layer>.<table>``."""

    catalog: str
    prefix: str
    volume_name: str = "snapshots"

    @classmethod
    def from_config(cls, cfg: LakehouseConfig, local: bool) -> Names:
        return cls(
            catalog=cfg.local_catalog if local else cfg.catalog,
            prefix=cfg.schema_prefix,
            volume_name=cfg.volume_name,
        )

    def schema(self, layer: str) -> str:
        return f"{self.catalog}.{self.prefix}{layer}"

    def table(self, layer: str, name: str) -> str:
        return f"{self.schema(layer)}.{name}"

    @property
    def volume_root(self) -> str:
        return f"/Volumes/{self.catalog}/{self.prefix}landing/{self.volume_name}"

    def snapshot_root(self, snapshot_id: int) -> str:
        return f"{self.volume_root}/snapshot={snapshot_id}"


def landing_root(settings: Settings, names: Names, snapshot_id: int, local: bool) -> str:
    if local:
        return str((Path(settings.paths.landing_dir) / f"snapshot={snapshot_id}").resolve())
    return names.snapshot_root(snapshot_id)


def get_spark(
    cfg: LakehouseConfig, warehouse_dir: Path | None = None, app_name: str = "foretaksrisiko"
):
    """Return the Databricks session when running there, otherwise a local Delta-enabled session."""
    from pyspark.sql import SparkSession

    if on_databricks():
        return SparkSession.builder.getOrCreate()
    from delta import configure_spark_with_delta_pip

    warehouse = Path(warehouse_dir or cfg.local_warehouse_dir).resolve()
    warehouse.mkdir(parents=True, exist_ok=True)
    builder = (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config("spark.sql.warehouse.dir", warehouse.as_uri())
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.driver.memory", "3g")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


def ensure_schemas(
    spark, names: Names, layers: tuple[str, ...] = ("bronze", "silver", "gold", "monitoring")
) -> None:
    for layer in layers:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {names.schema(layer)}")


def table_exists(spark, name: str) -> bool:
    return spark.catalog.tableExists(name)


def write_snapshot(df, table: str, snapshot_id: int) -> None:
    """Idempotent write of one snapshot partition into a Delta table partitioned by snapshot_id."""
    if table_exists(df.sparkSession, table):
        (
            df.write.format("delta")
            .mode("overwrite")
            .option("replaceWhere", f"snapshot_id = {int(snapshot_id)}")
            .option("mergeSchema", "true")
            .saveAsTable(table)
        )
    else:
        df.write.format("delta").mode("overwrite").partitionBy("snapshot_id").saveAsTable(table)


def write_partitions(df, table: str, partition_columns: list[str], where: str) -> None:
    """Idempotent write of the rows selected by ``where`` into a multi-column partitioned table."""
    if table_exists(df.sparkSession, table):
        df.write.format("delta").mode("overwrite").option("replaceWhere", where).saveAsTable(table)
    else:
        df.write.format("delta").mode("overwrite").partitionBy(*partition_columns).saveAsTable(
            table
        )


def overwrite_table(df, table: str) -> None:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)


def table_version(spark, table: str) -> int | None:
    """Current Delta version of a table, for lineage in MLflow runs and manifests."""
    if not table_exists(spark, table):
        return None
    row = spark.sql(f"DESCRIBE HISTORY {table} LIMIT 1").collect()
    return int(row[0]["version"]) if row else None
