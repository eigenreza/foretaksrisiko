"""Roles: reduce every company's roles to counts and flags while streaming (rules L3 to L5).

privacy-scan: allow-person-fields

This module is the only place that reads person fields (navn, fodselsdato, erDoed). They are used
for one company at a time, inside ``reduce_roles``, and only to count persons and to decide whether
the CEO is also the board chair. Nothing person-level is returned, written, logged or cached.
The bulk file is read from the network stream and is never written to disk.
"""

from __future__ import annotations

import logging
from collections import Counter

import pyarrow as pa

from foretaksrisiko.acquire.fields import code, to_date
from foretaksrisiko.acquire.jsonstream import StreamOpener, iter_items
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter

log = logging.getLogger(__name__)

BOARD_TYPES = frozenset({"LEDE", "NEST", "MEDL"})
GROUPS_WITH_DATES = ("STYR", "DAGL", "REVI", "REGN", "KONT")

ROLLER_COUNTS_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("n_role_groups", pa.int32()),
        ("n_roles_total", pa.int32()),
        ("n_roles_active", pa.int32()),
        ("n_deregistered_roles", pa.int32()),
        ("board_size", pa.int32()),
        ("n_board_chair", pa.int32()),
        ("n_board_deputy_chair", pa.int32()),
        ("n_board_members", pa.int32()),
        ("n_deputy_members", pa.int32()),
        ("n_observers", pa.int32()),
        ("n_ceo", pa.int32()),
        ("has_ceo", pa.bool_()),
        ("has_chair", pa.bool_()),
        ("ceo_is_chair", pa.bool_()),
        ("n_auditor", pa.int32()),
        ("has_auditor", pa.bool_()),
        ("n_accountant", pa.int32()),
        ("has_accountant", pa.bool_()),
        ("n_contact_person", pa.int32()),
        ("has_contact_person", pa.bool_()),
        ("n_roles_valgt_av", pa.int32()),
        ("n_person_roleholders", pa.int32()),
        ("n_distinct_persons", pa.int32()),
        ("n_deceased_roleholders", pa.int32()),
        ("n_org_roleholders", pa.int32()),
        ("n_org_roleholders_in_scope", pa.int32()),
        ("n_bostyrer", pa.int32()),
        ("styr_sist_endret", pa.date32()),
        ("dagl_sist_endret", pa.date32()),
        ("revi_sist_endret", pa.date32()),
        ("regn_sist_endret", pa.date32()),
        ("kont_sist_endret", pa.date32()),
    ]
)

# Organisation-to-organisation links, both ends inside the kept AS and ASA population (rule L4).
ROLLER_LINKS_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("rolleholder_organisasjonsnummer", pa.string()),
        ("rolleholder_organisasjonsform", pa.string()),
        ("rollegruppe", pa.string()),
        ("rolletype", pa.string()),
        ("godkjenningsstatus", pa.string()),
        ("rolleholder_er_slettet", pa.bool_()),
        ("avregistrert", pa.bool_()),
    ]
)

COUNT_COLUMNS = [
    name
    for name, field in zip(ROLLER_COUNTS_SCHEMA.names, ROLLER_COUNTS_SCHEMA, strict=True)
    if field.type == pa.int32()
]


def _person_key(person: dict) -> tuple:
    """In-memory identity of one person within one company, discarded after the company."""
    navn = person.get("navn") if isinstance(person.get("navn"), dict) else {}
    return (navn.get("fornavn"), navn.get("etternavn"), person.get("fodselsdato"))


