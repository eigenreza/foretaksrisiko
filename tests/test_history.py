"""privacy-scan: allow-dates"""

from __future__ import annotations

import random
from urllib.parse import parse_qs

import httpx

from conftest import AS_1, AS_2, ENK_1, FAKE_LAST, KEPT_UNITS
from foretaksrisiko.acquire.history import acquire_history, reduce_event
from foretaksrisiko.acquire.http import PoliteClient
from foretaksrisiko.acquire.landing import read_table
from foretaksrisiko.config import BrregConfig


def _event(
    oid: int,
    orgnr: str,
    typ: str,
    changes: list[dict] | None = None,
    dato: str = "2026-06-01T10:00:00.000Z",
) -> dict:
    return {
        "oppdateringsid": oid,
        "dato": dato,
        "organisasjonsnummer": orgnr,
        "endringstype": typ,
        "endringer": changes,
    }


def test_reduce_event_keeps_field_names_and_status_values_only() -> None:
    event = _event(
        5,
        AS_1,
        "Endring",
        [
            {"op": "replace", "path": "/navn", "value": f"NYTT NAVN {FAKE_LAST}"},
            {"op": "replace", "path": "/forretningsadresse/adresse/0", "value": "Hemmelig vei 1"},
            {"op": "replace", "path": "/konkurs", "value": True},
            {"op": "add", "path": "/konkursdato", "value": "2026-05-30"},
            {"op": "replace", "path": "/sisteInnsendteAarsregnskap", "value": "2025"},
            {"op": "add", "path": "/tvangsopplostPgaManglendeRegnskapDato", "value": "2026-06-01"},
            {"op": "remove", "path": "/aktivitet/1"},
        ],
    )
    row = reduce_event(event)
    expected_fields = [
        "aktivitet",
        "forretningsadresse",
        "konkurs",
        "konkursdato",
        "navn",
        "sisteInnsendteAarsregnskap",
        "tvangsopplostPgaManglendeRegnskapDato",
    ]
    assert row["changed_fields"] == ";".join(expected_fields)
    assert row["n_changes"] == 7
    assert row["konkurs"] is True and row["konkursdato"].isoformat() == "2026-05-30"
    assert row["tvang_dato"].isoformat() == "2026-06-01"
    assert row["siste_innsendte_aarsregnskap"] == 2025
    assert row["under_avvikling"] is None
    text = " ".join(str(v) for v in row.values())
    assert FAKE_LAST not in text and "Hemmelig" not in text


def test_history_filters_population_and_aggregates_the_rest(landing) -> None:
    events = [
        _event(
            1,
            AS_1,
            "Endring",
            [{"op": "replace", "path": "/konkurs", "value": True}],
            "2026-05-02T10:00:00.000Z",
        ),
        _event(
            2,
            ENK_1,
            "Endring",
            [{"op": "replace", "path": "/navn", "value": FAKE_LAST}],
            "2026-05-03T10:00:00.000Z",
        ),
        _event(3, ENK_1, "Sletting", None, "2026-06-03T10:00:00.000Z"),
        _event(4, AS_2, "Endring", None, "2026-06-04T10:00:00.000Z"),
    ]
    roles = [
        {
            "id": "7",
            "time": "2026-05-02T11:00:00Z",
            "type": "x",
            "data": {"organisasjonsnummer": AS_1},
        },
        {
            "id": "8",
            "time": "2026-05-02T12:00:00Z",
            "type": "x",
            "data": {"organisasjonsnummer": ENK_1},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if request.url.path.endswith("/oppdateringer/enheter"):
            assert params.get("includeChanges") == "true"
            start = int(params.get("oppdateringsid", 0))
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "oppdaterteEnheter": [e for e in events if e["oppdateringsid"] >= start]
                    }
                },
            )
        if request.url.path.endswith("/oppdateringer/roller"):
            after = int(params.get("afterId", 0))
            return httpx.Response(200, json=[r for r in roles if int(r["id"]) > after])
        return httpx.Response(404)

    client = PoliteClient(
        "https://example.invalid",
        "test",
        requests_per_second=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        rng=random.Random(0),
    )
    summary = acquire_history(
        client, BrregConfig(), landing, "2026-05-01T00:00:00.000Z", set(KEPT_UNITS)
    )
    assert summary["events_total"] == 4 and summary["events_population"] == 2
    assert summary["role_events_total"] == 2 and summary["role_events_population"] == 1
    rows = read_table(landing.root / "events_enheter").to_pylist()
    assert [r["organisasjonsnummer"] for r in rows] == [AS_1, AS_2]
    assert rows[0]["konkurs"] is True and rows[1]["changed_fields"] is None
    monthly = {
        (r["month"], r["endringstype"], r["field"], r["in_population"]): r["n_events"]
        for r in read_table(landing.root / "events_monthly_all").to_pylist()
    }
    assert monthly[("2026-05", "Endring", "*", True)] == 1
    assert monthly[("2026-05", "Endring", "*", False)] == 1
    assert monthly[("2026-06", "Sletting", "*", False)] == 1
    assert monthly[("2026-05", "Endring", "konkurs", True)] == 1
    all_text = " ".join(str(r) for r in rows) + " ".join(str(k) for k in monthly)
    assert FAKE_LAST not in all_text and ENK_1 not in all_text
    role_rows = read_table(landing.root / "events_roller").to_pylist()
    assert role_rows == [
        {"organisasjonsnummer": AS_1, "event_id": 7, "time": "2026-05-02T11:00:00Z"}
    ]


def test_feed_timestamp_normalises_offsets_and_precision() -> None:
    from foretaksrisiko.acquire.history import feed_timestamp

    assert feed_timestamp("2026-11-03T03:28:15+00:00") == "2026-11-03T03:28:15.000Z"
    assert feed_timestamp("2026-11-03T05:28:15+02:00") == "2026-11-03T03:28:15.000Z"
    assert feed_timestamp("2025-05-01T00:00:00.000Z") == "2025-05-01T00:00:00.000Z"
    assert feed_timestamp("2025-05-01") == "2025-05-01T00:00:00.000Z"
