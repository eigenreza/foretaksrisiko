from __future__ import annotations

from conftest import fake_orgnr
from foretaksrisiko.acquire.sampling import (
    UNKNOWN,
    allocate,
    build_section_lookup,
    county_of,
    stratified_sample,
)

SN_ITEMS = [
    {"code": "J", "parent_code": None, "level": 1, "name": "Informasjon"},
    {"code": "62", "parent_code": "J", "level": 2, "name": "IT"},
    {"code": "62.0", "parent_code": "62", "level": 3, "name": "IT"},
    {"code": "62.01", "parent_code": "62.0", "level": 4, "name": "Programmering"},
    {"code": "62.010", "parent_code": "62.01", "level": 5, "name": "Programmering"},
    {"code": "F", "parent_code": None, "level": 1, "name": "Bygg"},
    {"code": "41", "parent_code": "F", "level": 2, "name": "Bygg"},
]


def test_section_lookup_climbs_parents_and_falls_back_to_prefix() -> None:
    section = build_section_lookup(SN_ITEMS)
    assert section("62.010") == "J"
    assert section("62.019") == "J"
    assert section("41.200") == "F"
    assert section("99.999") == UNKNOWN
    assert section(None) == UNKNOWN


def test_county_of() -> None:
    assert county_of("0301") == "03"
    assert county_of("4601") == "46"
    assert county_of(None) == "99"
    assert county_of("12") == "99"


def test_allocate_is_proportional_and_sums_to_total() -> None:
    sizes = {("J", "03"): 700, ("F", "46"): 200, ("X", "99"): 100}
    allocation = allocate(sizes, 100)
    assert sum(allocation.values()) == 100
    assert allocation[("J", "03")] == 70
    assert allocation[("F", "46")] == 20
    capped = allocate(sizes, 5000)
    assert capped == sizes


def test_stratified_sample_is_deterministic() -> None:
    units = [(fake_orgnr(i), "J" if i % 3 else "F", "03" if i % 2 else "46") for i in range(60)]
    first = stratified_sample(units, 20, seed=42)
    second = stratified_sample(units, 20, seed=42)
    other = stratified_sample(units, 20, seed=43)
    assert first == second
    assert first != other
    assert len(first) == 20
    assert len({r["organisasjonsnummer"] for r in first}) == 20
    sections = {r["stratum_section"] for r in first}
    assert sections == {"J", "F"}


def test_copy_sample_keeps_only_companies_still_in_population(tmp_path) -> None:
    from conftest import AS_1, AS_2, ASA_1
    from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter, read_table
    from foretaksrisiko.acquire.sampling import SAMPLE_SCHEMA, copy_sample

    first, second = Landing(tmp_path, 1), Landing(tmp_path, 2)
    with ParquetBatchWriter(first.table_dir("sample"), SAMPLE_SCHEMA) as writer:
        for orgnr in (AS_1, AS_2):
            writer.write(
                {"organisasjonsnummer": orgnr, "stratum_section": "J", "stratum_county": "03"}
            )
    summary = copy_sample(second, first, {AS_1, ASA_1})
    assert summary["sample_size"] == 1 and summary["left_population"] == 1
    copied = read_table(second.root / "sample").to_pylist()
    assert [r["organisasjonsnummer"] for r in copied] == [AS_1]
    assert second.read_manifest()["sample"]["copied_from_snapshot_id"] == 1
