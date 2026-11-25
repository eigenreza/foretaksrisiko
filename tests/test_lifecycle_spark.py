"""Scoring with a registered champion and monitoring across two synthetic snapshots.

Needs Java and the spark extra. The champion is a stub model registered in a local MLflow
registry, so the test exercises the alias lookup, the scoring and monitoring stages and the
alert stage without any trained model.

privacy-scan: allow-dates
"""

from __future__ import annotations

import shutil

import numpy as np
import pandas as pd
import pytest

pyspark = pytest.importorskip("pyspark")
pytest.importorskip("delta")
mlflow = pytest.importorskip("mlflow")
if not shutil.which("java"):
    pytest.skip("java is not on PATH", allow_module_level=True)

from foretaksrisiko.config import (  # noqa: E402
    DesignConfig,
    LakehouseConfig,
    MonitoringConfig,
    QualityConfig,
    RegistryConfig,
    ScopeConfig,
    Settings,
)
from foretaksrisiko.lakehouse.bronze import load_bronze, read_manifest  # noqa: E402
from foretaksrisiko.lakehouse.features import build_features  # noqa: E402
from foretaksrisiko.lakehouse.gold import build_company_snapshot  # noqa: E402
from foretaksrisiko.lakehouse.labels import build_labels  # noqa: E402
from foretaksrisiko.lakehouse.outcomes import build_outcomes  # noqa: E402
from foretaksrisiko.lakehouse.session import Names, get_spark  # noqa: E402
from foretaksrisiko.lakehouse.silver import (  # noqa: E402
    build_history,
    build_reference_tables,
    build_silver_enheter,
    build_silver_pass_through,
)
from foretaksrisiko.models.lakehouse_score import score_with_champion  # noqa: E402
from foretaksrisiko.monitoring.alerts import AlertBreach  # noqa: E402
from foretaksrisiko.monitoring.lakehouse_monitor import check_alerts, monitor_snapshot  # noqa: E402
from foretaksrisiko.quality.checks import run_layer_checks  # noqa: E402
from foretaksrisiko.registry.client import Registry, write_events  # noqa: E402
from synthetic_landing import build_landing  # noqa: E402

pytestmark = pytest.mark.spark

CFG = LakehouseConfig()
QCFG = QualityConfig(
    mod11_severity="warn",
    min_nace_section_share=0.5,
    min_fylke_coverage=0.5,
    min_kommune_coverage=0.5,
)
SETTINGS = Settings(
    lakehouse=CFG,
    quality=QCFG,
    design=DesignConfig(peer_min_size=20),
    monitoring=MonitoringConfig(
        min_rows=1,
        scenarios={
            "simulated_breach": {
                "psi_warn": 0.0001,
                "psi_alert": 0.0005,
                "category_share_delta_warn": 0.0001,
                "category_share_delta_alert": 0.0005,
                "score_psi_warn": 0.0001,
                "score_psi_alert": 0.0005,
                "min_rows": 1,
            }
        },
    ),
)


class StubModel(mlflow.pyfunc.PythonModel):
    """Deterministic scores from one feature, standing in for the trained model."""

    def predict(self, context, model_input: pd.DataFrame, params=None):
        age = pd.to_numeric(model_input["age_years"], errors="coerce").fillna(0.0).to_numpy()
        return 1.0 / (1.0 + np.exp(0.2 * age - 1.0))


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    session = get_spark(
        CFG, warehouse_dir=tmp_path_factory.mktemp("warehouse"), app_name="foretaksrisiko-lifecycle"
    )
    yield session
    session.stop()


@pytest.fixture(scope="module")
def names() -> Names:
    return Names.from_config(CFG, local=True)


@pytest.fixture(scope="module")
def lakehouse(spark, names, tmp_path_factory) -> None:
    root = tmp_path_factory.mktemp("landing")
    build_landing(root, 1, "2026-11-03T03:28:15+00:00", variant=1)
    build_landing(root, 2, "2026-11-10T03:28:15+00:00", variant=2)
    for snapshot_id in (1, 2):
        landing_root = str(root / f"snapshot={snapshot_id}")
        load_bronze(spark, names, landing_root, snapshot_id, CFG.bronze_tables, CFG.klass_tables)
        run_layer_checks(
            spark, names, snapshot_id, "bronze", QCFG, ScopeConfig(), read_manifest(landing_root)
        )
        build_reference_tables(spark, names, snapshot_id)
        build_silver_enheter(spark, names, snapshot_id)
        build_silver_pass_through(spark, names, snapshot_id)
        build_history(spark, names, snapshot_id)
        build_company_snapshot(spark, names, snapshot_id)
    build_outcomes(spark, names)
    build_labels(spark, names, SETTINGS.design)
    for snapshot_id in (1, 2):
        build_features(spark, names, SETTINGS.design, snapshot_id, "prospective")


