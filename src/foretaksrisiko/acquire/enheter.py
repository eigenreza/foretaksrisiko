"""Main units (enheter): stream the bulk file, keep AS and ASA, drop every other form in memory.

Rules L1 and L2: units of any other organisation form, and units registered in
Frivillighetsregisteret, are never written to disk. Only counts of what was dropped are kept.
"""

from __future__ import annotations

import logging
from collections import Counter

import pyarrow as pa

from foretaksrisiko.acquire.fields import (
    code,
    count,
    dig,
    join_lines,
    non_empty,
    to_bool,
    to_date,
    to_float,
    to_int,
    to_year,
)
from foretaksrisiko.acquire.jsonstream import StreamOpener, iter_items
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter
from foretaksrisiko.config import ScopeConfig

log = logging.getLogger(__name__)

DROP_DELETED = "deleted"
DROP_FORM = "form"
DROP_FRIVILLIG = "frivillighetsregisteret"

ENHET_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("organisasjonsform", pa.string()),
        ("registrert_i_frivillighetsregisteret", pa.bool_()),
        ("registreringsdato_enhetsregisteret", pa.date32()),
        ("stiftelsesdato", pa.date32()),
        ("vedtektsdato", pa.date32()),
        ("kapital_belop", pa.float64()),
        ("kapital_antall_aksjer", pa.float64()),
        ("kapital_type", pa.string()),
        ("kapital_valuta", pa.string()),
        ("kapital_innbetalt", pa.float64()),
        ("kapital_fullt_innbetalt", pa.bool_()),
        ("kapital_innfort_dato", pa.date32()),
        ("antall_ansatte", pa.int32()),
        ("har_registrert_antall_ansatte", pa.bool_()),
        ("registreringsdato_antall_ansatte_nav", pa.date32()),
        ("naeringskode1", pa.string()),
        ("naeringskode2", pa.string()),
        ("naeringskode3", pa.string()),
        ("hjelpeenhetskode", pa.string()),
        ("institusjonell_sektorkode", pa.string()),
        ("forretningsadresse_kommunenummer", pa.string()),
        ("forretningsadresse_postnummer", pa.string()),
        ("forretningsadresse_landkode", pa.string()),
        ("postadresse_kommunenummer", pa.string()),
        ("registrert_i_mvaregisteret", pa.bool_()),
        ("registreringsdato_mvaregisteret", pa.date32()),
        ("antall_frivillig_mva_beskrivelser", pa.int32()),
        ("registrert_i_foretaksregisteret", pa.bool_()),
        ("registreringsdato_foretaksregisteret", pa.date32()),
        ("registrert_i_stiftelsesregisteret", pa.bool_()),
        ("registrert_i_partiregisteret", pa.bool_()),
        ("konkurs", pa.bool_()),
        ("konkursdato", pa.date32()),
        ("under_avvikling", pa.bool_()),
        ("under_avvikling_dato", pa.date32()),
        ("under_tvangsavvikling_eller_tvangsopplosning", pa.bool_()),
        ("tvangsavviklet_pga_manglende_sletting_dato", pa.date32()),
        ("tvangsopplost_pga_manglende_daglig_leder_dato", pa.date32()),
        ("tvangsopplost_pga_manglende_revisor_dato", pa.date32()),
        ("tvangsopplost_pga_manglende_regnskap_dato", pa.date32()),
        ("tvangsopplost_pga_mangelfullt_styre_dato", pa.date32()),
        ("under_rekonstruksjonsforhandling_dato", pa.date32()),
        ("under_utenlandsk_insolvensbehandling_dato", pa.date32()),
        ("fravalg_revisjon_dato", pa.date32()),
        ("fravalg_revisjon_beslutnings_dato", pa.date32()),
        ("siste_innsendte_aarsregnskap", pa.int32()),
        ("er_i_konsern", pa.bool_()),
        ("maalform", pa.string()),
        ("antall_historiske_navn", pa.int32()),
        ("antall_paategninger", pa.int32()),
        ("paategning_infotyper", pa.string()),
        ("har_hjemmeside", pa.bool_()),
        ("har_epostadresse", pa.bool_()),
        ("har_telefon", pa.bool_()),
    ]
)

# Register free text, kept only in the local landing zone. Never published, never uploaded as is.
ENHET_TEXT_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("vedtektsfestet_formaal", pa.string()),
        ("aktivitet", pa.string()),
    ]
)


