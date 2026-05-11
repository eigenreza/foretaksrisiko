"""Gold: one wide row per company per snapshot, the base for features and labels."""

from __future__ import annotations

import logging

import pyarrow as pa

from foretaksrisiko.acquire.regnskap import NUMERIC_PATHS, REGNSKAP_SCHEMA
from foretaksrisiko.acquire.roller import ROLLER_COUNTS_SCHEMA, ROLLER_LINKS_SCHEMA
from foretaksrisiko.acquire.sampling import SAMPLE_SCHEMA
from foretaksrisiko.acquire.underenheter import UNDERENHET_SCHEMA
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, table_exists, write_snapshot

log = logging.getLogger(__name__)

ROLE_COLUMNS = [n for n in ROLLER_COUNTS_SCHEMA.names if n != "organisasjonsnummer"]
ACCOUNT_COLUMNS = [
    "regnskap_id",
    "regnskapsperiode_fra_dato",
    "regnskapsperiode_til_dato",
    "fiscal_year",
    "period_days",
    "valuta",
    "avviklingsregnskap",
    "oppstillingsplan",
    "ikke_revidert_aarsregnskap",
    "fravalg_revisjon",
    "smaa_foretak",
    "regnskapsregler",
    "morselskap",
    *NUMERIC_PATHS,
]
PREVIOUS_COLUMNS = [
    "fiscal_year",
    "sum_driftsinntekter",
    "driftsresultat",
    "aarsresultat",
    "sum_eiendeler",
    "sum_egenkapital",
    "sum_gjeld",
]

_ARROW_TO_SPARK = {
    pa.string(): "STRING",
    pa.int32(): "INT",
    pa.int64(): "BIGINT",
    pa.float64(): "DOUBLE",
    pa.bool_(): "BOOLEAN",
    pa.date32(): "DATE",
}


def ddl_from_arrow(schema: pa.Schema, extra: str = "") -> str:
    parts = [f"{field.name} {_ARROW_TO_SPARK[field.type]}" for field in schema]
    return ", ".join(parts + ([extra] if extra else []))


SNAPSHOT_COLUMNS = "snapshot_id INT, snapshot_date DATE, ingested_at TIMESTAMP"


def _snapshot_view(
    spark, names: Names, table: str, view: str, snapshot_id: int, schema: pa.Schema, extra: str = ""
) -> bool:
    """Temp view of a silver table for the snapshot, or an empty view with the expected schema."""
    from pyspark.sql import functions as F

    source = names.table("silver", table)
    if table_exists(spark, source):
        df = spark.table(source).where(F.col("snapshot_id") == snapshot_id)
        if df.limit(1).count() > 0:
            df.createOrReplaceTempView(view)
            return True
    ddl = ddl_from_arrow(schema, ", ".join(p for p in (SNAPSHOT_COLUMNS, extra) if p))
    spark.createDataFrame([], ddl).createOrReplaceTempView(view)
    return False


