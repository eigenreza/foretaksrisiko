"""Polite HTTP client: rate limit, exponential backoff with jitter, Retry-After, streaming."""

from __future__ import annotations

import email.utils
import gzip
import io
import logging
import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class RetryError(RuntimeError):
    """Raised when a request keeps failing after all retries."""


class RateLimiter:
    """Allows at most ``requests_per_second`` calls, spaced evenly."""

    def __init__(
        self,
        requests_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until the next slot. Threads sharing one limiter get slots in turn."""
        with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if delay > 0:
            self._sleep(delay)


def parse_retry_after(value: str | None, now: Callable[[], float] = time.time) -> float | None:
    """Seconds to wait from a Retry-After header, which is either seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed.timestamp() - now())


_ZONE_OFFSETS = {"GMT": 0, "UTC": 0, "CET": 1, "CEST": 2}


def parse_http_date(value: str | None) -> datetime | None:
    """Parse a Last-Modified header, RFC 7231 or Brreg's ``Tue Nov 03 04:28:15 CET 2026`` form."""
    if not value:
        return None
    parts = value.split()
    if len(parts) == 6 and "," not in value and parts[4] in _ZONE_OFFSETS:
        try:
            naive = datetime.strptime(" ".join(parts[:4] + parts[5:]), "%a %b %d %H:%M:%S %Y")
        except ValueError:
            return None
        return naive.replace(tzinfo=timezone(timedelta(hours=_ZONE_OFFSETS[parts[4]])))
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class PoliteClient:
    """Sequential HTTP client that respects a request budget and server backoff signals."""

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        requests_per_second: float = 4.0,
        max_retries: int = 8,
        timeout_seconds: float = 60.0,
        backoff_base_seconds: float = 1.0,
        backoff_cap_seconds: float = 120.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )
        self._limiter = limiter or RateLimiter(requests_per_second)
        self._max_retries = max_retries
        self._base = backoff_base_seconds
        self._cap = backoff_cap_seconds
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.request_count = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            delay = min(retry_after, self._cap)
        else:
            delay = min(self._cap, self._base * 2**attempt) * (0.5 + self._rng.random())
        log.info("backing off %.1f s", delay)
        self._sleep(delay)

    def get(
        self,
        path: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        """GET with retries. Returns any non-retryable response, including 404."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.wait()
            self.request_count += 1
            try:
                response = self._client.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("transport error (%s), attempt %d", type(exc).__name__, attempt + 1)
                self._backoff(attempt, None)
                continue
            if response.status_code in RETRY_STATUSES:
                log.warning("status %d, attempt %d", response.status_code, attempt + 1)
                self._backoff(attempt, parse_retry_after(response.headers.get("Retry-After")))
                continue
            return response
        raise RetryError(f"gave up after {self._max_retries + 1} attempts") from last_error

    @contextmanager
    def stream(self, path: str, headers: dict | None = None) -> Iterator[httpx.Response]:
        """Streaming GET with retries on the initial status. The body is read by the caller."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._limiter.wait()
            self.request_count += 1
            request = self._client.build_request("GET", path, headers=headers)
            try:
                response = self._client.send(request, stream=True)
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("transport error (%s), attempt %d", type(exc).__name__, attempt + 1)
                self._backoff(attempt, None)
                continue
            if response.status_code in RETRY_STATUSES:
                response.close()
                log.warning("status %d, attempt %d", response.status_code, attempt + 1)
                self._backoff(attempt, parse_retry_after(response.headers.get("Retry-After")))
                continue
            try:
                yield response
            finally:
                response.close()
            return
        raise RetryError(f"gave up after {self._max_retries + 1} attempts") from last_error


class _IteratorReader(io.RawIOBase):
    """File-like view over an iterator of byte chunks."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:  # type: ignore[override]
        while not self._pending:
            try:
                self._pending = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(buffer), len(self._pending))
        buffer[:n] = self._pending[:n]
        self._pending = self._pending[n:]
        return n


def _raw_chunks(response: httpx.Response, chunk_size: int) -> Iterator[bytes]:
    if response.is_stream_consumed or response.is_closed:
        content = response.content
        for start in range(0, len(content), chunk_size):
            yield content[start : start + chunk_size]
        return
    yield from response.iter_raw(chunk_size)


def gzip_stream(response: httpx.Response, chunk_size: int = 1 << 20) -> gzip.GzipFile:
    """Decompress a gzip response as a stream, without writing it to disk."""
    reader = io.BufferedReader(
        _IteratorReader(_raw_chunks(response, chunk_size)), buffer_size=chunk_size
    )
    return gzip.GzipFile(fileobj=reader, mode="rb")
