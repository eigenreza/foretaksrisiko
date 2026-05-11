"""Event history from the Enhetsregisteret update feeds, reduced to company-level rows.

Each unit event may carry a JSON patch of the changed fields. Only the names of changed fields
are kept, plus the new values of a few status fields (booleans, dates, a year). No other values
are stored: names, addresses and free text never leave memory. Events for units outside the kept
population are reduced to monthly counts and nothing else.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime

import pyarrow as pa

from foretaksrisiko.acquire.fields import to_date, to_int
from foretaksrisiko.acquire.http import PoliteClient
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter
from foretaksrisiko.acquire.oppdateringer import iter_role_updates
from foretaksrisiko.config import BrregConfig

log = logging.getLogger(__name__)

PAGE_SIZE = 10_000

BOOL_STATUS_PATHS = {
    "/konkurs": "konkurs",
    "/underAvvikling": "under_avvikling",
    "/underTvangsavviklingEllerTvangsopplosning": "under_tvang",
    "/registrertIMvaregisteret": "registrert_i_mvaregisteret",
    "/registrertIForetaksregisteret": "registrert_i_foretaksregisteret",
    "/erIKonsern": "er_i_konsern",
}
DATE_STATUS_PATHS = {
    "/konkursdato": "konkursdato",
    "/underAvviklingDato": "under_avvikling_dato",
    "/tvangsavvikletPgaManglendeSlettingDato": "tvang_dato",
    "/tvangsopplostPgaManglendeDagligLederDato": "tvang_dato",
    "/tvangsopplostPgaManglendeRevisorDato": "tvang_dato",
    "/tvangsopplostPgaManglendeRegnskapDato": "tvang_dato",
    "/tvangsopplostPgaMangelfulltStyreDato": "tvang_dato",
    "/fravalgRevisjonDato": "fravalg_revisjon_dato",
}
YEAR_STATUS_PATHS = {"/sisteInnsendteAarsregnskap": "siste_innsendte_aarsregnskap"}

EVENTS_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("oppdateringsid", pa.int64()),
        ("dato", pa.string()),
        ("endringstype", pa.string()),
        ("n_changes", pa.int32()),
        ("changed_fields", pa.string()),
        ("konkurs", pa.bool_()),
        ("under_avvikling", pa.bool_()),
        ("under_tvang", pa.bool_()),
        ("registrert_i_mvaregisteret", pa.bool_()),
        ("registrert_i_foretaksregisteret", pa.bool_()),
        ("er_i_konsern", pa.bool_()),
        ("konkursdato", pa.date32()),
        ("under_avvikling_dato", pa.date32()),
        ("tvang_dato", pa.date32()),
        ("fravalg_revisjon_dato", pa.date32()),
        ("siste_innsendte_aarsregnskap", pa.int32()),
    ]
)

MONTHLY_SCHEMA = pa.schema(
    [
        ("month", pa.string()),
        ("endringstype", pa.string()),
        ("field", pa.string()),
        ("in_population", pa.bool_()),
        ("n_events", pa.int64()),
    ]
)

ROLE_EVENTS_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("event_id", pa.int64()),
        ("time", pa.string()),
    ]
)


FEED_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"


def feed_timestamp(iso: str) -> str:
    """Normalise an ISO-8601 timestamp to the update feed's format: UTC, milliseconds, Z suffix.

    The feed rejects other spellings, such as a +00:00 offset or seconds without a fraction.
    """
    text = iso.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime(FEED_TIME_FORMAT)


def iter_unit_events(
    client: PoliteClient,
    path: str,
    since: str,
    until: str | None = None,
    page_size: int = PAGE_SIZE,
) -> Iterator[dict]:
    """Walk the unit update feed with change details, using the oppdateringsid cursor."""
    cursor: int | None = None
    while True:
        params: dict = {"dato": since, "size": page_size, "includeChanges": "true"}
        if until:
            params["updatedBefore"] = until
        if cursor is not None:
            params["oppdateringsid"] = cursor
        response = client.get(path, params=params)
        response.raise_for_status()
        events = (response.json().get("_embedded") or {}).get("oppdaterteEnheter") or []
        if not events:
            return
        yield from events
        cursor = int(events[-1]["oppdateringsid"]) + 1
        if len(events) < page_size:
            return


def _top_level(path: str) -> str:
    parts = path.split("/")
    return parts[1] if len(parts) > 1 else path


def reduce_event(event: dict) -> dict:
    """One event to one row: field names, and new values of status fields only."""
    changes = event.get("endringer") or []
    fields: set[str] = set()
    row: dict = {
        "organisasjonsnummer": str(event.get("organisasjonsnummer")),
        "oppdateringsid": to_int(event.get("oppdateringsid")),
        "dato": str(event.get("dato")),
        "endringstype": event.get("endringstype"),
        "n_changes": len(changes),
    }
    for name in EVENTS_SCHEMA.names[6:]:
        row[name] = None
    tvang_dates = []
    for change in changes:
        path = str(change.get("path", ""))
        fields.add(_top_level(path))
        value = change.get("value")
        if change.get("op") == "remove":
            continue
        if path in BOOL_STATUS_PATHS and isinstance(value, bool):
            row[BOOL_STATUS_PATHS[path]] = value
        elif path in DATE_STATUS_PATHS:
            parsed = to_date(value)
            if DATE_STATUS_PATHS[path] == "tvang_dato":
                if parsed:
                    tvang_dates.append(parsed)
            else:
                row[DATE_STATUS_PATHS[path]] = parsed
        elif path in YEAR_STATUS_PATHS:
            row[YEAR_STATUS_PATHS[path]] = to_int(value)
    if tvang_dates:
        row["tvang_dato"] = min(tvang_dates)
    row["changed_fields"] = ";".join(sorted(fields)) if fields else None
    return row


def acquire_history(
    client: PoliteClient,
    cfg: BrregConfig,
    landing: Landing,
    since: str,
    kept_orgnr: set[str],
    until: str | None = None,
    include_roles: bool = True,
) -> dict:
    """Fetch unit and role events since ``since`` and write reduced tables for the population."""
    counts: Counter[str] = Counter()
    monthly: Counter[tuple[str, str, str, bool]] = Counter()
    with ParquetBatchWriter(landing.table_dir("events_enheter"), EVENTS_SCHEMA) as writer:
        for event in iter_unit_events(client, cfg.oppdateringer_enheter_path, since, until):
            counts["events_total"] += 1
            orgnr = str(event.get("organisasjonsnummer"))
            in_population = orgnr in kept_orgnr
            month = str(event.get("dato"))[:7]
            typ = str(event.get("endringstype"))
            monthly[(month, typ, "*", in_population)] += 1
            for change in event.get("endringer") or []:
                path = str(change.get("path", ""))
                if path in BOOL_STATUS_PATHS or path in DATE_STATUS_PATHS:
                    monthly[(month, typ, path.lstrip("/"), in_population)] += 1
            if not in_population:
                continue
            writer.write(reduce_event(event))
            counts["events_population"] += 1
            if counts["events_total"] % 500_000 == 0:
                log.info(
                    "history: %d events read, %d in population",
                    counts["events_total"],
                    counts["events_population"],
                )
    with ParquetBatchWriter(
        landing.table_dir("events_monthly_all"), MONTHLY_SCHEMA
    ) as monthly_writer:
        for (month, typ, field, in_population), n in sorted(monthly.items()):
            monthly_writer.write(
                {
                    "month": month,
                    "endringstype": typ,
                    "field": field,
                    "in_population": in_population,
                    "n_events": n,
                }
            )
    if include_roles:
        with ParquetBatchWriter(
            landing.table_dir("events_roller"), ROLE_EVENTS_SCHEMA
        ) as role_writer:
            for event in iter_role_updates(client, cfg.oppdateringer_roller_path, since):
                counts["role_events_total"] += 1
                orgnr = str((event.get("data") or {}).get("organisasjonsnummer"))
                if orgnr not in kept_orgnr:
                    continue
                role_writer.write(
                    {
                        "organisasjonsnummer": orgnr,
                        "event_id": to_int(event.get("id")),
                        "time": str(event.get("time")),
                    }
                )
                counts["role_events_population"] += 1
    summary = {"since": since, "until": until, **counts}
    log.info("history done: %s", summary)
    landing.update_manifest("history", summary)
    return summary
