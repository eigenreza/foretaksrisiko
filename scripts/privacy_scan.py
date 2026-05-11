"""Privacy scan for the repository (brief rule L11 and section 16, P8).

Fails on:
  - nine-digit numbers that pass the MOD11 organisation number checksum,
  - person field names, unless the file carries the marker ``privacy-scan: allow-person-fields``,
  - calendar dates, unless the file carries the marker ``privacy-scan: allow-dates``,
  - tool attribution strings that must never appear in this repository.
Warns on four-digit years in Markdown files, for manual review.

Usage: python scripts/privacy_scan.py [path ...]
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from foretaksrisiko.orgnr import is_valid_orgnr  # noqa: E402

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".cfg",
    ".ini",
    ".html",
    ".css",
    ".js",
    ".svg",
    ".csv",
    ".sql",
    ".sh",
    ".ps1",
    ".ipynb",
    ".bicep",
}
TEXT_NAMES = {"Dockerfile", "LICENSE", "Makefile"}
SKIP_NAMES = {"uv.lock"}

NINE_DIGITS = re.compile(r"(?<![0-9A-Za-z])(\d{9})(?![0-9A-Za-z])")
PERSON_FIELDS = re.compile(
    r"\b(fodselsdato|foedselsdato|fødselsdato|fornavn|etternavn|mellomnavn|"
    r"fodselsnummer|foedselsnummer|fødselsnummer|personnummer)\b",
    re.IGNORECASE,
)
DATES = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})(?!\d)")
YEARS = re.compile(r"\b(19|20)\d{2}\b")
ATTRIBUTION = re.compile(r"Co-Authored-By|Generated with|claude\.ai|Anthropic", re.IGNORECASE)

ALLOW_PERSON_MARKER = "privacy-scan: allow-person-fields"
ALLOW_DATES_MARKER = "privacy-scan: allow-dates"
SELF = Path(__file__).resolve()


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    snippet: str
    severity: str = "fail"

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.severity}: {self.rule}: {self.snippet.strip()[:120]}"
        )


def repo_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    paths = [root / p for p in out.split("\0") if p]
    return [p for p in paths if p.is_file() and is_text_file(p)]


def is_text_file(path: Path) -> bool:
    if path.name in SKIP_NAMES:
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def scan_text(text: str, path: str, is_self: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    allow_person = ALLOW_PERSON_MARKER in text
    allow_dates = ALLOW_DATES_MARKER in text
    is_markdown = path.lower().endswith(".md")
    for number, line in enumerate(text.splitlines(), start=1):
        for match in NINE_DIGITS.finditer(line):
            if is_valid_orgnr(match.group(1)):
                findings.append(Finding(path, number, "valid-organisation-number", line))
                break
        if not allow_person and PERSON_FIELDS.search(line):
            findings.append(Finding(path, number, "person-field-name", line))
        if not allow_dates and DATES.search(line):
            findings.append(Finding(path, number, "calendar-date", line))
        if not is_self and ATTRIBUTION.search(line):
            findings.append(Finding(path, number, "tool-attribution", line))
        if is_markdown and YEARS.search(line) and not DATES.search(line):
            findings.append(Finding(path, number, "year-for-manual-review", line, "warn"))
    return findings


def scan_paths(paths: list[Path], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        findings.extend(scan_text(text, rel, is_self=path.resolve() == SELF))
    return findings


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths = [Path(a).resolve() for a in argv] if argv else repo_files(ROOT)
    findings = scan_paths(paths, ROOT)
    failures = [f for f in findings if f.severity == "fail"]
    for finding in findings:
        print(finding)
    print(
        f"privacy scan: {len(paths)} files, {len(failures)} failures, "
        f"{len(findings) - len(failures)} warnings"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
