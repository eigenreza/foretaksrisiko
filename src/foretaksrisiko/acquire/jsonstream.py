"""Streaming iteration over large JSON arrays, so bulk files never need to fit in memory."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import BinaryIO

import ijson

StreamOpener = Callable[[], AbstractContextManager[BinaryIO]]


def iter_items(stream: BinaryIO) -> Iterator[dict]:
    """Yield each element of a top-level JSON array, one at a time."""
    peek = getattr(stream, "peek", None)
    if peek is not None:
        head = peek(1)[:1]
        if head and head not in (b"[", b" ", b"\n", b"\r", b"\t"):
            raise ValueError("expected a JSON array at the top level of the bulk file")
    for item in ijson.items(stream, "item", use_float=True):
        if isinstance(item, dict):
            yield item
