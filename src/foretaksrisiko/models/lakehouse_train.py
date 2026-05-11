"""Train and evaluate on the gold tables, log to MLflow, write result tables to the lakehouse."""

from __future__ import annotations

import logging

from foretaksrisiko.config import Settings
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, on_databricks, table_version
from foretaksrisiko.models.train import log_to_mlflow, run_experiment
from foretaksrisiko.registry.client import make_registry, write_events

log = logging.getLogger(__name__)


def load_training_frame(spark, names: Names, snapshot_id: int, design: str, sample_only: bool):
    features = names.table("gold", "features")
    labels = names.table("gold", "labels")
    company = names.table("gold", "company_snapshot")
    sample_filter = "AND c.in_dev_sample" if sample_only else ""
    frame = spark.sql(
        f"""
        SELECT f.*, l.label_strict, l.label_broad, l.eligible
        FROM {features} f
        JOIN {labels} l
          ON l.organisasjonsnummer = f.organisasjonsnummer AND l.design = f.design
         AND l.reference_snapshot_id = f.reference_snapshot_id
        JOIN {company} c ON c.organisasjonsnummer = f.organisasjonsnummer AND c.snapshot_id = {snapshot_id}
        WHERE f.design = '{design}' AND f.reference_snapshot_id = {snapshot_id} AND l.eligible {sample_filter}
        """
    )
    pdf = frame.toPandas()
    for column in pdf.columns:
        if str(pdf[column].dtype) in ("float64",):
            pdf[column] = pdf[column].astype("float32")
    return pdf


def train_on_lakehouse(
    spark,
    names: Names,
    settings: Settings,
    snapshot_id: int,
    design: str,
    sample_only: bool,
    register: bool = True,
) -> dict:
    """Train, evaluate, log to MLflow and, by default, register the run as the challenger.

    Retraining never produces a champion directly: the new version gets the challenger alias and
    the promotion rule is evaluated and recorded, while promotion stays a separate approved step.
    """
    import mlflow
    from pyspark.sql import functions as F

    cfg = settings.model
    frame = load_training_frame(spark, names, snapshot_id, design, sample_only)
    log.info("training frame: %d rows, %d positives", len(frame), int(frame["label_strict"].sum()))
    scope = "sample" if sample_only else "population"
    result = run_experiment(frame, design, cfg)
    user = spark.sql("SELECT current_user() AS u").first()["u"]
    mlflow.set_experiment(f"/Users/{user}/{cfg.experiment_name}")
    tags = {
        "design": design,
        "snapshot_id": str(snapshot_id),
        "scope": scope,
        "features_version": str(table_version(spark, names.table("gold", "features"))),
        "labels_version": str(table_version(spark, names.table("gold", "labels"))),
    }
    run_id = log_to_mlflow(
        result, cfg, run_name=f"{design}-snapshot{snapshot_id}-{scope}", tags=tags
    )
    ensure_schemas(spark, names, ("monitoring", "gold"))
    stamp = {
        "run_id": run_id,
        "design": design,
        "reference_snapshot_id": snapshot_id,
        "scope": scope,
    }

    def write(table: str, pdf, layer: str = "monitoring") -> None:
        if pdf is None or pdf.empty:
            return
        sdf = spark.createDataFrame(pdf.astype(object).where(pdf.notna(), None))
        for key, value in stamp.items():
            sdf = sdf.withColumn(key, F.lit(value))
        sdf = sdf.withColumn("logged_at", F.current_timestamp())
        sdf.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(
            names.table(layer, table)
        )

    write("evaluation_metrics", result.metrics)
    write("fairness", result.fairness)
    write("explanations", result.explanations)
    write("calibration", result.calibration)
    write("scores", result.scores, layer="gold")
    headline = result.metrics[
        (result.metrics["split"] == "test") & (result.metrics["ablation"] == "all")
    ]
    summary = {
        **stamp,
        "rows": len(frame),
        "positives": int(frame["label_strict"].sum()),
        "headline": {
            f"{r['model']}:{r['metric']}": r["value"]
            for _, r in headline.iterrows()
            if r["metric"] in ("average_precision", "precision_top_1pct", "lift_top_1pct", "brier")
            and r["seed"] in (None, cfg.seeds[0])
        },
    }
    if register:
        registry = make_registry(settings.registry, names, local=not on_databricks(), actor=user)
        version = registry.register(run_id, tags={**tags, "run_id": run_id})
        registry.set_challenger(version)
        decision = registry.evaluate(version)
        write_events(spark, names, registry.events)
        summary["registry"] = {
            "model_name": registry.model_name,
            "version": version,
            "alias": settings.registry.challenger_alias,
            "promotion_rule": decision.summary(),
        }
    log.info("training done: %s", summary)
    return summary
