"""Lakehouse tests that need no Spark.

privacy-scan: allow-dates
"""

from __future__ import annotations

import io
from pathlib import Path

import pyarrow as pa

from conftest import AS_1
from foretaksrisiko.acquire.landing import Landing
from foretaksrisiko.config import LakehouseConfig
from foretaksrisiko.lakehouse.bronze import snapshot_date_from_manifest
from foretaksrisiko.lakehouse.gold import ddl_from_arrow
from foretaksrisiko.lakehouse.session import Names
from foretaksrisiko.lakehouse.silver import resolve_mapping
from foretaksrisiko.lakehouse.upload import upload_snapshot
from foretaksrisiko.quality.checks import mod11_valid_sql


def test_names_local_and_databricks() -> None:
    cfg = LakehouseConfig()
    local = Names.from_config(cfg, local=True)
    remote = Names.from_config(cfg, local=False)
    assert local.table("bronze", "enheter") == "spark_catalog.foretaksrisiko_bronze.enheter"
    assert remote.schema("gold") == "workspace.foretaksrisiko_gold"
    assert (
        remote.snapshot_root(3) == "/Volumes/workspace/foretaksrisiko_landing/snapshots/snapshot=3"
    )


def test_resolve_mapping_prefers_shared_prefix_and_flags_ambiguity() -> None:
    pairs = [("69.209", "69.201"), ("69.209", "69.202"), ("62.010", "62.010"), ("10.1", "10.110")]
    rows = resolve_mapping(pairs)
    assert ("62.010", "62.010", 1, False) in rows
    assert ("69.209", "69.201", 2, True) in rows
    assert ("10.1", "10.110", 1, False) in rows
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)


def test_snapshot_date_prefers_bulk_file_time() -> None:
    manifest = {
        "enheter": {
            "source": {"last_modified_iso": "2026-11-03T03:28:15+00:00"},
            "updated_at": "2026-11-03T09:44:56+00:00",
        }
    }
    assert snapshot_date_from_manifest(manifest).isoformat() == "2026-11-03"
    assert (
        snapshot_date_from_manifest(
            {"enheter": {"updated_at": "2026-11-04T01:00:00+00:00"}}
        ).isoformat()
        == "2026-11-04"
    )


def test_ddl_from_arrow() -> None:
    schema = pa.schema(
        [("a", pa.string()), ("b", pa.int32()), ("c", pa.date32()), ("d", pa.float64())]
    )
    assert ddl_from_arrow(schema, "x INT") == "a STRING, b INT, c DATE, d DOUBLE, x INT"


def test_mod11_sql_mentions_all_weights() -> None:
    sql = mod11_valid_sql("organisasjonsnummer")
    for weight in (3, 2, 7, 6, 5, 4):
        assert f"* {weight}" in sql
    assert "substr(organisasjonsnummer, 9, 1)" in sql


class _FakeFiles:
    def __init__(self) -> None:
        self.uploaded: dict[str, int] = {}

    def upload(self, path: str, contents: io.BufferedReader, overwrite: bool = False) -> None:
        assert overwrite
        self.uploaded[path] = len(contents.read())


class _AlreadyExists:
    def __init__(self, label: str) -> None:
        self.label = label

    def create(self, **kwargs) -> None:
        raise RuntimeError(f"{self.label} already exists")


class _FakeClient:
    def __init__(self) -> None:
        self.files = _FakeFiles()
        self.schemas = _AlreadyExists("schema")
        self.volumes = _AlreadyExists("volume")


def test_upload_skips_excluded_tables_and_ledgers(tmp_path: Path, monkeypatch) -> None:
    import sys
    import types

    catalog_module = types.ModuleType("databricks.sdk.service.catalog")
    catalog_module.VolumeType = types.SimpleNamespace(MANAGED="MANAGED")
    sdk_module = types.ModuleType("databricks.sdk")
    service_module = types.ModuleType("databricks.sdk.service")
    monkeypatch.setitem(sys.modules, "databricks", types.ModuleType("databricks"))
    monkeypatch.setitem(sys.modules, "databricks.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "databricks.sdk.service", service_module)
    monkeypatch.setitem(sys.modules, "databricks.sdk.service.catalog", catalog_module)

    landing = Landing(tmp_path / "landing", 1)
    (landing.table_dir("enheter") / "part-00000.parquet").write_bytes(b"x" * 10)
    (landing.table_dir("enheter_tekst") / "part-00000.parquet").write_bytes(b"y" * 10)
    (landing.table_dir("regnskap") / "batch-00000.parquet").write_bytes(b"z" * 5)
    (landing.table_dir("regnskap") / "_fetched_orgnr.txt").write_text(AS_1, encoding="utf-8")
    landing.update_manifest("enheter", {"rows_kept": 1})

    client = _FakeClient()
    names = Names.from_config(LakehouseConfig(), local=False)
    summary = upload_snapshot(landing.root.parent, names, 1, ["enheter_tekst"], client=client)
    uploaded = set(client.files.uploaded)
    root = names.snapshot_root(1)
    assert uploaded == {
        f"{root}/enheter/part-00000.parquet",
        f"{root}/regnskap/batch-00000.parquet",
        f"{root}/manifest.json",
    }
    assert summary["uploaded_files"] == 3
    assert summary["skipped_files"] == 2
    assert summary["tables"] == ["enheter", "regnskap"]
