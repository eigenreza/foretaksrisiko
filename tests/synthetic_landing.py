"""Builds a complete synthetic landing folder for lakehouse tests. No real data.

privacy-scan: allow-dates
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from conftest import (
    AS_1,
    AS_2,
    AS_AUDITOR,
    ASA_1,
    enheter_records,
    fake_orgnr,
    gz_array,
    opener_for,
    roller_records,
    underenheter_records,
)
from foretaksrisiko.acquire.enheter import acquire_enheter
from foretaksrisiko.acquire.history import EVENTS_SCHEMA, MONTHLY_SCHEMA, ROLE_EVENTS_SCHEMA
from foretaksrisiko.acquire.klass import KLASS_CORR_SCHEMA, KLASS_ITEM_SCHEMA
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter
from foretaksrisiko.acquire.regnskap import (
    REGNSKAP_SCHEMA,
    REGNSKAP_STATUS_SCHEMA,
    flatten_regnskap,
)
from foretaksrisiko.acquire.roller import acquire_roller
from foretaksrisiko.acquire.sampling import SAMPLE_SCHEMA
from foretaksrisiko.acquire.underenheter import acquire_underenheter
from foretaksrisiko.config import ScopeConfig
from foretaksrisiko.features.text import TEXT_FEATURES_SCHEMA

AS_3 = fake_orgnr(13)

SN2025_ITEMS = [
    ("J", None, 1, "Informasjon og kommunikasjon"),
    ("62", "J", 2, "Tjenester tilknyttet informasjonsteknologi"),
    ("62.0", "62", 3, "Tjenester tilknyttet informasjonsteknologi"),
    ("62.01", "62.0", 4, "Programmeringstjenester"),
    ("62.010", "62.01", 5, "Programmeringstjenester"),
    ("F", None, 1, "Bygge- og anleggsvirksomhet"),
    ("41", "F", 2, "Oppfoering av bygninger"),
    ("41.2", "41", 3, "Oppfoering av bygninger"),
    ("41.20", "41.2", 4, "Oppfoering av bygninger"),
    ("41.200", "41.20", 5, "Oppfoering av bygninger"),
    ("K", None, 1, "Finansiering og forsikring"),
    ("64", "K", 2, "Finansieringsvirksomhet"),
    ("64.1", "64", 3, "Bankvirksomhet"),
    ("64.19", "64.1", 4, "Bankvirksomhet ellers"),
    ("64.190", "64.19", 5, "Bankvirksomhet ellers"),
    ("M", None, 1, "Faglig tjenesteyting"),
    ("69", "M", 2, "Juridisk og regnskapsmessig tjenesteyting"),
    ("69.2", "69", 3, "Regnskap og revisjon"),
    ("69.20", "69.2", 4, "Regnskap og revisjon"),
    ("69.201", "69.20", 5, "Revisjon"),
    ("69.202", "69.20", 5, "Regnskap"),
]
# SN2007 has the same codes plus one old code that split into two SN2025 codes.
SN2007_ITEMS = SN2025_ITEMS + [("69.209", "69.20", 5, "Annen regnskap og revisjon")]
CORRESPONDENCE = [
    ("62.010", "62.010"),
    ("41.200", "41.200"),
    ("64.190", "64.190"),
    ("69.201", "69.209"),
    ("69.202", "69.209"),
]
FYLKER = [("03", "Oslo"), ("11", "Rogaland"), ("46", "Vestland")]
KOMMUNER = [("0301", "Oslo"), ("1103", "Stavanger"), ("4601", "Bergen")]


def _write(directory: Path, schema, rows: list[dict]) -> None:
    with ParquetBatchWriter(directory, schema) as writer:
        for row in rows:
            writer.write(row)


def _regnskap_item(year: int, typ: str, revenue: float, result: float) -> dict:
    return {
        "id": year * 100 + (1 if typ == "SELSKAP" else 2),
        "regnskapstype": typ,
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "valuta": "NOK",
        "avviklingsregnskap": False,
        "oppstillingsplan": "smaa",
        "revisjon": {"ikkeRevidertAarsregnskap": True, "fravalgRevisjon": True},
        "regnkapsprinsipper": {
            "smaaForetak": True,
            "regnskapsregler": "regnskapslovenAlminneligRegler",
        },
        "virksomhet": {"morselskap": False},
        "egenkapitalGjeld": {
            "sumEgenkapitalGjeld": 1000.0,
            "egenkapital": {"sumEgenkapital": 400.0},
            "gjeldOversikt": {"sumGjeld": 600.0},
        },
        "eiendeler": {"sumEiendeler": 1000.0},
        "resultatregnskapResultat": {
            "aarsresultat": result,
            "driftsresultat": {
                "driftsresultat": result + 10,
                "driftsinntekter": {"sumDriftsinntekter": revenue, "salgsinntekter": revenue},
            },
        },
    }


def build_landing(
    landing_dir: Path, snapshot_id: int, snapshot_date_iso: str, variant: int = 1
) -> Landing:
    """Variant 1 is the base population; variant 2 moves AS_1, removes ASA_1 and adds AS_3."""
    landing = Landing(landing_dir, snapshot_id)
    scope = ScopeConfig()
    units = enheter_records()
    subs = underenheter_records()
    roles = roller_records()
    if variant == 2:
        for unit in units:
            if unit.get("organisasjonsnummer") == AS_1:
                unit["forretningsadresse"] = {
                    "kommunenummer": "4601",
                    "postnummer": "5003",
                    "landkode": "NO",
                }
                unit["antallAnsatte"] = 25
        units = [u for u in units if u.get("organisasjonsnummer") != ASA_1]
        new_unit = dict(units[0])
        new_unit.update(
            {
                "organisasjonsnummer": AS_3,
                "navn": "SYNTETISK NY",
                "naeringskode1": {"kode": "69.209", "beskrivelse": "Gammel kode"},
                "registreringsdatoEnhetsregisteret": "2026-01-15",
                "stiftelsesdato": "2026-01-10",
            }
        )
        units.append(new_unit)
        roles = [r for r in roles if r["organisasjonsnummer"] != ASA_1]
    for entry in roles:
        if entry["organisasjonsnummer"] == ASA_1:
            for group in entry["rollegrupper"]:
                if group["type"]["kode"] == "STYR":
                    group["sistEndret"] = "2026-08-01"
    kept = {
        u["organisasjonsnummer"]
        for u in units
        if u.get("organisasjonsform", {}).get("kode") in scope.organisasjonsformer
        and not u.get("registrertIFrivillighetsregisteret")
        and u.get("respons_klasse") != "SlettetEnhet"
    }
    acquire_enheter(opener_for(gz_array(units)), landing, scope)
    acquire_underenheter(opener_for(gz_array(subs)), landing, kept)
    acquire_roller(opener_for(gz_array(roles)), landing, kept)

    klass_root = landing.root / "klass"
    for name, items in (("sn2025", SN2025_ITEMS), ("sn2007", SN2007_ITEMS)):
        _write(
            klass_root / name,
            KLASS_ITEM_SCHEMA,
            [
                {
                    "code": c,
                    "parent_code": p,
                    "level": lvl,
                    "name": n,
                    "short_name": None,
                    "notes": None,
                }
                for c, p, lvl, n in items
            ],
        )
    _write(
        klass_root / "sn_corr_2025_2007",
        KLASS_CORR_SCHEMA,
        [
            {"source_code": s, "source_name": "x", "target_code": t, "target_name": "y"}
            for s, t in CORRESPONDENCE
        ],
    )
    _write(
        klass_root / "fylke",
        KLASS_ITEM_SCHEMA,
        [
            {
                "code": c,
                "parent_code": None,
                "level": 1,
                "name": n,
                "short_name": None,
                "notes": None,
            }
            for c, n in FYLKER
        ],
    )
    _write(
        klass_root / "kommune",
        KLASS_ITEM_SCHEMA,
        [
            {
                "code": c,
                "parent_code": None,
                "level": 1,
                "name": n,
                "short_name": None,
                "notes": None,
            }
            for c, n in KOMMUNER
        ],
    )
    for name in ("fylke_corr_2026_2024", "kommune_corr_2026_2024"):
        _write(klass_root / name, KLASS_CORR_SCHEMA, [])

    # One statement covers a single day. Both dates are inclusive, so that is a valid period.
    one_day = _regnskap_item(2022, "SELSKAP", 0.0, 0.0)
    one_day["regnskapsperiode"] = {"fraDato": "2022-12-31", "tilDato": "2022-12-31"}
    accounts = [
        flatten_regnskap(AS_1, _regnskap_item(2023, "SELSKAP", 900.0, 40.0)),
        flatten_regnskap(AS_1, _regnskap_item(2024, "SELSKAP", 1200.0, 60.0)),
        flatten_regnskap(AS_1, _regnskap_item(2024, "KONSERN", 1500.0, 70.0)),
        flatten_regnskap(AS_1, _regnskap_item(2025, "SELSKAP", 1300.0, 65.0)),
        flatten_regnskap(AS_AUDITOR, _regnskap_item(2024, "SELSKAP", 300.0, 10.0)),
        flatten_regnskap(AS_AUDITOR, one_day),
    ]
    _write(landing.root / "regnskap", REGNSKAP_SCHEMA, accounts)
    # The status table mixes a file written before the source snapshot field existed with a
    # current one, and one company has a failed request next to its final answer.
    status_dir = landing.root / "regnskap_status"
    status_dir.mkdir(parents=True, exist_ok=True)
    older = pa.schema([f for f in REGNSKAP_STATUS_SCHEMA if f.name != "source_snapshot_id"])
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"organisasjonsnummer": AS_1, "http_status": 200, "n_regnskap": 3},
                {"organisasjonsnummer": AS_2, "http_status": 404, "n_regnskap": 0},
                {"organisasjonsnummer": AS_AUDITOR, "http_status": 0, "n_regnskap": 0},
            ],
            schema=older,
        ),
        status_dir / "batch-00000.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "organisasjonsnummer": AS_AUDITOR,
                    "http_status": 200,
                    "n_regnskap": 1,
                    "source_snapshot_id": snapshot_id,
                }
            ],
            schema=REGNSKAP_STATUS_SCHEMA,
        ),
        status_dir / "batch-00001.parquet",
    )
    sample_rows = [
        {"organisasjonsnummer": o, "stratum_section": "J", "stratum_county": "03"}
        for o in sorted(kept)
        if o in {AS_1, AS_2}
    ]
    _write(landing.root / "sample", SAMPLE_SCHEMA, sample_rows)

    def event(oid, orgnr, dato, typ="Endring", fields=None, **status):
        row = {name: None for name in EVENTS_SCHEMA.names}
        row.update(
            {
                "organisasjonsnummer": orgnr,
                "oppdateringsid": oid,
                "dato": dato,
                "endringstype": typ,
                "n_changes": len(fields.split(";")) if fields else 0,
                "changed_fields": fields,
            }
        )
        row.update(status)
        return row

    events = [
        event(1, AS_1, "2026-01-15T10:00:00.000Z", fields="forretningsadresse"),
        event(2, AS_1, "2026-06-01T10:00:00.000Z", fields="kapital"),
        event(
            3,
            AS_1,
            "2026-06-10T10:00:00.000Z",
            fields="sisteInnsendteAarsregnskap",
            siste_innsendte_aarsregnskap=2025,
        ),
        event(
            4,
            AS_AUDITOR,
            "2026-07-15T10:00:00.000Z",
            fields="konkurs;konkursdato",
            konkurs=True,
            konkursdato=date(2026, 7, 15),
        ),
        event(5, AS_2, "2025-09-01T10:00:00.000Z", fields="navn"),
    ]
    _write(landing.root / "events_enheter", EVENTS_SCHEMA, events)
    _write(
        landing.root / "events_monthly_all",
        MONTHLY_SCHEMA,
        [
            {
                "month": "2026-07",
                "endringstype": "Endring",
                "field": "konkurs",
                "in_population": True,
                "n_events": 1,
            }
        ],
    )
    _write(
        landing.root / "events_roller",
        ROLE_EVENTS_SCHEMA,
        [
            {"organisasjonsnummer": AS_1, "event_id": 11, "time": "2026-02-01T10:00:00Z"},
            {"organisasjonsnummer": AS_1, "event_id": 12, "time": "2026-03-01T10:00:00Z"},
            {"organisasjonsnummer": AS_1, "event_id": 13, "time": "2025-01-01T10:00:00Z"},
        ],
    )
    _write(
        landing.root / "text_features",
        TEXT_FEATURES_SCHEMA,
        [
            {
                "organisasjonsnummer": AS_1,
                "text_chars": 40,
                "text_sim_own_code": 0.4,
                "text_sim_best": 0.5,
                "text_rank_own_code": 3,
                "text_sim_section": 0.3,
            },
            {
                "organisasjonsnummer": AS_2,
                "text_chars": 0,
                "text_sim_own_code": None,
                "text_sim_best": None,
                "text_rank_own_code": None,
                "text_sim_section": None,
            },
        ],
    )
    landing.update_manifest("sample", {"sample_size": len(sample_rows)})
    landing.update_manifest("enheter", {"source": {"last_modified_iso": snapshot_date_iso}})
    assert json.loads(landing.manifest_path.read_text(encoding="utf-8"))["enheter"][
        "rows_kept"
    ] == len(kept)
    return landing
