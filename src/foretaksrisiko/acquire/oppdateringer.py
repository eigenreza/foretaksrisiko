"""Change events between snapshots, reduced to counts per company."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator

import pyarrow as pa

from foretaksrisiko.acquire.http import PoliteClient
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter
from foretaksrisiko.config import BrregConfig

log = logging.getLogger(__name__)

PAGE_SIZE = 10_000

UPDATES_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("endringstype", pa.string()),
        ("n_events", pa.int32()),
        ("first_dato", pa.string()),
        ("last_dato", pa.string()),
    ]
)

ROLE_UPDATES_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("n_events", pa.int32()),
        ("first_time", pa.string()),
        ("last_time", pa.string()),
    ]
)


def iter_unit_updates(
    client: PoliteClient,
    path: str,
    embedded_key: str,
    since: str,
    until: str | None = None,
    page_size: int | None = None,
) -> Iterator[dict]:
    """Walk the unit or sub-unit update feed with the oppdateringsid cursor."""
    page_size = page_size or PAGE_SIZE
    cursor: int | None = None
    while True:
        params: dict = {"dato": since, "size": page_size}
        if until:
            params["updatedBefore"] = until
        if cursor is not None:
            params["oppdateringsid"] = cursor
        response = client.get(path, params=params)
        response.raise_for_status()
        events = (response.json().get("_embedded") or {}).get(embedded_key) or []
        if not events:
            return
        yield from events
        cursor = int(events[-1]["oppdateringsid"]) + 1
        if len(events) < page_size:
            return


def iter_role_updates(
    client: PoliteClient, path: str, since: str, page_size: int | None = None
) -> Iterator[dict]:
    """Walk the role update feed (CloudEvents) with afterTime, then afterId."""
    page_size = page_size or PAGE_SIZE
    after_id: int | None = None
    while True:
        params: dict = {"size": page_size}
        if after_id is None:
            params["afterTime"] = since
        else:
            params["afterId"] = after_id
        response = client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload = (payload.get("_embedded") or {}).get("rolleoppdateringer") or []
        if not payload:
            return
        yield from payload
        after_id = int(payload[-1]["id"])
        if len(payload) < page_size:
            return


def acquire_updates(
    client: PoliteClient,
    cfg: BrregConfig,
    landing: Landing,
    since: str,
    kept_orgnr: set[str],
    kept_underenheter: set[str] | None = None,
    until: str | None = None,
) -> dict:
    """Aggregate events since ``since`` to counts per company and write three tables."""
    summary: dict = {"since": since, "until": until}

    def reduce_units(path: str, key: str, keep: set[str], table: str) -> None:
        agg: dict[tuple[str, str], list] = {}
        total = 0
        for event in iter_unit_updates(client, path, key, since, until):
            total += 1
            orgnr = str(event.get("organisasjonsnummer"))
            if orgnr not in keep:
                continue
            k = (orgnr, str(event.get("endringstype")))
            dato = str(event.get("dato"))
            if k not in agg:
                agg[k] = [0, dato, dato]
            agg[k][0] += 1
            agg[k][1] = min(agg[k][1], dato)
            agg[k][2] = max(agg[k][2], dato)
        with ParquetBatchWriter(landing.table_dir(table), UPDATES_SCHEMA) as w:
            for (orgnr, typ), (n, first, last) in sorted(agg.items()):
                w.write(
                    {
                        "organisasjonsnummer": orgnr,
                        "endringstype": typ,
                        "n_events": n,
                        "first_dato": first,
                        "last_dato": last,
                    }
                )
        types = Counter(typ for (_, typ) in agg)
        summary[table] = {"events_total": total, "rows": len(agg), "by_type": dict(types)}

    reduce_units(
        cfg.oppdateringer_enheter_path, "oppdaterteEnheter", kept_orgnr, "oppdateringer_enheter"
    )
    if kept_underenheter is not None:
        reduce_units(
            cfg.oppdateringer_underenheter_path,
            "oppdaterteUnderenheter",
            kept_underenheter,
            "oppdateringer_underenheter",
        )

    role_agg: dict[str, list] = {}
    total = 0
    for event in iter_role_updates(client, cfg.oppdateringer_roller_path, since):
        total += 1
        orgnr = str((event.get("data") or {}).get("organisasjonsnummer"))
        if orgnr not in kept_orgnr:
            continue
        time = str(event.get("time"))
        if orgnr not in role_agg:
            role_agg[orgnr] = [0, time, time]
        role_agg[orgnr][0] += 1
        role_agg[orgnr][1] = min(role_agg[orgnr][1], time)
        role_agg[orgnr][2] = max(role_agg[orgnr][2], time)
    with ParquetBatchWriter(landing.table_dir("oppdateringer_roller"), ROLE_UPDATES_SCHEMA) as w:
        for orgnr, (n, first, last) in sorted(role_agg.items()):
            w.write(
                {
                    "organisasjonsnummer": orgnr,
                    "n_events": n,
                    "first_time": first,
                    "last_time": last,
                }
            )
    summary["oppdateringer_roller"] = {"events_total": total, "rows": len(role_agg)}
    log.info("updates done: %s", summary)
    landing.update_manifest("oppdateringer", summary)
    return summary
