"""Tests that prove rules L1 to L7 on the landing zone.

privacy-scan: allow-person-fields
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from conftest import (
    DROPPED_UNITS,
    ENK_1,
    KEPT_UNITS,
    PERSON_MARKERS,
    SUB_ENK,
)
from foretaksrisiko.acquire.enheter import acquire_enheter
from foretaksrisiko.acquire.roller import acquire_roller
from foretaksrisiko.acquire.underenheter import acquire_underenheter

# Column names that would carry person-level data. Counts such as n_person_roleholders are fine.
FORBIDDEN_COLUMN_PARTS = (
    "fornavn",
    "etternavn",
    "fodselsdato",
    "foedselsdato",
    "er_doed",
    "erdoed",
)
FORBIDDEN_COLUMN_NAMES = {
    "navn",
    "person",
    "bostyrer",
    "adresse",
    "epostadresse",
    "telefon",
    "mobil",
}


def _run_all(enheter_opener, underenheter_opener, roller_opener, landing, scope) -> None:
    acquire_enheter(enheter_opener, landing, scope)
    acquire_underenheter(underenheter_opener, landing, set(KEPT_UNITS))
    acquire_roller(roller_opener, landing, set(KEPT_UNITS))


def _parquet_files(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.parquet"))
    assert files
    return files


def _all_string_cells(table: pa.Table) -> list[str]:
    cells: list[str] = []
    for column in table.itercolumns():
        if pa.types.is_string(column.type):
            cells.extend(v for v in column.to_pylist() if v is not None)
    return cells


def test_no_raw_or_unexpected_files_in_landing(
    enheter_opener, underenheter_opener, roller_opener, landing, scope
) -> None:
    _run_all(enheter_opener, underenheter_opener, roller_opener, landing, scope)
    for path in landing.root.rglob("*"):
        if path.is_file():
            assert path.suffix in {".parquet", ".json"}, path
            assert not path.name.endswith(".gz")


def test_no_person_columns_anywhere(
    enheter_opener, underenheter_opener, roller_opener, landing, scope
) -> None:
    _run_all(enheter_opener, underenheter_opener, roller_opener, landing, scope)
    for file in _parquet_files(landing.root):
        for name in pq.read_schema(file).names:
            assert name.lower() not in FORBIDDEN_COLUMN_NAMES, (file, name)
            assert not any(part in name.lower() for part in FORBIDDEN_COLUMN_PARTS), (file, name)


def test_no_person_values_anywhere(
    enheter_opener, underenheter_opener, roller_opener, landing, scope
) -> None:
    _run_all(enheter_opener, underenheter_opener, roller_opener, landing, scope)
    for file in _parquet_files(landing.root):
        for cell in _all_string_cells(pq.read_table(file)):
            for marker in PERSON_MARKERS:
                assert marker not in cell, (file, marker)
    manifest = landing.manifest_path.read_text(encoding="utf-8")
    for marker in PERSON_MARKERS:
        assert marker not in manifest


def test_dropped_units_never_appear(
    enheter_opener, underenheter_opener, roller_opener, landing, scope
) -> None:
    _run_all(enheter_opener, underenheter_opener, roller_opener, landing, scope)
    seen: set[str] = set()
    for file in _parquet_files(landing.root):
        seen.update(_all_string_cells(pq.read_table(file)))
    assert not (seen & DROPPED_UNITS), seen & DROPPED_UNITS
    assert ENK_1 not in seen and SUB_ENK not in seen
    manifest = landing.manifest_path.read_text(encoding="utf-8")
    for orgnr in DROPPED_UNITS | KEPT_UNITS:
        assert orgnr not in manifest


def test_logs_carry_counts_only(
    enheter_opener, underenheter_opener, roller_opener, landing, scope, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        _run_all(enheter_opener, underenheter_opener, roller_opener, landing, scope)
    text = caplog.text
    assert "rows_kept" in text
    for marker in PERSON_MARKERS:
        assert marker not in text
    for orgnr in DROPPED_UNITS | KEPT_UNITS:
        assert orgnr not in text
