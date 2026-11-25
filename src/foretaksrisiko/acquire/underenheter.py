"""Sub-units (underenheter): keep only those whose parent is a kept AS or ASA."""

from __future__ import annotations

import logging
from collections import Counter

import pyarrow as pa

from foretaksrisiko.acquire.fields import code, dig, to_bool, to_date, to_int
from foretaksrisiko.acquire.jsonstream import StreamOpener, iter_items
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter

log = logging.getLogger(__name__)

UNDERENHET_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("overordnet_enhet", pa.string()),
        ("organisasjonsform", pa.string()),
        ("naeringskode1", pa.string()),
        ("beliggenhetsadresse_kommunenummer", pa.string()),
        ("beliggenhetsadresse_postnummer", pa.string()),
        ("beliggenhetsadresse_landkode", pa.string()),
        ("antall_ansatte", pa.int32()),
        ("har_registrert_antall_ansatte", pa.bool_()),
        ("registrert_i_mvaregisteret", pa.bool_()),
        ("registreringsdato_enhetsregisteret", pa.date32()),
        ("oppstartsdato", pa.date32()),
        ("nedleggelsesdato", pa.date32()),
        ("dato_eierskifte", pa.date32()),
    ]
)


def project_underenhet(raw: dict) -> dict:
    return {
        "organisasjonsnummer": str(raw.get("organisasjonsnummer")),
        "overordnet_enhet": str(raw.get("overordnetEnhet")),
        "organisasjonsform": code(raw.get("organisasjonsform")),
        "naeringskode1": code(raw.get("naeringskode1")),
        "beliggenhetsadresse_kommunenummer": dig(raw, ("beliggenhetsadresse", "kommunenummer")),
        "beliggenhetsadresse_postnummer": dig(raw, ("beliggenhetsadresse", "postnummer")),
        "beliggenhetsadresse_landkode": dig(raw, ("beliggenhetsadresse", "landkode")),
        "antall_ansatte": to_int(raw.get("antallAnsatte")),
        "har_registrert_antall_ansatte": to_bool(raw.get("harRegistrertAntallAnsatte")),
        "registrert_i_mvaregisteret": to_bool(raw.get("registrertIMvaregisteret")),
        "registreringsdato_enhetsregisteret": to_date(raw.get("registreringsdatoEnhetsregisteret")),
        "oppstartsdato": to_date(raw.get("oppstartsdato")),
        "nedleggelsesdato": to_date(raw.get("nedleggelsesdato")),
        "dato_eierskifte": to_date(raw.get("datoEierskifte")),
    }


def acquire_underenheter(
    open_stream: StreamOpener,
    landing: Landing,
    kept_orgnr: set[str],
    rows_per_file: int = 50_000,
) -> dict:
    counts: Counter[str] = Counter()
    with (
        open_stream() as stream,
        ParquetBatchWriter(
            landing.table_dir("underenheter"), UNDERENHET_SCHEMA, rows_per_file
        ) as writer,
    ):
        for raw in iter_items(stream):
            counts["total"] += 1
            if raw.get("respons_klasse") in ("SlettetUnderEnhet", "GoneUnderenhet") or raw.get(
                "slettedato"
            ):
                counts["dropped_deleted"] += 1
                continue
            parent = raw.get("overordnetEnhet")
            if parent is None or str(parent) not in kept_orgnr:
                counts["dropped_parent_not_kept"] += 1
                continue
            writer.write(project_underenhet(raw))
            counts["kept"] += 1
    summary = {
        "rows_total": counts["total"],
        "rows_kept": counts["kept"],
        "rows_dropped_parent_not_kept": counts["dropped_parent_not_kept"],
        "rows_dropped_deleted": counts["dropped_deleted"],
        "files": writer.files_written,
    }
    log.info("underenheter done: %s", summary)
    landing.update_manifest("underenheter", summary)
    return summary
