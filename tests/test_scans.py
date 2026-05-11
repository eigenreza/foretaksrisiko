"""Tests for the style and privacy scan scripts. Trigger words are built at runtime."""

from __future__ import annotations

from pathlib import Path

import privacy_scan
import style_scan
from foretaksrisiko.orgnr import mod11_check_digit


def _valid_orgnr() -> str:
    for n in range(91_000_000, 91_000_100):
        digit = mod11_check_digit(str(n))
        if digit is not None:
            return f"{n}{digit}"
    raise AssertionError("no check digit found")


def _rules(findings) -> list[str]:
    return sorted(f.rule for f in findings)


def test_style_scan_flags_dashes_and_words() -> None:
    em = chr(0x2014)
    en = chr(0x2013)
    banned = "fra" + "ud"
    lines = [
        "A clean line.",
        f"A bad {em} line.",
        f"Pages 10{en}12 are fine.",
        f"Words {en} like this fail.",
        f"No {banned} here.",
    ]
    text = "\n".join(lines)
    rules = _rules(style_scan.scan_text(text, "x.md"))
    assert rules == ["banned-word", "em-dash", "en-dash-as-sentence-dash"]
    assert style_scan.scan_text("plain text", "x.md") == []


def test_style_scan_marker_allows_word_list() -> None:
    banned = "svin" + "del"
    text = f"{style_scan.ALLOW_BANNED_MARKER}\n{banned}"
    assert style_scan.scan_text(text, "x.py") == []


def test_privacy_scan_flags_valid_orgnr_only() -> None:
    valid = _valid_orgnr()
    invalid = valid[:8] + str((int(valid[8]) + 1) % 10)
    assert _rules(privacy_scan.scan_text(f"number {valid}", "x.md")) == [
        "valid-organisation-number"
    ]
    assert privacy_scan.scan_text(f"number {invalid}", "x.md") == []
    assert privacy_scan.scan_text(f"sha256:ab{valid}cd", "x.md") == []


def test_privacy_scan_person_fields_and_marker() -> None:
    field = "for" + "navn"
    assert _rules(privacy_scan.scan_text(f"col = '{field}'", "x.py")) == ["person-field-name"]
    with_marker = f"# {privacy_scan.ALLOW_PERSON_MARKER}\ncol = '{field}'"
    assert privacy_scan.scan_text(with_marker, "x.py") == []


def test_privacy_scan_dates_years_and_attribution() -> None:
    year = "20" + "24"
    iso_date = f"{year}-05-01"
    assert _rules(privacy_scan.scan_text(f"built {iso_date}", "x.py")) == ["calendar-date"]
    assert privacy_scan.scan_text(f"{privacy_scan.ALLOW_DATES_MARKER}\n{iso_date}", "x.py") == []
    warnings = privacy_scan.scan_text(f"the standard from {year}", "x.md")
    assert [f.severity for f in warnings] == ["warn"]
    assert privacy_scan.scan_text(f"the standard from {year}", "x.py") == []
    attribution = "Co-Authored" + "-By: someone"
    assert _rules(privacy_scan.scan_text(attribution, "x.txt")) == ["tool-attribution"]


def test_repository_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    files = privacy_scan.repo_files(root)
    assert files
    privacy_findings = [f for f in privacy_scan.scan_paths(files, root) if f.severity == "fail"]
    assert privacy_findings == []
    assert style_scan.scan_paths(style_scan.repo_files(root), root) == []
