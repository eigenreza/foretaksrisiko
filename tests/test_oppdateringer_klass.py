"""privacy-scan: allow-dates"""

from __future__ import annotations

import random
from urllib.parse import parse_qs

import httpx

from conftest import AS_1, AS_2, ENK_1, KEPT_UNITS, SUB_1
from foretaksrisiko.acquire.http import PoliteClient
from foretaksrisiko.acquire.klass import acquire_klass
from foretaksrisiko.acquire.landing import read_table
from foretaksrisiko.acquire.oppdateringer import acquire_updates
from foretaksrisiko.config import BrregConfig, KlassConfig


def _client(handler) -> PoliteClient:
    return PoliteClient(
        base_url="https://example.invalid",
        user_agent="test",
        requests_per_second=1000,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        rng=random.Random(0),
    )


def test_updates_are_paged_and_reduced_to_counts(landing, monkeypatch) -> None:
    monkeypatch.setattr("foretaksrisiko.acquire.oppdateringer.PAGE_SIZE", 2)
    unit_events = [
        {
            "oppdateringsid": 1,
            "dato": "2026-01-02T10:00:00.000Z",
            "organisasjonsnummer": AS_1,
            "endringstype": "Endring",
        },
        {
            "oppdateringsid": 2,
            "dato": "2026-01-03T10:00:00.000Z",
            "organisasjonsnummer": ENK_1,
            "endringstype": "Endring",
        },
        {
            "oppdateringsid": 3,
            "dato": "2026-01-04T10:00:00.000Z",
            "organisasjonsnummer": AS_1,
            "endringstype": "Endring",
        },
        {
            "oppdateringsid": 4,
            "dato": "2026-01-05T10:00:00.000Z",
            "organisasjonsnummer": AS_2,
            "endringstype": "Sletting",
        },
        {
            "oppdateringsid": 5,
            "dato": "2026-01-06T10:00:00.000Z",
            "organisasjonsnummer": AS_1,
            "endringstype": "Ny",
        },
    ]
    sub_events = [
        {
            "oppdateringsid": 7,
            "dato": "2026-01-02T10:00:00.000Z",
            "organisasjonsnummer": SUB_1,
            "endringstype": "Endring",
        },
    ]
    role_events = [
        {
            "id": "11",
            "time": "2026-01-02T10:00:00Z",
            "type": "rolle.oppdatert",
            "data": {"organisasjonsnummer": AS_1},
        },
        {
            "id": "12",
            "time": "2026-01-03T10:00:00Z",
            "type": "rolle.oppdatert",
            "data": {"organisasjonsnummer": ENK_1},
        },
        {
            "id": "13",
            "time": "2026-01-04T10:00:00Z",
            "type": "rolle.oppdatert",
            "data": {"organisasjonsnummer": AS_1},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        size = int(params["size"])
        if request.url.path.endswith("/oppdateringer/enheter"):
            start = int(params.get("oppdateringsid", 0))
            page = [e for e in unit_events if e["oppdateringsid"] >= start][:size]
            return httpx.Response(200, json={"_embedded": {"oppdaterteEnheter": page}})
        if request.url.path.endswith("/oppdateringer/underenheter"):
            start = int(params.get("oppdateringsid", 0))
            page = [e for e in sub_events if e["oppdateringsid"] >= start][:size]
            return httpx.Response(200, json={"_embedded": {"oppdaterteUnderenheter": page}})
        if request.url.path.endswith("/oppdateringer/roller"):
            after = int(params.get("afterId", 0))
            page = [e for e in role_events if int(e["id"]) > after][:size]
            return httpx.Response(200, json=page)
        return httpx.Response(404)

    summary = acquire_updates(
        _client(handler),
        BrregConfig(),
        landing,
        "2026-01-01T00:00:00.000Z",
        set(KEPT_UNITS),
        {SUB_1},
    )
    rows = read_table(landing.root / "oppdateringer_enheter").to_pylist()
    by_key = {(r["organisasjonsnummer"], r["endringstype"]): r for r in rows}
    assert set(by_key) == {(AS_1, "Endring"), (AS_1, "Ny"), (AS_2, "Sletting")}
    assert by_key[(AS_1, "Endring")]["n_events"] == 2
    assert by_key[(AS_1, "Endring")]["first_dato"].startswith("2026-01-02")
    assert by_key[(AS_1, "Endring")]["last_dato"].startswith("2026-01-04")
    assert summary["oppdateringer_enheter"]["events_total"] == 5
    assert summary["oppdateringer_enheter"]["by_type"] == {"Endring": 1, "Ny": 1, "Sletting": 1}
    sub_rows = read_table(landing.root / "oppdateringer_underenheter").to_pylist()
    assert [r["organisasjonsnummer"] for r in sub_rows] == [SUB_1]
    roles = read_table(landing.root / "oppdateringer_roller").to_pylist()
    assert roles == [
        {
            "organisasjonsnummer": AS_1,
            "n_events": 2,
            "first_time": "2026-01-02T10:00:00Z",
            "last_time": "2026-01-04T10:00:00Z",
        }
    ]


def test_klass_tables_and_licence(landing) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/versions/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "name": "Test standard",
                    "validFrom": "2025-01-01",
                    "classificationItems": [
                        {
                            "code": "A",
                            "parentCode": "",
                            "level": "1",
                            "name": "Jordbruk",
                            "shortName": "",
                            "notes": "",
                        },
                        {
                            "code": "01",
                            "parentCode": "A",
                            "level": "2",
                            "name": "Jordbruk",
                            "shortName": "",
                            "notes": "n",
                        },
                    ],
                },
            )
        if "/correspondencetables/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "name": "Corr",
                    "correspondenceMaps": [
                        {
                            "sourceCode": "01.110",
                            "sourceName": "a",
                            "targetCode": "01.110",
                            "targetName": "b",
                        }
                    ],
                },
            )
        return httpx.Response(404)

    summary = acquire_klass(_client(handler), landing, KlassConfig())
    assert summary["licence"] == "CC BY 4.0"
    assert summary["sn2025"]["n_items"] == 2
    assert summary["sn_corr_2025_2007"]["n_maps"] == 1
    rows = read_table(landing.root / "klass" / "sn2025").to_pylist()
    assert rows[0]["parent_code"] is None and rows[1]["parent_code"] == "A"
    assert rows[1]["level"] == 2
    corr = read_table(landing.root / "klass" / "kommune_corr_2026_2024").to_pylist()
    assert corr[0]["target_code"] == "01.110"
    assert landing.read_manifest()["klass"]["licence"] == "CC BY 4.0"
