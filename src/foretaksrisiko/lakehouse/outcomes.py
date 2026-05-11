"""Gold outcomes: the first known date of each proxy outcome per company, from all snapshots.

Sources are the register status fields in every silver snapshot and the change events, which also
cover companies that were deleted later. The table is rebuilt completely on every run.
"""

from __future__ import annotations

import logging

from foretaksrisiko.lakehouse.session import Names, ensure_schemas, overwrite_table, table_exists

log = logging.getLogger(__name__)

TVANG_COLUMNS = [
    "tvangsavviklet_pga_manglende_sletting_dato",
    "tvangsopplost_pga_manglende_daglig_leder_dato",
    "tvangsopplost_pga_manglende_revisor_dato",
    "tvangsopplost_pga_manglende_regnskap_dato",
    "tvangsopplost_pga_mangelfullt_styre_dato",
]


def build_outcomes(spark, names: Names) -> int:
    ensure_schemas(spark, names, ("gold",))
    enheter = names.table("silver", "enheter")
    events = names.table("silver", "events_enheter")
    tvang_least = "least(" + ", ".join(TVANG_COLUMNS) + ")"
    register = spark.sql(
        f"""
        SELECT organisasjonsnummer,
               min(konkursdato) AS reg_bankruptcy,
               min({tvang_least}) AS reg_forced,
               min(under_avvikling_dato) AS reg_voluntary,
               min(under_rekonstruksjonsforhandling_dato) AS reg_reconstruction,
               min(registreringsdato_enhetsregisteret) AS registered,
               min(snapshot_id) AS first_seen_snapshot,
               max(snapshot_id) AS last_seen_snapshot,
               max(snapshot_date) AS last_seen_date
        FROM {enheter}
        GROUP BY organisasjonsnummer
        """
    )
    register.createOrReplaceTempView("outcomes_register")
    if table_exists(spark, events):
        spark.sql(
            f"""
            CREATE OR REPLACE TEMP VIEW outcomes_events AS
            SELECT organisasjonsnummer,
                   min(CASE WHEN konkurs THEN coalesce(konkursdato, to_date(substr(dato, 1, 10))) END)
                     AS ev_bankruptcy,
                   min(konkursdato) AS ev_bankruptcy_date,
                   min(CASE WHEN under_tvang THEN coalesce(tvang_dato, to_date(substr(dato, 1, 10))) END)
                     AS ev_forced,
                   min(tvang_dato) AS ev_forced_date,
                   min(CASE WHEN under_avvikling
                            THEN coalesce(under_avvikling_dato, to_date(substr(dato, 1, 10))) END)
                     AS ev_voluntary,
                   min(under_avvikling_dato) AS ev_voluntary_date,
                   min(CASE WHEN endringstype = 'Sletting' THEN to_date(substr(dato, 1, 10)) END)
                     AS ev_deleted,
                   min(CASE WHEN endringstype = 'Fjernet' THEN to_date(substr(dato, 1, 10)) END)
                     AS ev_removed
            FROM (SELECT DISTINCT organisasjonsnummer, oppdateringsid, dato, endringstype, konkurs,
                         konkursdato, under_tvang, tvang_dato, under_avvikling, under_avvikling_dato
                  FROM {events})
            GROUP BY organisasjonsnummer
            """
        )
    else:
        spark.sql(
            """
            CREATE OR REPLACE TEMP VIEW outcomes_events AS
            SELECT organisasjonsnummer, CAST(NULL AS DATE) AS ev_bankruptcy,
                   CAST(NULL AS DATE) AS ev_bankruptcy_date, CAST(NULL AS DATE) AS ev_forced,
                   CAST(NULL AS DATE) AS ev_forced_date, CAST(NULL AS DATE) AS ev_voluntary,
                   CAST(NULL AS DATE) AS ev_voluntary_date, CAST(NULL AS DATE) AS ev_deleted,
                   CAST(NULL AS DATE) AS ev_removed
            FROM outcomes_register WHERE 1 = 0
            """
        )
    outcomes = spark.sql(
        """
        SELECT coalesce(r.organisasjonsnummer, e.organisasjonsnummer) AS organisasjonsnummer,
               r.registered,
               least(r.reg_bankruptcy, e.ev_bankruptcy_date, e.ev_bankruptcy) AS first_bankruptcy_date,
               least(r.reg_forced, e.ev_forced_date, e.ev_forced) AS first_forced_date,
               least(r.reg_voluntary, e.ev_voluntary_date, e.ev_voluntary) AS first_voluntary_date,
               r.reg_reconstruction AS first_reconstruction_date,
               e.ev_deleted AS deletion_date,
               e.ev_removed AS removed_from_open_data_date,
               r.first_seen_snapshot, r.last_seen_snapshot, r.last_seen_date,
               r.organisasjonsnummer IS NOT NULL AS in_population
        FROM outcomes_register r
        FULL OUTER JOIN outcomes_events e ON e.organisasjonsnummer = r.organisasjonsnummer
        """
    )
    target = names.table("gold", "outcomes")
    overwrite_table(outcomes, target)
    rows = spark.table(target).count()
    log.info("gold outcomes rows %d", rows)
    return rows
