"""HTTP client tests.

privacy-scan: allow-dates
"""

from __future__ import annotations

import gzip
import json
import random

import httpx
import pytest

from foretaksrisiko.acquire.http import (
    PoliteClient,
    RateLimiter,
    RetryError,
    gzip_stream,
    parse_http_date,
    parse_retry_after,
)
from foretaksrisiko.acquire.jsonstream import iter_items


def test_rate_limiter_spaces_requests() -> None:
    clock = {"now": 100.0}
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    limiter = RateLimiter(4, clock=lambda: clock["now"], sleep=sleep)
    for _ in range(5):
        limiter.wait()
    assert sleeps == pytest.approx([0.25, 0.25, 0.25, 0.25])


def test_parse_retry_after_seconds_and_date() -> None:
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(
        "Wed, 21 Oct 2015 07:28:00 GMT", now=lambda: 1445412470.0
    ) == pytest.approx(10.0)


def test_parse_http_date_accepts_rfc_and_brreg_formats() -> None:
    rfc = parse_http_date("Wed, 21 Oct 2015 07:28:00 GMT")
    assert rfc is not None and rfc.isoformat() == "2015-10-21T07:28:00+00:00"
    brreg = parse_http_date("Tue Nov 03 04:28:15 CET 2026")
    assert brreg is not None and brreg.isoformat() == "2026-11-03T04:28:15+01:00"
    assert parse_http_date("nonsense") is None
    assert parse_http_date(None) is None


def _client(handler, max_retries: int = 3) -> tuple[PoliteClient, list[float]]:
    sleeps: list[float] = []
    client = PoliteClient(
        base_url="https://example.invalid",
        user_agent="test",
        requests_per_second=1000,
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        rng=random.Random(0),
        limiter=RateLimiter(1000, sleep=lambda s: None),
    )
    return client, sleeps


def test_retries_with_retry_after_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client, sleeps = _client(handler)
    response = client.get("/x")
    assert response.status_code == 200
    assert len(calls) == 3
    assert sleeps[0] == 2.0
    assert len(sleeps) == 2
    assert client.request_count == 3


def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client, _ = _client(handler, max_retries=2)
    with pytest.raises(RetryError):
        client.get("/x")
    assert client.request_count == 3


def test_404_is_returned_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client, sleeps = _client(handler)
    assert client.get("/x").status_code == 404
    assert sleeps == []


def test_user_agent_header_is_generic() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200)

    client, _ = _client(handler)
    client.get("/x")
    assert seen["ua"] == "test"
    assert "@" not in seen["ua"]


@pytest.mark.parametrize("as_stream", [True, False])
def test_gzip_stream_feeds_json_items(as_stream: bool) -> None:
    payload = gzip.compress(json.dumps([{"a": 1}, {"a": 2.5}]).encode())
    headers = {"Content-Type": "application/gzip"}

    def handler(request: httpx.Request) -> httpx.Response:
        if as_stream:
            return httpx.Response(200, stream=httpx.ByteStream(payload), headers=headers)
        return httpx.Response(200, content=payload, headers=headers)

    client, _ = _client(handler)
    with client.stream("/bulk", headers={"Accept": "application/gzip"}) as response:
        items = list(iter_items(gzip_stream(response, chunk_size=7)))
    assert items == [{"a": 1}, {"a": 2.5}]
    assert isinstance(items[1]["a"], float)
