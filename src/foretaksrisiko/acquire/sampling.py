"""Stratified development sample by industry section and county."""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from collections.abc import Callable

import pyarrow as pa

from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter, read_table

log = logging.getLogger(__name__)

UNKNOWN = "X"

SAMPLE_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("stratum_section", pa.string()),
        ("stratum_county", pa.string()),
    ]
)


def build_section_lookup(items: list[dict]) -> Callable[[str | None], str]:
    """Map an industry code to its section letter using the Klass parent chain."""
    parent = {str(it["code"]): it.get("parent_code") for it in items}
    level = {str(it["code"]): int(it["level"]) for it in items}

    def climb(start: str) -> str | None:
        current: str | None = start
        seen = 0
        while current is not None and current in level and seen < 10:
            if level[current] == 1:
                return current
            current = parent.get(current)
            seen += 1
        return None

    def section(code: str | None) -> str:
        if not code:
            return UNKNOWN
        text = str(code)
        for candidate in (text, text[:5], text[:4], text[:2]):
            found = climb(candidate)
            if found is not None:
                return found
        return UNKNOWN

    return section


def county_of(kommunenummer: str | None) -> str:
    if kommunenummer and len(str(kommunenummer)) == 4 and str(kommunenummer).isdigit():
        return str(kommunenummer)[:2]
    return "99"


def allocate(sizes: dict[tuple, int], total: int) -> dict[tuple, int]:
    """Proportional allocation with largest remainders, capped at each stratum's size."""
    population = sum(sizes.values())
    if population == 0 or total <= 0:
        return {key: 0 for key in sizes}
    total = min(total, population)
    exact = {key: total * n / population for key, n in sizes.items()}
    allocation = {key: min(int(v), sizes[key]) for key, v in exact.items()}
    remaining = total - sum(allocation.values())
    by_remainder = sorted(exact, key=lambda k: (exact[k] - int(exact[k]), str(k)), reverse=True)
    for key in by_remainder:
        if remaining <= 0:
            break
        if allocation[key] < sizes[key]:
            allocation[key] += 1
            remaining -= 1
    return allocation


def stratified_sample(units: list[tuple[str, str, str]], size: int, seed: int) -> list[dict]:
    """Sample (orgnr, section, county) tuples proportionally within section x county strata."""
    strata: dict[tuple, list[str]] = defaultdict(list)
    for orgnr, section, county in units:
        strata[(section, county)].append(orgnr)
    allocation = allocate({k: len(v) for k, v in strata.items()}, size)
    rng = random.Random(seed)
    sample: list[dict] = []
    for key in sorted(strata):
        members = sorted(strata[key])
        chosen = rng.sample(members, allocation[key]) if allocation[key] else []
        sample.extend(
            {"organisasjonsnummer": o, "stratum_section": key[0], "stratum_county": key[1]}
            for o in sorted(chosen)
        )
    return sample


def build_sample(landing: Landing, size: int, seed: int) -> dict:
    """Read the kept units and the SN2025 code list; write the ``sample`` table."""
    sn_items = read_table(landing.root / "klass" / "sn2025").to_pylist()
    section_of = build_section_lookup(sn_items)
    table = read_table(
        landing.root / "enheter",
        columns=["organisasjonsnummer", "naeringskode1", "forretningsadresse_kommunenummer"],
    )
    units = [
        (
            row["organisasjonsnummer"],
            section_of(row["naeringskode1"]),
            county_of(row["forretningsadresse_kommunenummer"]),
        )
        for row in table.to_pylist()
    ]
    sample = stratified_sample(units, size, seed)
    with ParquetBatchWriter(landing.table_dir("sample"), SAMPLE_SCHEMA, rows_per_file=100_000) as w:
        for row in sample:
            w.write(row)
    sections = sorted({s for _, s, _ in units})
    summary = {
        "population": len(units),
        "sample_size": len(sample),
        "seed": seed,
        "n_strata": len({(s, c) for _, s, c in units}),
        "n_sections": len(sections),
        "unknown_section_in_population": sum(1 for _, s, _ in units if s == UNKNOWN),
    }
    log.info("sample done: %s", summary)
    landing.update_manifest("sample", summary)
    return summary


def copy_sample(landing: Landing, previous: Landing, kept: set[str]) -> dict:
    """Carry the development sample forward: the earlier sample's companies still in scope.

    Later snapshots keep the same sampled companies rather than drawing afresh, so training
    frames across snapshots describe the same companies.
    """
    earlier = read_table(previous.root / "sample").to_pylist()
    rows = [row for row in earlier if row["organisasjonsnummer"] in kept]
    with ParquetBatchWriter(landing.table_dir("sample"), SAMPLE_SCHEMA, rows_per_file=100_000) as w:
        for row in rows:
            w.write(row)
    summary = {
        "copied_from_snapshot_id": previous.snapshot_id,
        "sample_size": len(rows),
        "left_population": len(earlier) - len(rows),
    }
    log.info("sample copied: %s", summary)
    landing.update_manifest("sample", summary)
    return summary
