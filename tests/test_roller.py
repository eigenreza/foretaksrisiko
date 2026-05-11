"""privacy-scan: allow-dates"""

from datetime import date

from conftest import AS_1, AS_AUDITOR, ASA_1, ENK_1, KEPT_UNITS, roller_records
from foretaksrisiko.acquire.landing import read_table
from foretaksrisiko.acquire.roller import (
    ROLLER_COUNTS_SCHEMA,
    ROLLER_LINKS_SCHEMA,
    acquire_roller,
    reduce_roles,
)


def _entry(orgnr: str) -> dict:
    return next(e for e in roller_records() if e["organisasjonsnummer"] == orgnr)


def test_reduce_counts_and_flags_for_company_with_ceo_as_chair() -> None:
    row, links = reduce_roles(_entry(AS_1), set(KEPT_UNITS))
    assert row["organisasjonsnummer"] == AS_1
    assert row["n_role_groups"] == 4
    assert row["n_roles_total"] == 7
    assert row["n_roles_active"] == 6
    assert row["n_deregistered_roles"] == 1
    assert row["board_size"] == 2
    assert row["n_board_chair"] == 1
    assert row["n_board_members"] == 1
    assert row["n_deputy_members"] == 1
    assert row["has_ceo"] is True and row["n_ceo"] == 1
    assert row["has_chair"] is True
    assert row["ceo_is_chair"] is True
    assert row["n_person_roleholders"] == 4
    assert row["n_distinct_persons"] == 3
    assert row["n_deceased_roleholders"] == 0
    assert row["has_auditor"] is True and row["has_accountant"] is True
    assert row["n_org_roleholders"] == 2
    assert row["n_org_roleholders_in_scope"] == 1
    assert row["styr_sist_endret"] == date(2024, 6, 1)
    assert row["dagl_sist_endret"] == date(2023, 1, 1)
    assert row["kont_sist_endret"] is None
    assert len(links) == 1
    link = links[0]
    assert link["rolleholder_organisasjonsnummer"] == AS_AUDITOR
    assert link["rollegruppe"] == "REVI" and link["rolletype"] == "REVI"
    assert link["godkjenningsstatus"] == "GODKJENT"


def test_reduce_company_with_separate_ceo() -> None:
    row, links = reduce_roles(_entry(ASA_1), set(KEPT_UNITS))
    assert row["board_size"] == 3
    assert row["n_board_deputy_chair"] == 1
    assert row["ceo_is_chair"] is False
    assert row["has_contact_person"] is True
    assert row["n_roles_valgt_av"] == 1
    assert row["n_deceased_roleholders"] == 1
    assert row["n_distinct_persons"] == 3
    assert links == []


def test_row_schema_has_no_person_fields() -> None:
    row, _ = reduce_roles(_entry(AS_1), set(KEPT_UNITS))
    assert set(row) == set(ROLLER_COUNTS_SCHEMA.names)
    for value in row.values():
        assert not isinstance(value, (dict, list))


def test_stream_skips_units_outside_scope(roller_opener, landing) -> None:
    summary = acquire_roller(roller_opener, landing, set(KEPT_UNITS))
    counts = read_table(landing.root / "roller_counts")
    links = read_table(landing.root / "roller_links")
    assert counts.schema.equals(ROLLER_COUNTS_SCHEMA)
    assert links.schema.equals(ROLLER_LINKS_SCHEMA)
    assert set(counts.column("organisasjonsnummer").to_pylist()) == {AS_1, ASA_1}
    assert ENK_1 not in counts.column("organisasjonsnummer").to_pylist()
    assert summary == {
        "entries_total": 3,
        "entries_kept": 2,
        "entries_skipped": 1,
        "links": 1,
        "files": 1,
        "raw_file_written_to_disk": False,
    }