def build_company_snapshot(spark, names: Names, snapshot_id: int) -> int:
    from pyspark.sql import functions as F

    ensure_schemas(spark, names, ("gold",))
    enheter = spark.table(names.table("silver", "enheter")).where(
        F.col("snapshot_id") == snapshot_id
    )
    enheter.createOrReplaceTempView("g_enheter")
    present = {
        "roller_counts": _snapshot_view(
            spark, names, "roller_counts", "g_roles", snapshot_id, ROLLER_COUNTS_SCHEMA
        ),
        "underenheter": _snapshot_view(
            spark, names, "underenheter", "g_sub", snapshot_id, UNDERENHET_SCHEMA
        ),
        "roller_links": _snapshot_view(
            spark, names, "roller_links", "g_links", snapshot_id, ROLLER_LINKS_SCHEMA
        ),
        "regnskap": _snapshot_view(
            spark,
            names,
            "regnskap",
            "g_regnskap",
            snapshot_id,
            REGNSKAP_SCHEMA,
            "fiscal_year INT, period_days INT",
        ),
        "sample": _snapshot_view(spark, names, "sample", "g_sample", snapshot_id, SAMPLE_SCHEMA),
    }
    role_select = ",\n".join(f"r.{c}" for c in ROLE_COLUMNS)
    account_select = ",\n".join(f"a.{c} AS acc_{c}" for c in ACCOUNT_COLUMNS)
    previous_select = ",\n".join(f"p.{c} AS acc_prev_{c}" for c in PREVIOUS_COLUMNS)
    df = spark.sql(
        f"""
        WITH sub AS (
          SELECT u.overordnet_enhet AS organisasjonsnummer,
                 count(*) AS n_sub_units,
                 sum(CASE WHEN u.nedleggelsesdato IS NULL THEN 1 ELSE 0 END) AS n_sub_units_active,
                 count(DISTINCT u.beliggenhetsadresse_kommunenummer) AS n_sub_unit_municipalities,
                 sum(u.antall_ansatte) AS sub_units_antall_ansatte,
                 sum(IF(u.oppstartsdato >= date_sub(u.snapshot_date, 365), 1, 0))
                   AS n_sub_units_opened_12m,
                 sum(IF(u.nedleggelsesdato >= date_sub(u.snapshot_date, 365), 1, 0))
                   AS n_sub_units_closed_12m,
                 sum(IF(u.dato_eierskifte >= date_sub(u.snapshot_date, 365), 1, 0))
                   AS n_ownership_changes_12m
          FROM g_sub u GROUP BY u.overordnet_enhet
        ),
        links AS (SELECT * FROM g_links WHERE NOT avregistrert),
        aud AS (
          SELECT organisasjonsnummer, min(rolleholder_organisasjonsnummer) AS auditor_orgnr,
                 count(*) AS n_auditor_links
          FROM links WHERE rolletype = 'REVI' GROUP BY organisasjonsnummer
        ),
        acc AS (
          SELECT organisasjonsnummer, min(rolleholder_organisasjonsnummer) AS accountant_orgnr,
                 count(*) AS n_accountant_links
          FROM links WHERE rolletype = 'REGN' GROUP BY organisasjonsnummer
        ),
        aud_port AS (
          SELECT rolleholder_organisasjonsnummer AS auditor_orgnr,
                 count(DISTINCT organisasjonsnummer) AS auditor_portfolio_size
          FROM links WHERE rolletype = 'REVI' GROUP BY rolleholder_organisasjonsnummer
        ),
        acc_port AS (
          SELECT rolleholder_organisasjonsnummer AS accountant_orgnr,
                 count(DISTINCT organisasjonsnummer) AS accountant_portfolio_size
          FROM links WHERE rolletype = 'REGN' GROUP BY rolleholder_organisasjonsnummer
        ),
        reg AS (
          SELECT g.*, row_number() OVER (
                   PARTITION BY g.organisasjonsnummer
                   ORDER BY g.regnskapsperiode_til_dato DESC, g.regnskap_id DESC) AS rn
          FROM g_regnskap g
          WHERE g.regnskapstype = 'SELSKAP' AND g.regnskapsperiode_til_dato <= g.snapshot_date
        ),
        reg_all AS (
          SELECT organisasjonsnummer,
                 count(DISTINCT CASE WHEN regnskapstype = 'SELSKAP' THEN fiscal_year END)
                   AS n_accounts_years,
                 max(CASE WHEN regnskapstype = 'KONSERN' THEN true ELSE false END)
                   AS has_konsern_regnskap
          FROM g_regnskap GROUP BY organisasjonsnummer
        ),
        latest AS (SELECT * FROM reg WHERE rn = 1),
        previous AS (SELECT * FROM reg WHERE rn = 2)
        SELECT
          e.*,
          {role_select},
          coalesce(sub.n_sub_units, 0) AS n_sub_units,
          coalesce(sub.n_sub_units_active, 0) AS n_sub_units_active,
          coalesce(sub.n_sub_unit_municipalities, 0) AS n_sub_unit_municipalities,
          sub.sub_units_antall_ansatte,
          coalesce(sub.n_sub_units_opened_12m, 0) AS n_sub_units_opened_12m,
          coalesce(sub.n_sub_units_closed_12m, 0) AS n_sub_units_closed_12m,
          coalesce(sub.n_ownership_changes_12m, 0) AS n_ownership_changes_12m,
          aud.auditor_orgnr,
          coalesce(aud.n_auditor_links, 0) AS n_auditor_links,
          aud_port.auditor_portfolio_size,
          acc.accountant_orgnr,
          coalesce(acc.n_accountant_links, 0) AS n_accountant_links,
          acc_port.accountant_portfolio_size,
          a.organisasjonsnummer IS NOT NULL AS has_accounts,
          coalesce(reg_all.n_accounts_years, 0) AS n_accounts_years,
          coalesce(reg_all.has_konsern_regnskap, false) AS has_konsern_regnskap,
          datediff(e.snapshot_date, a.regnskapsperiode_til_dato) AS accounts_age_days,
          {account_select},
          {previous_select},
          coalesce(smp.organisasjonsnummer IS NOT NULL, false) AS in_dev_sample
        FROM g_enheter e
        LEFT JOIN g_roles r ON r.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN sub ON sub.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN aud ON aud.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN aud_port ON aud_port.auditor_orgnr = aud.auditor_orgnr
        LEFT JOIN acc ON acc.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN acc_port ON acc_port.accountant_orgnr = acc.accountant_orgnr
        LEFT JOIN latest a ON a.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN previous p ON p.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN reg_all ON reg_all.organisasjonsnummer = e.organisasjonsnummer
        LEFT JOIN g_sample smp ON smp.organisasjonsnummer = e.organisasjonsnummer
        """
    )
    target = names.table("gold", "company_snapshot")
    write_snapshot(df, target, snapshot_id)
    rows = spark.table(target).where(F.col("snapshot_id") == snapshot_id).count()
    log.info(
        "gold company_snapshot snapshot %d rows %d, inputs present: %s", snapshot_id, rows, present
    )
    return rows