@pytest.fixture(scope="module")
def registry(tmp_path_factory) -> Registry:
    uri = f"sqlite:///{(tmp_path_factory.mktemp('mlflow') / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    mlflow.set_experiment("test-lifecycle")
    cfg = RegistryConfig(model_name="lifecycle_stub")
    with mlflow.start_run(run_name="stub") as run:
        mlflow.pyfunc.log_model(artifact_path=cfg.artifact_path, python_model=StubModel())
        mlflow.log_metric("valid__hgb_calibrated__average_precision", 0.5)
    registry = Registry(cfg.model_name, cfg, actor="tests")
    return registry, run.info.run_id


def test_without_champion_scoring_is_skipped_and_monitoring_warns(
    spark, names, lakehouse, registry
) -> None:
    reg, _ = registry
    summary = score_with_champion(spark, names, SETTINGS, reg, 2)
    assert summary["status"] == "no_champion"
    monitored = monitor_snapshot(spark, names, SETTINGS, reg, 2)
    assert monitored["status"] == "monitored" and monitored["reference_snapshot_id"] == 1
    alerts = spark.table(names.table("monitoring", "alerts")).where("snapshot_id = 2").toPandas()
    assert "no_champion" in set(alerts["alert_type"])
    assert monitored["alerts_alert"] == int((alerts["severity"] == "alert").sum())


def test_champion_scores_both_snapshots_and_monitoring_compares_them(
    spark, names, lakehouse, registry
) -> None:
    reg, run_id = registry
    version = reg.register(run_id, tags={"snapshot_id": "1", "design": "retro"})
    reg.set_challenger(version)
    reg.client.set_registered_model_alias(reg.model_name, "champion", version)
    assert write_events(spark, names, reg.events) == 2
    events = spark.table(names.table("monitoring", "registry_events")).toPandas()
    assert list(events["event"]) == ["registered", "challenger_set"]

    summary = score_with_champion(spark, names, SETTINGS, reg, 2)
    assert summary["status"] == "scored" and summary["training_snapshot_id"] == 1
    assert [s["snapshot_id"] for s in summary["scored"]] == [1, 2]
    scores = spark.table(names.table("gold", "champion_scores")).toPandas()
    assert set(scores["snapshot_id"]) == {1, 2} and (scores["model_version"] == version).all()
    assert scores["score"].between(0, 1).all()
    assert len(scores) == len(
        spark.table(names.table("gold", "features")).where("design = 'prospective'").toPandas()
    )
    again = score_with_champion(spark, names, SETTINGS, reg, 2)
    assert [s["snapshot_id"] for s in again["scored"]] == [2]
    assert spark.table(names.table("gold", "champion_scores")).count() == len(scores)

    monitored = monitor_snapshot(spark, names, SETTINGS, reg, 2)
    assert monitored["status"] == "monitored" and monitored["model_version"] == version
    assert monitored["champion_age_snapshots"] == 1 and monitored["features_monitored"] > 20
    drift = spark.table(names.table("monitoring", "drift")).where("snapshot_id = 2").toPandas()
    assert (drift["scenario"] == "default").all()
    assert {"numeric", "categorical", "prediction"} <= set(drift["kind"])
    assert set(drift[drift["kind"] == "prediction"]["metric"]) >= {"psi", "flag_share", "p99"}
    summaries = spark.table(names.table("monitoring", "score_summary")).toPandas()
    assert sorted(summaries["side"]) == ["current", "reference"]
    assert (summaries["model_version"] == version).all()
    alerts = spark.table(names.table("monitoring", "alerts")).where("snapshot_id = 2").toPandas()
    assert "no_champion" not in set(alerts["alert_type"])


def test_simulated_breach_writes_alerts_and_fails_the_alert_stage(
    spark, names, lakehouse, registry
) -> None:
    reg, _ = registry
    monitored = monitor_snapshot(spark, names, SETTINGS, reg, 2, scenario="simulated_breach")
    assert monitored["alerts_alert"] > 0
    alerts = spark.table(names.table("monitoring", "alerts")).toPandas()
    breach = alerts[alerts["scenario"] == "simulated_breach"]
    assert (breach["severity"] == "alert").any()
    assert breach["alert_type"].str.startswith("data_drift:").any()
    assert (alerts[alerts["scenario"] == "default"]["snapshot_id"] == 2).all()
    with pytest.raises(AlertBreach, match="simulated_breach"):
        check_alerts(spark, names, 2, "simulated_breach")
    rerun = monitor_snapshot(spark, names, SETTINGS, reg, 2, scenario="simulated_breach")
    assert rerun["alerts_alert"] == monitored["alerts_alert"]
    rows = spark.table(names.table("monitoring", "alerts")).where("scenario = 'simulated_breach'")
    assert rows.count() == monitored["alerts_alert"] + monitored["alerts_warn"]