def drop_reason(raw: dict, scope: ScopeConfig) -> str | None:
    """None when the unit is kept, otherwise a short reason used only for counting."""
    if raw.get("respons_klasse") in ("SlettetEnhet", "GoneEnhet") or raw.get("slettedato"):
        return DROP_DELETED
    form = code(raw.get("organisasjonsform"))
    if form not in scope.organisasjonsformer:
        return DROP_FORM
    if scope.drop_frivillighetsregisteret and raw.get("registrertIFrivillighetsregisteret") is True:
        return DROP_FRIVILLIG
    return None


def project_enhet(raw: dict) -> dict:
    kapital = raw.get("kapital") or {}
    paategninger = raw.get("paategninger") or []
    infotyper = sorted({str(p.get("infotype")) for p in paategninger if isinstance(p, dict)})
    return {
        "organisasjonsnummer": str(raw.get("organisasjonsnummer")),
        "organisasjonsform": code(raw.get("organisasjonsform")),
        "registrert_i_frivillighetsregisteret": to_bool(
            raw.get("registrertIFrivillighetsregisteret")
        ),
        "registreringsdato_enhetsregisteret": to_date(raw.get("registreringsdatoEnhetsregisteret")),
        "stiftelsesdato": to_date(raw.get("stiftelsesdato")),
        "vedtektsdato": to_date(raw.get("vedtektsdato")),
        "kapital_belop": to_float(kapital.get("belop")),
        "kapital_antall_aksjer": to_float(kapital.get("antallAksjer")),
        "kapital_type": kapital.get("type"),
        "kapital_valuta": kapital.get("valuta"),
        "kapital_innbetalt": to_float(kapital.get("innbetalt")),
        "kapital_fullt_innbetalt": to_bool(kapital.get("fulltInnbetalt")),
        "kapital_innfort_dato": to_date(kapital.get("innfortDato")),
        "antall_ansatte": to_int(raw.get("antallAnsatte")),
        "har_registrert_antall_ansatte": to_bool(raw.get("harRegistrertAntallAnsatte")),
        "registreringsdato_antall_ansatte_nav": to_date(
            raw.get("registreringsdatoAntallAnsatteNAVAaregisteret")
        ),
        "naeringskode1": code(raw.get("naeringskode1")),
        "naeringskode2": code(raw.get("naeringskode2")),
        "naeringskode3": code(raw.get("naeringskode3")),
        "hjelpeenhetskode": code(raw.get("hjelpeenhetskode")),
        "institusjonell_sektorkode": code(raw.get("institusjonellSektorkode")),
        "forretningsadresse_kommunenummer": dig(raw, ("forretningsadresse", "kommunenummer")),
        "forretningsadresse_postnummer": dig(raw, ("forretningsadresse", "postnummer")),
        "forretningsadresse_landkode": dig(raw, ("forretningsadresse", "landkode")),
        "postadresse_kommunenummer": dig(raw, ("postadresse", "kommunenummer")),
        "registrert_i_mvaregisteret": to_bool(raw.get("registrertIMvaregisteret")),
        "registreringsdato_mvaregisteret": to_date(
            raw.get("registreringsdatoMerverdiavgiftsregisteret")
        ),
        "antall_frivillig_mva_beskrivelser": count(raw.get("frivilligMvaRegistrertBeskrivelser")),
        "registrert_i_foretaksregisteret": to_bool(raw.get("registrertIForetaksregisteret")),
        "registreringsdato_foretaksregisteret": to_date(
            raw.get("registreringsdatoForetaksregisteret")
        ),
        "registrert_i_stiftelsesregisteret": to_bool(raw.get("registrertIStiftelsesregisteret")),
        "registrert_i_partiregisteret": to_bool(raw.get("registrertIPartiregisteret")),
        "konkurs": to_bool(raw.get("konkurs")),
        "konkursdato": to_date(raw.get("konkursdato")),
        "under_avvikling": to_bool(raw.get("underAvvikling")),
        "under_avvikling_dato": to_date(raw.get("underAvviklingDato")),
        "under_tvangsavvikling_eller_tvangsopplosning": to_bool(
            raw.get("underTvangsavviklingEllerTvangsopplosning")
        ),
        "tvangsavviklet_pga_manglende_sletting_dato": to_date(
            raw.get("tvangsavvikletPgaManglendeSlettingDato")
        ),
        "tvangsopplost_pga_manglende_daglig_leder_dato": to_date(
            raw.get("tvangsopplostPgaManglendeDagligLederDato")
        ),
        "tvangsopplost_pga_manglende_revisor_dato": to_date(
            raw.get("tvangsopplostPgaManglendeRevisorDato")
        ),
        "tvangsopplost_pga_manglende_regnskap_dato": to_date(
            raw.get("tvangsopplostPgaManglendeRegnskapDato")
        ),
        "tvangsopplost_pga_mangelfullt_styre_dato": to_date(
            raw.get("tvangsopplostPgaMangelfulltStyreDato")
        ),
        "under_rekonstruksjonsforhandling_dato": to_date(
            raw.get("underRekonstruksjonsforhandlingDato")
        ),
        "under_utenlandsk_insolvensbehandling_dato": to_date(
            raw.get("underUtenlandskInsolvensbehandlingDato")
        ),
        "fravalg_revisjon_dato": to_date(raw.get("fravalgRevisjonDato")),
        "fravalg_revisjon_beslutnings_dato": to_date(raw.get("fravalgRevisjonBeslutningsDato")),
        "siste_innsendte_aarsregnskap": to_year(raw.get("sisteInnsendteAarsregnskap")),
        "er_i_konsern": to_bool(raw.get("erIKonsern")),
        "maalform": raw.get("maalform"),
        "antall_historiske_navn": count(raw.get("historiskeNavn")),
        "antall_paategninger": len(paategninger),
        "paategning_infotyper": ";".join(infotyper) if infotyper else None,
        "har_hjemmeside": non_empty(raw.get("hjemmeside")),
        "har_epostadresse": non_empty(raw.get("epostadresse")),
        "har_telefon": non_empty(raw.get("telefon")) or non_empty(raw.get("mobil")),
    }