def reduce_roles(entry: dict, kept_orgnr: set[str]) -> tuple[dict, list[dict]]:
    """Reduce one company's role record to a counts row and organisation links."""
    orgnr = str(entry.get("organisasjonsnummer"))
    counts: Counter[str] = Counter()
    row: dict = {name: 0 for name in COUNT_COLUMNS}
    row["organisasjonsnummer"] = orgnr
    for group in GROUPS_WITH_DATES:
        row[f"{group.lower()}_sist_endret"] = None
    links: list[dict] = []

    persons: set[tuple] = set()
    ceo_persons: set[tuple] = set()
    chair_persons: set[tuple] = set()

    groups = entry.get("rollegrupper") or []
    counts["n_role_groups"] = len(groups)
    for group in groups:
        group_code = code(group.get("type"))
        if group_code in GROUPS_WITH_DATES:
            row[f"{group_code.lower()}_sist_endret"] = to_date(group.get("sistEndret"))
        for role in group.get("roller") or []:
            role_type = code(role.get("type"))
            deregistered = role.get("avregistrert") is True
            counts["n_roles_total"] += 1
            if deregistered:
                counts["n_deregistered_roles"] += 1
            else:
                counts["n_roles_active"] += 1

            holder_org = role.get("enhet") if isinstance(role.get("enhet"), dict) else None
            if holder_org is not None:
                counts["n_org_roleholders"] += 1
                holder_orgnr = holder_org.get("organisasjonsnummer")
                holder_form = code(holder_org.get("organisasjonsform"))
                if holder_orgnr is not None and str(holder_orgnr) in kept_orgnr:
                    counts["n_org_roleholders_in_scope"] += 1
                    links.append(
                        {
                            "organisasjonsnummer": orgnr,
                            "rolleholder_organisasjonsnummer": str(holder_orgnr),
                            "rolleholder_organisasjonsform": holder_form,
                            "rollegruppe": group_code,
                            "rolletype": role_type,
                            "godkjenningsstatus": holder_org.get("godkjenningsstatus"),
                            "rolleholder_er_slettet": holder_org.get("erSlettet") is True,
                            "avregistrert": deregistered,
                        }
                    )
            elif isinstance(role.get("bostyrer"), dict):
                counts["n_bostyrer"] += 1

            if deregistered:
                continue

            person = role.get("person") if isinstance(role.get("person"), dict) else None
            if person is not None:
                key = _person_key(person)
                persons.add(key)
                counts["n_person_roleholders"] += 1
                if person.get("erDoed") is True:
                    counts["n_deceased_roleholders"] += 1
                if role_type == "DAGL":
                    ceo_persons.add(key)
                if role_type == "LEDE":
                    chair_persons.add(key)

            if role.get("valgtAv"):
                counts["n_roles_valgt_av"] += 1
            if role_type in BOARD_TYPES:
                counts["board_size"] += 1
            if role_type == "LEDE":
                counts["n_board_chair"] += 1
            elif role_type == "NEST":
                counts["n_board_deputy_chair"] += 1
            elif role_type == "MEDL":
                counts["n_board_members"] += 1
            elif role_type == "VARA":
                counts["n_deputy_members"] += 1
            elif role_type == "OBS":
                counts["n_observers"] += 1
            elif role_type == "DAGL":
                counts["n_ceo"] += 1
            elif role_type == "REVI":
                counts["n_auditor"] += 1
            elif role_type == "REGN":
                counts["n_accountant"] += 1
            elif role_type == "KONT":
                counts["n_contact_person"] += 1

    row.update({name: counts[name] for name in COUNT_COLUMNS if name != "n_distinct_persons"})
    row["n_distinct_persons"] = len(persons)
    row["has_ceo"] = counts["n_ceo"] > 0
    row["has_chair"] = counts["n_board_chair"] > 0
    row["ceo_is_chair"] = bool(ceo_persons & chair_persons)
    row["has_auditor"] = counts["n_auditor"] > 0
    row["has_accountant"] = counts["n_accountant"] > 0
    row["has_contact_person"] = counts["n_contact_person"] > 0
    return row, links


def acquire_roller(
    open_stream: StreamOpener,
    landing: Landing,
    kept_orgnr: set[str],
    rows_per_file: int = 50_000,
) -> dict:
    """Stream the roles bulk file; write counts and links for kept companies only."""
    counts: Counter[str] = Counter()
    with (
        open_stream() as stream,
        ParquetBatchWriter(
            landing.table_dir("roller_counts"), ROLLER_COUNTS_SCHEMA, rows_per_file
        ) as writer,
        ParquetBatchWriter(
            landing.table_dir("roller_links"), ROLLER_LINKS_SCHEMA, rows_per_file
        ) as link_writer,
    ):
        for entry in iter_items(stream):
            counts["entries_total"] += 1
            orgnr = entry.get("organisasjonsnummer")
            if orgnr is None or str(orgnr) not in kept_orgnr:
                counts["entries_skipped"] += 1
                continue
            row, links = reduce_roles(entry, kept_orgnr)
            writer.write(row)
            for link in links:
                link_writer.write(link)
            counts["entries_kept"] += 1
            counts["links"] += len(links)
            if counts["entries_total"] % 200_000 == 0:
                log.info(
                    "roller: %d read, %d kept", counts["entries_total"], counts["entries_kept"]
                )
    summary = {
        "entries_total": counts["entries_total"],
        "entries_kept": counts["entries_kept"],
        "entries_skipped": counts["entries_skipped"],
        "links": counts["links"],
        "files": writer.files_written,
        "raw_file_written_to_disk": False,
    }
    log.info("roller done: %s", summary)
    landing.update_manifest("roller", summary)
    return summary
