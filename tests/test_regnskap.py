"""privacy-scan: allow-dates"""

from __future__ import annotations

import random
from datetime import date

import httpx

from conftest import AS_1, AS_2, ASA_1
from foretaksrisiko.acquire.http import PoliteClient
from foretaksrisiko.acquire.landing import read_table
from foretaksrisiko.acquire.regnskap import REGNSKAP_SCHEMA, RegnskapFetcher, flatten_regnskap


def _item(year: int, typ: str = "SELSKAP", innskutt_key: str = "sumInnskuttEgenkaptial") -> dict:
    return {
        "id": year * 10,
        "journalnr": "ignored",
        "regnskapstype": typ,
        "virksomhet": {"organisasjonsnummer": "x", "organisasjonsform": "AS", "morselskap": False},
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "valuta": "NOK",
        "avviklingsregnskap": False,
        "oppstillingsplan": "smaa",
        "revisjon": {"ikkeRevidertAarsregnskap": True, "fravalgRevisjon": True},
        "regnkapsprinsipper": {
            "smaaForetak": True,
            "regnskapsregler": "regnskapslovenAlminneligRegler",
        },
        "egenkapitalGjeld": {
            "sumEgenkapitalGjeld": 1000.0,
            "egenkapital": {
                "sumEgenkapital": 400.0,
                "opptjentEgenkapital": {"sumOpptjentEgenkapital": 370.0},
                "innskuttEgenkapital": {innskutt_key: 30.0},
            },
            "gjeldOversikt": {
                "sumGjeld": 600.0,
                "kortsiktigGjeld": {"sumKortsiktigGjeld": 500.0},
                "langsiktigGjeld": {"sumLangsiktigGjeld": 100.0},
            },
        },
        "eiendeler": {"sumEiendeler": 1000.0, "omloepsmidler": {"sumOmloepsmidler": 800.0}},
        "resultatregnskapResultat": {
            "aarsresultat": 50.0,
            "driftsresultat": {
                "driftsresultat": 70.0,
                "driftsinntekter": {"sumDriftsinntekter": 900.0, "salgsinntekter": 890.0},
                "driftskostnad": {"sumDriftskostnad": 830.0, "loennskostnad": 400.0},
            },
            "finansresultat": {"nettoFinans": -5.0, "finanskostnad": {"sumFinanskostnad": 5.0}},
        },
    }


def test_flatten_reads_nested_fields_and_source_typo() -> None:
    row = flatten_regnskap(AS_1, _item(2024))
    assert set(row) == set(REGNSKAP_SCHEMA.names)
    assert row["regnskap_id"] == 20240
    assert row["regnskapsperiode_til_dato"] == date(2024, 12, 31)
    assert row["sum_innskutt_egenkapital"] == 30.0
    assert row["sum_kortsiktig_gjeld"] == 500.0
    assert row["loennskostnad"] == 400.0
    assert row["netto_finans"] == -5.0
    assert row["goodwill"] is None
    assert row["fravalg_revisjon"] is True
    corrected = flatten_regnskap(AS_1, _item(2024, innskutt_key="sumInnskuttEgenkapital"))
    assert corrected["sum_innskutt_egenkapital"] == 30.0


def _make_fetcher(landing, handler, max_retries: int = 1) -> RegnskapFetcher:
    client = PoliteClient(
        base_url="https://example.invalid",
        user_agent="test",
        requests_per_second=1000,
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        rng=random.Random(0),
    )
    return RegnskapFetcher(client, landing, "/regnskap/{orgnr}", batch_size=2, workers=3)


def test_fetch_is_resumable_and_idempotent(landing) -> None:
    attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        orgnr = request.url.path.rsplit("/", 1)[-1]
        attempts[orgnr] = attempts.get(orgnr, 0) + 1
        if orgnr == AS_1:
            return httpx.Response(200, json=[_item(2023), _item(2024), _item(2024, "KONSERN")])
        if orgnr == AS_2:
            return httpx.Response(404)
        if attempts[orgnr] <= 2:
            return httpx.Response(500)
        return httpx.Response(200, json=[_item(2024)])

    fetcher = _make_fetcher(landing, handler)
    first = fetcher.run([AS_1, AS_2, ASA_1])
    assert first["ok"] == 1 and first["not_found"] == 1 and first["failed"] == 1
    assert first["rows"] == 3
    assert fetcher.fetched() == {AS_1, AS_2}

    second = fetcher.run([AS_1, AS_2, ASA_1])
    assert second["requested"] == 1
    assert second["ok"] == 1 and second["failed"] == 0
    assert fetcher.fetched() == {AS_1, AS_2, ASA_1}
    assert attempts[AS_1] == 1

    rows = read_table(landing.root / "regnskap").to_pylist()
    assert len(rows) == 4
    assert {r["organisasjonsnummer"] for r in rows} == {AS_1, ASA_1}
    status = read_table(landing.root / "regnskap_status").to_pylist()
    by_orgnr = {(r["organisasjonsnummer"], r["http_status"]) for r in status}
    assert (AS_2, 404) in by_orgnr and (AS_1, 200) in by_orgnr and (ASA_1, 0) in by_orgnr

    third = fetcher.run([AS_1, AS_2, ASA_1])
    assert third["requested"] == 0
    assert landing.read_manifest()["regnskap"]["fetched_total"] == 3


