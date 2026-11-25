from conftest import AS_1, KEPT_UNITS, SUB_1, SUB_2
from foretaksrisiko.acquire.landing import read_table
from foretaksrisiko.acquire.underenheter import acquire_underenheter


def test_sub_units_follow_their_parent(underenheter_opener, landing) -> None:
    summary = acquire_underenheter(underenheter_opener, landing, set(KEPT_UNITS))
    rows = read_table(landing.root / "underenheter").to_pylist()
    assert {r["organisasjonsnummer"] for r in rows} == {SUB_1, SUB_2}
    assert all(r["overordnet_enhet"] == AS_1 for r in rows)
    assert {r["beliggenhetsadresse_kommunenummer"] for r in rows} == {"0301", "4601"}
    assert summary["rows_total"] == 3
    assert summary["rows_kept"] == 2
    assert summary["rows_dropped_parent_not_kept"] == 1
