"""Norwegian organisation number (organisasjonsnummer) checksum, MOD11."""

from __future__ import annotations

WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def mod11_check_digit(first_eight: str) -> int | None:
    """Return the MOD11 check digit for eight digits, or None when no valid digit exists."""
    if len(first_eight) != 8 or not first_eight.isdigit():
        raise ValueError("expected exactly eight digits")
    total = sum(int(d) * w for d, w in zip(first_eight, WEIGHTS, strict=True))
    remainder = total % 11
    if remainder == 0:
        return 0
    check = 11 - remainder
    if check == 10:
        return None
    return check


def is_valid_orgnr(value: str | None) -> bool:
    """True when value is nine digits whose last digit is the MOD11 check digit."""
    if value is None or len(value) != 9 or not value.isdigit():
        return False
    expected = mod11_check_digit(value[:8])
    return expected is not None and expected == int(value[8])