def test_carry_forward_copies_unchanged_accounts_and_refetches_the_rest(tmp_path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from conftest import fake_orgnr
    from foretaksrisiko.acquire.history import EVENTS_SCHEMA
    from foretaksrisiko.acquire.landing import Landing
    from foretaksrisiko.acquire.regnskap import filing_changed_companies

    as_3 = fake_orgnr(13)
    first, second = Landing(tmp_path, 1), Landing(tmp_path, 2)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        orgnr = request.url.path.rsplit("/", 1)[-1]
        calls.append(orgnr)
        if orgnr == AS_2:
            return httpx.Response(404)
        items = [_item(2023), _item(2024)] if orgnr == AS_1 else [_item(2024)]
        return httpx.Response(200, json=items)

    _make_fetcher(first, handler).run([AS_1, AS_2, ASA_1])
    assert sorted(calls) == sorted([AS_1, AS_2, ASA_1])

    # Snapshot 2: AS_2 reports a new filing, as_3 is new, nobody is due for the rolling refresh.
    event = {name: None for name in EVENTS_SCHEMA.names}
    event.update(
        {
            "organisasjonsnummer": AS_2,
            "oppdateringsid": 1,
            "dato": "x",
            "endringstype": "Endring",
            "n_changes": 1,
            "changed_fields": "sisteInnsendteAarsregnskap",
        }
    )
    pq.write_table(
        pa.Table.from_pylist([event], schema=EVENTS_SCHEMA),
        second.table_dir("events_enheter") / "part-00000.parquet",
    )
    assert filing_changed_companies(second) == {AS_2}
    kept = {AS_1, AS_2, ASA_1, as_3}
    fetcher = _make_fetcher(second, handler)
    plan = fetcher.carry_forward(first, kept, filing_changed_companies(second), refresh_share=0.0)
    assert plan["carried_forward"] == 2 and plan["new"] == 1 and plan["filing_changed"] == 1
    assert plan["refresh_due"] == 0
    calls.clear()
    result = fetcher.run(sorted(kept))
    assert sorted(calls) == sorted([AS_2, as_3]) and result["requested"] == 2

    rows = read_table(second.root / "regnskap").to_pylist()
    per_company: dict[str, int] = {}
    for row in rows:
        per_company[row["organisasjonsnummer"]] = per_company.get(row["organisasjonsnummer"], 0) + 1
    assert per_company == {AS_1: 2, ASA_1: 1, as_3: 1}
    status_rows = read_table(second.root / "regnskap_status").to_pylist()
    status = {r["organisasjonsnummer"]: r for r in status_rows}
    assert status[AS_1]["source_snapshot_id"] == 1 and status[ASA_1]["source_snapshot_id"] == 1
    assert status[AS_2]["source_snapshot_id"] == 2 and status[as_3]["source_snapshot_id"] == 2
    assert status[AS_2]["http_status"] == 404 and status[AS_1]["http_status"] == 200
    assert second.read_manifest()["regnskap_carry_forward"]["carried_forward"] == 2

    # A rerun carries nothing more and requests nothing.
    again = fetcher.carry_forward(first, kept, set(), refresh_share=0.0)
    assert again["carried_forward"] == 0 and fetcher.run(sorted(kept))["requested"] == 0
    # The plan from the first start stays on record after such a restart.
    entry = second.read_manifest()["regnskap_carry_forward"]
    assert entry["carried_forward"] == 2 and entry["new"] == 1 and entry["filing_changed"] == 1

    # With a refresh share of one, every company is due; provenance chains back to snapshot 1.
    third = Landing(tmp_path, 3)
    plan3 = _make_fetcher(third, handler).carry_forward(second, kept, set(), refresh_share=1.0)
    assert plan3["refresh_due"] == 4 and plan3["carried_forward"] == 0
    plan3b = _make_fetcher(third, handler).carry_forward(second, kept, set(), refresh_share=0.0)
    assert plan3b["carried_forward"] == 4
    status3 = {
        r["organisasjonsnummer"]: r for r in read_table(third.root / "regnskap_status").to_pylist()
    }
    assert status3[AS_1]["source_snapshot_id"] == 1 and status3[as_3]["source_snapshot_id"] == 2
