"""Small, strict converters from register JSON values to typed column values."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date


def to_date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def to_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def to_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def to_year(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return to_int(text[:4]) if len(text) >= 4 else None


def code(obj: object) -> str | None:
    """The ``kode`` of a code object such as organisasjonsform or naeringskode1."""
    if isinstance(obj, dict):
        value = obj.get("kode")
        return str(value) if value is not None else None
    return None


def join_lines(values: object) -> str | None:
    if not isinstance(values, list):
        return None
    lines = [str(v).strip() for v in values if v]
    return "\n".join(lines) if lines else None


def count(values: object) -> int:
    return len(values) if isinstance(values, list) else 0


def non_empty(value: object) -> bool:
    return bool(value)


def dig(obj: object, path: Iterable[str]) -> object:
    """Follow nested keys; None when any step is missing."""
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
