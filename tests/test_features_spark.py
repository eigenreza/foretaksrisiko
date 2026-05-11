"""Outcomes, labels and features on the synthetic snapshots. Need Java and the spark extra.

privacy-scan: allow-dates
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

pyspark = pytest.importorskip("pyspark")
pytest.importorskip("delta")
if not shutil.which("java"):
    pytest.skip("java is not on PATH", allow_module_level=True)

from conftest import AS_1, AS_2, AS_AUDITOR, ASA_1  # noqa: E402
from foretaksrisiko.config import (  # noqa: E402
    DesignConfig,
    LakehouseConfig,
    QualityConfig,
    ScopeConfig,
)
from foretaksrisiko.lakehouse.bronze import load_bronze, read_manifest  # noqa: E402
from foretaksrisiko.lakehouse.features import build_features  # noqa: E402
from foretaksrisiko.lakehouse.gold import build_company_snapshot  # noqa: E402
from foretaksrisiko.lakehouse.labels import add_months, build_labels, reference_date  # noqa: E402
from foretaksrisiko.lakehouse.outcomes import build_outcomes  # noqa: E402
from foretaksrisiko.lakehouse.session import Names, get_spark  # noqa: E402
from foretaksrisiko.lakehouse.silver import (  # noqa: E402
    build_history,
    build_reference_tables,
    build_silver_enheter,
    build_silver_pass_through,
)
from foretaksrisiko.quality.checks import run_layer_checks  # noqa: E402
from synthetic_landing import build_landing  # noqa: E402

pytestmark = pytest.mark.spark

CFG = LakehouseConfig()
QCFG = QualityConfig(
    mod11_severity="warn",
    min_nace_section_share=0.5,
    min_fylke_coverage=0.5,
    min_kommune_coverage=0.5,
)
DCFG = DesignConfig(peer_min_size=20)


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    session = get_spark(
        CFG, warehouse_dir=tmp_path_factory.mktemp("warehouse"), app_name="foretaksrisiko-features"
    )
    yield session
    session.stop()


@pytest.fixture(scope="module")
def names() -> Names:
    return Names.from_config(CFG, local=True)


@pytest.fixture(scope="module")
def prepared(spark, names, tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("landing")
    build_landing(root, 1, "2026-11-03T03:28:15+00:00", variant=1)
    landing_root = str(root / "snapshot=1")
    load_bronze(spark, names, landing_root, 1, CFG.bronze_tables, CFG.klass_tables)
    run_layer_checks(spark, names, 1, "bronze", QCFG, ScopeConfig(), read_manifest(landing_root))
    build_reference_tables(spark, names, 1)
    build_silver_enheter(spark, names, 1)
    build_silver_pass_through(spark, names, 1)
    build_history(spark, names, 1)
    build_company_snapshot(spark, names, 1)
    build_outcomes(spark, names)
    build_labels(spark, names, DCFG)
    for design in ("retro", "prospective"):
        build_features(spark, names, DCFG, 1, design)
    return root


def _rows(spark, name: str, where: str) -> dict[str, dict]:
    frame = spark.sql(f"SELECT * FROM {name} WHERE {where}")
    return {r["organisasjonsnummer"]: r.asDict() for r in frame.collect()}


def test_reference_dates() -> None:
    assert reference_date("retro", date(2026, 11, 3), DCFG) == date(2026, 5, 1)
    assert reference_date("prospective", date(2026, 11, 3), DCFG) == date(2026, 11, 3)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 5, 1), -12) == date(2025, 5, 1)


def test_outcomes_merge_register_and_events(spark, names, prepared) -> None:
    out = _rows(spark, names.table("gold", "outcomes"), "1 = 1")
    assert out[AS_2]["first_bankruptcy_date"].isoformat() == "2024-11-20"
    assert out[AS_AUDITOR]["first_bankruptcy_date"].isoformat() == "2026-07-15"
    assert out[AS_1]["first_bankruptcy_date"] is None and out[AS_1]["deletion_date"] is None
    assert all(r["in_population"] for r in out.values())


def test_labels_for_both_designs(spark, names, prepared) -> None:
    retro = _rows(spark, names.table("gold", "labels"), "design = 'retro'")
    assert retro[AS_AUDITOR]["eligible"] is True and retro[AS_AUDITOR]["label_strict"] is True
    assert retro[AS_AUDITOR]["outcome_bankruptcy_date"].isoformat() == "2026-07-15"
    assert retro[AS_2]["eligible"] is False and retro[AS_2]["label_strict"] is False
    assert retro[AS_1]["eligible"] is True and retro[AS_1]["label_strict"] is False
    assert retro[AS_1]["reference_date"].isoformat() == "2026-05-01"
    assert retro[AS_1]["window_end"].isoformat() == "2026-11-01"
    assert retro[AS_1]["fully_observed"] is True
    prospective = _rows(spark, names.table("gold", "labels"), "design = 'prospective'")
    assert prospective[AS_1]["reference_date"].isoformat() == "2026-11-03"
    assert prospective[AS_1]["fully_observed"] is False
    assert not any(r["label_strict"] for r in prospective.values())
    # The auditor firm went bankrupt before the snapshot date, so it is not eligible prospectively.
    assert sum(r["eligible"] for r in prospective.values()) == 2
    assert prospective[AS_AUDITOR]["eligible"] is False


def test_features_are_known_at_reference_time(spark, names, prepared) -> None:
    features = names.table("gold", "features")
    retro = _rows(spark, features, "design = 'retro' AND reference_snapshot_id = 1")
    pro = _rows(spark, features, "design = 'prospective' AND reference_snapshot_id = 1")
    assert len(retro) == 4 and len(pro) == 4
    a1 = retro[AS_1]
    assert a1["masked_kapital"] is True and a1["kapital_belop"] is None
    assert pro[AS_1]["masked_kapital"] is False and pro[AS_1]["kapital_belop"] == 30000.0
    assert a1["n_address_changes_12m"] == 1 and a1["n_changes_12m"] == 1
    assert a1["n_role_events_6m"] == 2 and a1["n_role_events_12m"] == 2
    assert a1["acc_fiscal_year"] == 2024 and a1["acc_prev_fiscal_year"] == 2023
    assert a1["acc_n_statements_known"] == 2
    assert pro[AS_1]["acc_fiscal_year"] == 2025 and pro[AS_1]["acc_filing_lag_days"] == 161
    assert a1["acc_filing_lag_days"] is None
    assert a1["has_accounts"] is True and retro[AS_2]["has_accounts"] is False
    assert a1["equity_ratio"] == pytest.approx(0.4)
    assert a1["revenue_growth"] == pytest.approx(300 / 900)
    assert a1["text_sim_own_code"] == pytest.approx(0.4) and a1["text_rank_own_code"] == 3
    assert retro[AS_2]["text_chars"] == 0 and retro[ASA_1]["text_chars"] is None
    assert a1["auditor_portfolio_size"] == 1
    assert a1["auditor_other_clients_adverse_share"] is None
    assert a1["board_size"] == 2 and a1["masked_board"] is False
    assert retro[ASA_1]["masked_board"] is True and retro[ASA_1]["board_size"] is None
    assert pro[ASA_1]["masked_board"] is False and pro[ASA_1]["board_size"] == 3
    assert a1["n_sub_units"] == 2 and retro[AS_AUDITOR]["n_sub_units"] == 0
    assert a1["peer_group"].startswith("all:") and a1["size_band"] != "0"
    assert retro[AS_2]["size_band"] == "0"
    assert all(r["n_extreme_z"] == 0 for r in retro.values())
    assert a1["age_years"] == pytest.approx(11.25, abs=0.05)
    stats = spark.table(names.table("gold", "peer_stats")).where("design = 'retro'")
    features_seen = {r["feature"] for r in stats.select("feature").distinct().collect()}
    assert stats.count() > 0 and "equity_ratio" in features_seen
