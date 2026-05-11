"""Style scan for public files: no em dash, no en dash as a sentence dash, no banned words.

style-scan: allow-banned-words

Usage: python scripts/style_scan.py [path ...]
Without paths, every tracked or untracked-but-not-ignored text file in the repository is scanned.
Exit code 1 when a finding exists.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
EN_DASH_SENTENCE = re.compile(rf"(?<!\d){EN_DASH}|{EN_DASH}(?!\d)")
BANNED_WORDS = re.compile(
    r"\b(suspicious|fraud\w*|crimes?|criminal\w*|mistenkelig\w*|svindel\w*|"
    r"kriminalitet\w*|kriminell\w*)\b",
    re.IGNORECASE,
)
ALLOW_BANNED_MARKER = "style-scan: allow-banned-words"


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.snippet.strip()[:120]}"


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


def scan_text(text: str, path: str) -> list[Finding]:
    findings: list[Finding] = []
    allow_banned = ALLOW_BANNED_MARKER in text
    for number, line in enumerate(text.splitlines(), start=1):
        if EM_DASH in line:
            findings.append(Finding(path, number, "em-dash", line))
        if EN_DASH_SENTENCE.search(line):
            findings.append(Finding(path, number, "en-dash-as-sentence-dash", line))
        if not allow_banned and BANNED_WORDS.search(line):
            findings.append(Finding(path, number, "banned-word", line))
    return findings


def scan_paths(paths: list[Path], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(
            scan_text(text, str(path.relative_to(root)) if path.is_relative_to(root) else str(path))
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parents[1]
    paths = [Path(a).resolve() for a in argv] if argv else repo_files(root)
    findings = scan_paths(paths, root)
    for finding in findings:
        print(finding)
    print(f"style scan: {len(paths)} files, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
