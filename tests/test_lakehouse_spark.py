"""End-to-end lakehouse tests on synthetic snapshots. Need Java and the spark extra.

privacy-scan: allow-dates
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pyspark = pytest.importorskip("pyspark")
pytest.importorskip("delta")
if not shutil.which("java"):
    pytest.skip("java is not on PATH", allow_module_level=True)

from conftest import AS_1, AS_2, AS_AUDITOR, ASA_1  # noqa: E402
from foretaksrisiko.config import LakehouseConfig, QualityConfig, ScopeConfig  # noqa: E402
from foretaksrisiko.lakehouse.bronze import load_bronze, read_manifest  # noqa: E402
from foretaksrisiko.lakehouse.gold import build_company_snapshot  # noqa: E402
from foretaksrisiko.lakehouse.session import Names, get_spark  # noqa: E402
from foretaksrisiko.lakehouse.silver import (  # noqa: E402
    build_history,
    build_reference_tables,
    build_silver_enheter,
    build_silver_pass_through,
)
from foretaksrisiko.quality.checks import Checker, QualityError, run_layer_checks  # noqa: E402
from synthetic_landing import AS_3, build_landing  # noqa: E402

pytestmark = pytest.mark.spark

CFG = LakehouseConfig()
QCFG = QualityConfig(
    mod11_severity="warn",
    min_nace_section_share=0.5,
    min_fylke_coverage=0.5,
    min_kommune_coverage=0.5,
)


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    warehouse = tmp_path_factory.mktemp("warehouse")
    session = get_spark(CFG, warehouse_dir=warehouse, app_name="foretaksrisiko-tests")
    yield session
    session.stop()


@pytest.fixture(scope="module")
def names() -> Names:
    return Names.from_config(CFG, local=True)


@pytest.fixture(scope="module")
def landing_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("landing")
    build_landing(root, 1, "2026-11-03T03:28:15+00:00", variant=1)
    build_landing(root, 2, "2026-11-10T03:28:15+00:00", variant=2)
    return root


def _run_snapshot(spark, names, landing_dir: Path, snapshot_id: int) -> None:
    root = str(landing_dir / f"snapshot={snapshot_id}")
    load_bronze(spark, names, root, snapshot_id, CFG.bronze_tables, CFG.klass_tables)
    run_layer_checks(spark, names, snapshot_id, "bronze", QCFG, ScopeConfig(), read_manifest(root))
    build_reference_tables(spark, names, snapshot_id)
    build_silver_enheter(spark, names, snapshot_id)
    build_silver_pass_through(spark, names, snapshot_id)
    build_history(spark, names, snapshot_id)
    run_layer_checks(spark, names, snapshot_id, "silver", QCFG)
    build_company_snapshot(spark, names, snapshot_id)
    run_layer_checks(spark, names, snapshot_id, "gold", QCFG)


def _rows(spark, name: str, where: str = "1 = 1") -> dict[str, dict]:
    return {
        r["organisasjonsnummer"]: r.asDict()
        for r in spark.sql(f"SELECT * FROM {name} WHERE {where}").collect()
    }


def test_snapshot_one_end_to_end(spark, names, landing_dir) -> None:
    _run_snapshot(spark, names, landing_dir, 1)
    bronze = _rows(spark, names.table("bronze", "enheter"), "snapshot_id = 1")
    assert set(bronze) == {AS_1, AS_2, ASA_1, AS_AUDITOR}
    assert bronze[AS_1]["snapshot_date"].isoformat() == "2026-11-03"
    registry = spark.table(names.table("bronze", "snapshots")).collect()
    assert [r["snapshot_id"] for r in registry] == [1]

    silver = _rows(spark, names.table("silver", "enheter"), "snapshot_id = 1")
    assert silver[AS_1]["nace_section"] == "J" and silver[AS_1]["nace_division"] == "62"
    assert silver[AS_1]["nace_standard"] == "SN2025" and silver[AS_1]["nace_sn2007"] == "62.010"
    assert silver[AS_2]["nace_section"] == "F" and silver[AS_2]["fylke_name"] == "Vestland"
    assert silver[AS_1]["fylke_code"] == "03" and silver[AS_1]["kommune_name"] == "Oslo"
    assert 11 < silver[AS_1]["company_age_years"] < 12
    history = spark.table(names.table("silver", "enheter_history")).collect()
    assert len(history) == 4 and all(r["is_current"] for r in history)

    gold = _rows(spark, names.table("gold", "company_snapshot"), "snapshot_id = 1")
    assert len(gold) == 4
    g1 = gold[AS_1]
    assert g1["n_sub_units"] == 2 and g1["n_sub_unit_municipalities"] == 2
    assert g1["board_size"] == 2 and g1["ceo_is_chair"] is True
    assert g1["auditor_orgnr"] == AS_AUDITOR and g1["auditor_portfolio_size"] == 1
    assert g1["has_accounts"] is True and g1["acc_fiscal_year"] == 2025
    assert g1["acc_sum_driftsinntekter"] == 1300.0 and g1["acc_prev_sum_driftsinntekter"] == 1200.0
    assert g1["n_accounts_years"] == 3 and g1["has_konsern_regnskap"] is True
    assert g1["in_dev_sample"] is True
    assert gold[AS_2]["has_accounts"] is False and gold[AS_2]["acc_sum_driftsinntekter"] is None
    assert gold[ASA_1]["n_sub_units"] == 0 and gold[ASA_1]["in_dev_sample"] is False

    # Status files with and without the source snapshot field load together; older rows get this
    # snapshot as their source, and a final answer wins over a failed request.
    status = spark.table(names.table("bronze", "regnskap_status")).where("snapshot_id = 1")
    assert status.count() == 4
    assert {r["source_snapshot_id"] for r in status.collect()} == {1}
    silver_status = _rows(spark, names.table("silver", "regnskap_status"), "snapshot_id = 1")
    assert {o: r["http_status"] for o, r in silver_status.items()} == {
        AS_1: 200,
        AS_2: 404,
        AS_AUDITOR: 200,
    }

    # A statement that starts and ends on the same day is one day long and passes the period check.
    periods = spark.table(names.table("silver", "regnskap")).where(
        f"snapshot_id = 1 AND organisasjonsnummer = '{AS_AUDITOR}'"
    )
    assert sorted(r["period_days"] for r in periods.collect()) == [1, 366]

    results = spark.table(names.table("monitoring", "quality_results"))
    assert results.where("snapshot_id = 1 AND severity = 'error' AND NOT passed").count() == 0
    assert results.where("check = 'period_end_not_before_start' AND passed").count() > 0
    assert results.where("layer = 'bronze'").count() > 0


def test_snapshot_two_updates_history_and_is_idempotent(spark, names, landing_dir) -> None:
    _run_snapshot(spark, names, landing_dir, 2)
    history = names.table("silver", "enheter_history")
    as1 = spark.sql(
        f"SELECT * FROM {history} WHERE organisasjonsnummer = '{AS_1}' ORDER BY valid_from_snapshot"
    ).collect()
    assert [r["valid_from_snapshot"] for r in as1] == [1, 2]
    assert as1[0]["valid_to_snapshot"] == 2 and as1[0]["is_current"] is False
    assert as1[0]["valid_to_date"].isoformat() == "2026-11-10"
    assert as1[1]["is_current"] is True and as1[1]["forretningsadresse_kommunenummer"] == "4601"
    asa = spark.sql(f"SELECT * FROM {history} WHERE organisasjonsnummer = '{ASA_1}'").collect()
    assert len(asa) == 1 and asa[0]["valid_to_snapshot"] == 2 and asa[0]["is_current"] is False
    new = spark.sql(f"SELECT * FROM {history} WHERE organisasjonsnummer = '{AS_3}'").collect()
    assert len(new) == 1 and new[0]["valid_from_snapshot"] == 2 and new[0]["is_current"] is True
    assert spark.sql(f"SELECT count(*) FROM {history} WHERE is_current").first()[0] == 4

    silver_new = _rows(spark, names.table("silver", "enheter"), "snapshot_id = 2")[AS_3]
    assert silver_new["nace_standard"] == "SN2007"
    assert silver_new["nace_sn2025"] == "69.201" and silver_new["nace_mapping_ambiguous"] is True
    assert silver_new["nace_section"] == "M"

    before = spark.table(history).count()
    _run_snapshot(spark, names, landing_dir, 2)
    assert spark.table(history).count() == before
    assert spark.table(names.table("bronze", "enheter")).where("snapshot_id = 2").count() == 4
    assert (
        spark.table(names.table("gold", "company_snapshot")).where("snapshot_id = 1").count() == 4
    )


def test_failing_error_check_raises_and_is_recorded(spark, names) -> None:
    checker = Checker(spark, names, 1, "bronze")
    spark.createDataFrame(
        [(AS_1, 1), (AS_1, 1)], "organisasjonsnummer STRING, snapshot_id INT"
    ).createOrReplaceTempView("dup")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {names.schema('bronze')}")
    spark.sql(
        f"CREATE OR REPLACE TABLE {names.table('bronze', 'dup_probe')} USING DELTA "
        "AS SELECT * FROM dup"
    )
    checker.unique("dup_probe", ["organisasjonsnummer"])
    checker.write()
    with pytest.raises(QualityError):
        checker.raise_if_failed()
    recorded = (
        spark.table(names.table("monitoring", "quality_results"))
        .where("table = 'dup_probe'")
        .collect()
    )
    assert len(recorded) == 1 and recorded[0]["passed"] is False and recorded[0]["observed"] == 1.0
