"""privacy-scan: allow-dates"""

from datetime import date

from conftest import AS_1, AS_2, AS_AUDITOR, ASA_1, KEPT_UNITS
from foretaksrisiko.acquire.enheter import ENHET_SCHEMA, acquire_enheter
from foretaksrisiko.acquire.landing import read_table


def test_only_as_and_asa_are_kept(enheter_opener, landing, scope) -> None:
    summary = acquire_enheter(enheter_opener, landing, scope, rows_per_file=2)
    table = read_table(landing.root / "enheter")
    assert set(table.column("organisasjonsnummer").to_pylist()) == KEPT_UNITS
    assert table.schema.equals(ENHET_SCHEMA)
    assert summary["rows_total"] == 8
    assert summary["rows_kept"] == 4
    assert summary["rows_dropped_form"] == 2
    assert summary["rows_dropped_frivillighetsregisteret"] == 1
    assert summary["rows_dropped_deleted"] == 1
    assert summary["dropped_by_form"] == {"ENK": 1, "FLI": 1}
    assert summary["files"] == 2


def test_projection_types(enheter_opener, landing, scope) -> None:
    acquire_enheter(enheter_opener, landing, scope)
    rows = {r["organisasjonsnummer"]: r for r in read_table(landing.root / "enheter").to_pylist()}
    a1, a2, asa = rows[AS_1], rows[AS_2], rows[ASA_1]
    assert a1["kapital_belop"] == 30000.0
    assert a1["antall_ansatte"] == 12
    assert a1["naeringskode1"] == "62.010"
    assert a1["forretningsadresse_kommunenummer"] == "0301"
    assert a1["stiftelsesdato"] == date(2015, 2, 1)
    assert a1["siste_innsendte_aarsregnskap"] == 2024
    assert a1["har_hjemmeside"] is True
    assert a1["konkurs"] is False and a1["konkursdato"] is None
    assert a2["konkurs"] is True and a2["konkursdato"] == date(2024, 11, 20)
    assert a2["antall_paategninger"] == 1 and a2["paategning_infotyper"] == "AVVIKLING"
    assert a2["antall_historiske_navn"] == 1
    assert a2["har_hjemmeside"] is False
    assert a2["antall_ansatte"] is None
    assert asa["organisasjonsform"] == "ASA" and asa["er_i_konsern"] is True
    assert asa["kapital_innbetalt"] is None
    assert rows[AS_AUDITOR]["naeringskode1"] == "69.201"


def test_text_goes_to_separate_table(enheter_opener, landing, scope) -> None:
    acquire_enheter(enheter_opener, landing, scope)
    enheter = read_table(landing.root / "enheter")
    assert "vedtektsfestet_formaal" not in enheter.column_names
    text = read_table(landing.root / "enheter_tekst").to_pylist()
    assert {r["organisasjonsnummer"] for r in text} == KEPT_UNITS
    first = next(r for r in text if r["organisasjonsnummer"] == AS_1)
    assert first["vedtektsfestet_formaal"].startswith("Utvikling av programvare")
