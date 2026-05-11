from __future__ import annotations

import pytest

from conftest import AS_1, AS_2, KEPT_UNITS
from foretaksrisiko.acquire.enheter import acquire_enheter
from foretaksrisiko.acquire.landing import ParquetBatchWriter, read_table
from foretaksrisiko.features.text import code_descriptions, normalise

ITEMS = [
    {"code": "J", "parent_code": None, "level": 1, "name": "Informasjon"},
    {"code": "62", "parent_code": "J", "level": 2, "name": "IT-tjenester"},
    {"code": "62.0", "parent_code": "62", "level": 3, "name": "IT-tjenester"},
    {"code": "62.01", "parent_code": "62.0", "level": 4, "name": "Programmering"},
    {"code": "62.010", "parent_code": "62.01", "level": 5, "name": "Programmeringstjenester"},
    {"code": "F", "parent_code": None, "level": 1, "name": "Bygg og anlegg"},
    {"code": "41", "parent_code": "F", "level": 2, "name": "Oppfoering av bygninger"},
    {"code": "41.2", "parent_code": "41", "level": 3, "name": "Oppfoering av bygninger"},
    {"code": "41.20", "parent_code": "41.2", "level": 4, "name": "Oppfoering av bygninger"},
    {"code": "41.200", "parent_code": "41.20", "level": 5, "name": "Oppfoering av bygninger"},
    {"code": "64.190", "parent_code": None, "level": 5, "name": "Bankvirksomhet ellers"},
    {"code": "69.201", "parent_code": None, "level": 5, "name": "Revisjon"},
]


def test_code_descriptions_include_ancestors() -> None:
    desc = code_descriptions(ITEMS)
    assert set(desc) == {"62.010", "41.200", "64.190", "69.201"}
    expected = "programmeringstjenester programmering it-tjenester it-tjenester informasjon"
    assert desc["62.010"] == expected
    assert normalise("  Flere   ord\nHER ") == "flere ord her"


def test_text_features_written_without_text(enheter_opener, landing, scope) -> None:
    pytest.importorskip("sklearn")
    from foretaksrisiko.acquire.klass import KLASS_ITEM_SCHEMA
    from foretaksrisiko.features.text import TEXT_FEATURES_SCHEMA, build_text_features

    acquire_enheter(enheter_opener, landing, scope)
    with ParquetBatchWriter(landing.table_dir("klass/sn2025"), KLASS_ITEM_SCHEMA) as writer:
        for item in ITEMS:
            writer.write({**item, "short_name": None, "notes": None})
    summary = build_text_features(landing, chunk_size=2)
    assert summary["companies"] == len(KEPT_UNITS)
    assert summary["with_text"] == len(KEPT_UNITS)
    table = read_table(landing.root / "text_features")
    assert table.schema.equals(TEXT_FEATURES_SCHEMA)
    rows = {r["organisasjonsnummer"]: r for r in table.to_pylist()}
    programming = rows[AS_1]
    assert programming["text_chars"] > 0 and 0 < programming["text_sim_own_code"] <= 1
    assert programming["text_rank_own_code"] == 1
    assert programming["text_sim_section"] is not None
    building = rows[AS_2]
    assert building["text_rank_own_code"] >= 1
    for column in table.column_names:
        assert "tekst" not in column and "navn" not in column
