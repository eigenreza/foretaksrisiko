from foretaksrisiko.orgnr import is_valid_orgnr, mod11_check_digit


def test_check_digit_round_trip() -> None:
    first8 = "12345678"
    digit = mod11_check_digit(first8)
    assert digit is not None
    assert is_valid_orgnr(first8 + str(digit))
    assert not is_valid_orgnr(first8 + str((digit + 1) % 10))


def test_zero_remainder_gives_zero_digit() -> None:
    all_zero = "0" * 8
    assert mod11_check_digit(all_zero) == 0
    assert is_valid_orgnr(all_zero + "0")


def test_rejects_malformed() -> None:
    assert not is_valid_orgnr(None)
    assert not is_valid_orgnr("12345678")
    assert not is_valid_orgnr("1234567890")
    assert not is_valid_orgnr("12345678a")


def test_some_prefixes_have_no_check_digit() -> None:
    found = any(mod11_check_digit(f"{n:08d}") is None for n in range(10_000, 10_100))
    assert found