def project_enhet_text(raw: dict) -> dict | None:
    formaal = join_lines(raw.get("vedtektsfestetFormaal"))
    aktivitet = join_lines(raw.get("aktivitet"))
    if formaal is None and aktivitet is None:
        return None
    return {
        "organisasjonsnummer": str(raw.get("organisasjonsnummer")),
        "vedtektsfestet_formaal": formaal,
        "aktivitet": aktivitet,
    }


def acquire_enheter(
    open_stream: StreamOpener,
    landing: Landing,
    scope: ScopeConfig,
    rows_per_file: int = 50_000,
) -> dict:
    """Stream the bulk file into the ``enheter`` and ``enheter_tekst`` landing tables."""
    counts: Counter[str] = Counter()
    dropped_by_form: Counter[str] = Counter()
    with (
        open_stream() as stream,
        ParquetBatchWriter(landing.table_dir("enheter"), ENHET_SCHEMA, rows_per_file) as writer,
        ParquetBatchWriter(
            landing.table_dir("enheter_tekst"), ENHET_TEXT_SCHEMA, rows_per_file
        ) as text_writer,
    ):
        for raw in iter_items(stream):
            counts["total"] += 1
            reason = drop_reason(raw, scope)
            if reason is not None:
                counts[f"dropped_{reason}"] += 1
                if reason == DROP_FORM:
                    dropped_by_form[code(raw.get("organisasjonsform")) or "missing"] += 1
                continue
            writer.write(project_enhet(raw))
            counts["kept"] += 1
            text = project_enhet_text(raw)
            if text is not None:
                text_writer.write(text)
                counts["kept_with_text"] += 1
            if counts["total"] % 200_000 == 0:
                log.info("enheter: %d read, %d kept", counts["total"], counts["kept"])
    summary = {
        "rows_total": counts["total"],
        "rows_kept": counts["kept"],
        "rows_kept_with_text": counts["kept_with_text"],
        "rows_dropped_form": counts[f"dropped_{DROP_FORM}"],
        "rows_dropped_frivillighetsregisteret": counts[f"dropped_{DROP_FRIVILLIG}"],
        "rows_dropped_deleted": counts[f"dropped_{DROP_DELETED}"],
        "dropped_by_form": dict(dropped_by_form.most_common()),
        "files": writer.files_written,
    }
    log.info("enheter done: %s", {k: v for k, v in summary.items() if k != "dropped_by_form"})
    landing.update_manifest("enheter", summary)
    return summary
