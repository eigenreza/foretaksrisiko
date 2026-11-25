"""Silver: typed, deduplicated and conformed tables, NACE on both standards, regions, history."""

from __future__ import annotations

import logging

from foretaksrisiko.acquire.sampling import build_section_lookup
from foretaksrisiko.lakehouse.session import (
    Names,
    ensure_schemas,
    overwrite_table,
    table_exists,
    write_snapshot,
)

log = logging.getLogger(__name__)

# Tables copied from bronze with deduplication on these keys (None: whole row).
PASS_THROUGH: dict[str, list[str] | None] = {
    "underenheter": ["organisasjonsnummer"],
    "roller_counts": ["organisasjonsnummer"],
    "roller_links": None,
    "regnskap": ["organisasjonsnummer", "regnskap_id"],
    "regnskap_status": ["organisasjonsnummer"],
    "sample": ["organisasjonsnummer"],
    "oppdateringer_enheter": ["organisasjonsnummer", "endringstype"],
    "oppdateringer_underenheter": ["organisasjonsnummer", "endringstype"],
    "oppdateringer_roller": ["organisasjonsnummer"],
    "events_enheter": ["organisasjonsnummer", "oppdateringsid"],
    "events_roller": ["organisasjonsnummer", "event_id"],
    "events_monthly_all": ["month", "endringstype", "field", "in_population"],
    "text_features": ["organisasjonsnummer"],
}

# Attributes whose changes across snapshots are recorded in the type 2 history table.
HISTORY_COLUMNS = [
    "organisasjonsform",
    "nace_code",
    "forretningsadresse_kommunenummer",
    "forretningsadresse_postnummer",
    "kapital_belop",
    "antall_ansatte",
    "har_registrert_antall_ansatte",
    "registrert_i_mvaregisteret",
    "registrert_i_foretaksregisteret",
    "konkurs",
    "under_avvikling",
    "under_tvangsavvikling_eller_tvangsopplosning",
    "er_i_konsern",
    "siste_innsendte_aarsregnskap",
    "antall_historiske_navn",
    "fravalg_revisjon_dato",
]

PLACEHOLDER_NACE = "00.000"


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def resolve_mapping(pairs: list[tuple[str, str]]) -> list[tuple[str, str, int, bool]]:
    """Pick one target per source: longest shared prefix, then the smallest code. Flag ambiguity."""
    by_source: dict[str, set[str]] = {}
    for source, target in pairs:
        if source and target:
            by_source.setdefault(source, set()).add(target)
    rows = []
    for source in sorted(by_source):
        candidates = sorted(by_source[source], key=lambda t: (-_common_prefix(source, t), t))
        rows.append((source, candidates[0], len(candidates), len(candidates) > 1))
    return rows


def _dedupe(df, keys: list[str] | None, prefer: str | None = None):
    """One row per key: the highest value of ``prefer`` first, then the latest ingestion."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    if keys is None:
        return df.dropDuplicates([c for c in df.columns if c != "ingested_at"])
    order = ([F.col(prefer).desc()] if prefer else []) + [F.col("ingested_at").desc()]
    window = Window.partitionBy(*keys).orderBy(*order)
    return df.withColumn("_rn", F.row_number().over(window)).where("_rn = 1").drop("_rn")


def build_reference_tables(spark, names: Names, snapshot_id: int) -> dict[str, int]:
    """Code lists with section and division, resolved NACE maps, counties and municipalities."""
    from pyspark.sql import functions as F

    ensure_schemas(spark, names, ("silver",))
    counts: dict[str, int] = {}

    def rows_of(table: str, columns: list[str]) -> list[dict]:
        source = spark.table(names.table("bronze", table)).where(
            F.col("snapshot_id") == snapshot_id
        )
        return [r.asDict() for r in source.select(*columns).collect()]

    for standard in ("sn2025", "sn2007"):
        items = rows_of(f"klass_{standard}", ["code", "parent_code", "level", "name"])
        section_of = build_section_lookup(items)
        data = [
            (
                it["code"],
                it["name"],
                int(it["level"]),
                it["parent_code"],
                section_of(it["code"]) if int(it["level"]) > 1 else it["code"],
                it["code"][:2] if int(it["level"]) >= 2 else None,
            )
            for it in items
        ]
        df = spark.createDataFrame(
            data,
            "code STRING, name STRING, level INT, parent_code STRING, "
            "section STRING, division STRING",
        ).withColumn("snapshot_id", F.lit(int(snapshot_id)))
        overwrite_table(df, names.table("silver", f"klass_{standard}"))
        counts[f"klass_{standard}"] = len(data)

    corr = [
        (r["source_code"], r["target_code"])
        for r in rows_of("klass_sn_corr_2025_2007", ["source_code", "target_code"])
    ]
    to_2025 = resolve_mapping([(t, s) for s, t in corr])
    to_2007 = resolve_mapping(corr)
    overwrite_table(
        spark.createDataFrame(
            to_2025, "sn2007 STRING, sn2025 STRING, n_candidates INT, ambiguous BOOLEAN"
        ),
        names.table("silver", "nace_map_2007_to_2025"),
    )
    overwrite_table(
        spark.createDataFrame(
            to_2007, "sn2025 STRING, sn2007 STRING, n_candidates INT, ambiguous BOOLEAN"
        ),
        names.table("silver", "nace_map_2025_to_2007"),
    )
    counts["nace_map_2007_to_2025"] = len(to_2025)
    counts["nace_map_2025_to_2007"] = len(to_2007)

    fylke = [(r["code"], r["name"]) for r in rows_of("klass_fylke", ["code", "name"])]
    overwrite_table(
        spark.createDataFrame(fylke, "code STRING, name STRING"), names.table("silver", "fylke")
    )
    kommune = [
        (r["code"], r["name"], r["code"][:2]) for r in rows_of("klass_kommune", ["code", "name"])
    ]
    overwrite_table(
        spark.createDataFrame(kommune, "code STRING, name STRING, fylke_code STRING"),
        names.table("silver", "kommune"),
    )
    counts["fylke"] = len(fylke)
    counts["kommune"] = len(kommune)
    log.info("silver reference tables: %s", counts)
    return counts


def build_silver_enheter(spark, names: Names, snapshot_id: int) -> int:
    """One row per company for the snapshot, with NACE on both standards and region names."""
    from pyspark.sql import functions as F

    bronze = spark.table(names.table("bronze", "enheter")).where(
        F.col("snapshot_id") == snapshot_id
    )
    dedup = _dedupe(bronze, ["organisasjonsnummer"]).withColumn(
        "nace_code",
        F.when(F.col("naeringskode1") == PLACEHOLDER_NACE, None).otherwise(F.col("naeringskode1")),
    )
    dedup.createOrReplaceTempView("silver_enheter_input")
    s = names.table
    df = spark.sql(
        f"""
        SELECT
          e.*,
          CASE WHEN s25.code IS NOT NULL THEN 'SN2025'
               WHEN s07.code IS NOT NULL THEN 'SN2007' END AS nace_standard,
          CASE WHEN s25.code IS NOT NULL THEN e.nace_code ELSE m07.sn2025 END AS nace_sn2025,
          CASE WHEN s25.code IS NOT NULL THEN m25.sn2007 ELSE s07.code END AS nace_sn2007,
          CASE WHEN s25.code IS NOT NULL THEN coalesce(m25.ambiguous, false)
               WHEN s07.code IS NOT NULL THEN coalesce(m07.ambiguous, false) END
            AS nace_mapping_ambiguous,
          coalesce(s25.section, s25b.section) AS nace_section,
          substr(CASE WHEN s25.code IS NOT NULL THEN e.nace_code ELSE m07.sn2025 END, 1, 2)
            AS nace_division,
          substr(e.forretningsadresse_kommunenummer, 1, 2) AS fylke_code,
          f.name AS fylke_name,
          k.name AS kommune_name,
          round(months_between(e.snapshot_date,
                coalesce(e.stiftelsesdato, e.registreringsdato_enhetsregisteret)) / 12, 2)
            AS company_age_years
        FROM silver_enheter_input e
        LEFT JOIN {s("silver", "klass_sn2025")} s25 ON s25.code = e.nace_code
        LEFT JOIN {s("silver", "klass_sn2007")} s07 ON s07.code = e.nace_code AND s25.code IS NULL
        LEFT JOIN {s("silver", "nace_map_2007_to_2025")} m07
          ON m07.sn2007 = e.nace_code AND s25.code IS NULL
        LEFT JOIN {s("silver", "nace_map_2025_to_2007")} m25
          ON m25.sn2025 = e.nace_code AND s25.code IS NOT NULL
        LEFT JOIN {s("silver", "klass_sn2025")} s25b ON s25b.code = m07.sn2025
        LEFT JOIN {s("silver", "fylke")} f
          ON f.code = substr(e.forretningsadresse_kommunenummer, 1, 2)
        LEFT JOIN {s("silver", "kommune")} k ON k.code = e.forretningsadresse_kommunenummer
        """
    )
    target = names.table("silver", "enheter")
    write_snapshot(df, target, snapshot_id)
    rows = spark.table(target).where(F.col("snapshot_id") == snapshot_id).count()
    log.info("silver enheter snapshot %d rows %d", snapshot_id, rows)
    return rows


def build_silver_pass_through(spark, names: Names, snapshot_id: int) -> dict[str, int]:
    from pyspark.sql import functions as F

    counts: dict[str, int] = {}
    for table, keys in PASS_THROUGH.items():
        source = names.table("bronze", table)
        if not table_exists(spark, source):
            continue
        df = spark.table(source).where(F.col("snapshot_id") == snapshot_id)
        if df.limit(1).count() == 0:
            continue
        # A request that failed is recorded with status 0; a final answer (200 or 404) for the
        # same company wins over it.
        df = _dedupe(df, keys, prefer="http_status" if table == "regnskap_status" else None)
        if table == "regnskap":
            df = df.withColumn("fiscal_year", F.year("regnskapsperiode_til_dato")).withColumn(
                "period_days",
                F.datediff("regnskapsperiode_til_dato", "regnskapsperiode_fra_dato") + F.lit(1),
            )
        target = names.table("silver", table)
        write_snapshot(df, target, snapshot_id)
        counts[table] = spark.table(target).where(F.col("snapshot_id") == snapshot_id).count()
    log.info("silver pass-through tables snapshot %d: %s", snapshot_id, counts)
    return counts


def build_history(spark, names: Names, snapshot_id: int) -> dict[str, int]:
    """Type 2 history of key attributes. Idempotent for a rerun of the same snapshot."""
    from pyspark.sql import functions as F

    silver = names.table("silver", "enheter")
    history = names.table("silver", "enheter_history")
    columns = ", ".join(HISTORY_COLUMNS)
    hash_expr = (
        "sha2(concat_ws('|', "
        + ", ".join(f"coalesce(cast({c} AS STRING), '')" for c in HISTORY_COLUMNS)
        + "), 256)"
    )
    current = spark.sql(
        f"""
        SELECT organisasjonsnummer, {columns}, {hash_expr} AS row_hash, snapshot_date
        FROM {silver} WHERE snapshot_id = {int(snapshot_id)}
        """
    )
    current.createOrReplaceTempView("history_current")
    snapshot_date = current.select(F.max("snapshot_date")).first()[0]
    if snapshot_date is None:
        raise ValueError(f"silver enheter has no rows for snapshot {snapshot_id}")
    date_literal = f"DATE '{snapshot_date.isoformat()}'"
    history_columns = (
        f"organisasjonsnummer, {columns}, row_hash, valid_from_snapshot, valid_to_snapshot, "
        "valid_from_date, valid_to_date, is_current"
    )
    if not table_exists(spark, history):
        spark.sql(
            f"""
            CREATE TABLE {history} USING DELTA AS
            SELECT organisasjonsnummer, {columns}, row_hash,
                   CAST(NULL AS INT) AS valid_from_snapshot, CAST(NULL AS INT) AS valid_to_snapshot,
                   CAST(NULL AS DATE) AS valid_from_date, CAST(NULL AS DATE) AS valid_to_date,
                   CAST(true AS BOOLEAN) AS is_current
            FROM history_current WHERE 1 = 0
            """
        )
    # Undo any earlier processing of this snapshot, so a rerun gives the same result.
    spark.sql(f"DELETE FROM {history} WHERE valid_from_snapshot = {int(snapshot_id)}")
    spark.sql(
        f"UPDATE {history} SET valid_to_snapshot = NULL, valid_to_date = NULL, is_current = true "
        f"WHERE valid_to_snapshot = {int(snapshot_id)}"
    )
    spark.sql(
        f"""
        MERGE INTO {history} AS h
        USING history_current AS n
        ON h.organisasjonsnummer = n.organisasjonsnummer AND h.is_current
        WHEN MATCHED AND h.row_hash <> n.row_hash THEN UPDATE SET
          h.valid_to_snapshot = {int(snapshot_id)}, h.valid_to_date = {date_literal},
          h.is_current = false
        WHEN NOT MATCHED BY SOURCE AND h.is_current THEN UPDATE SET
          h.valid_to_snapshot = {int(snapshot_id)}, h.valid_to_date = {date_literal},
          h.is_current = false
        """
    )
    spark.sql(
        f"""
        INSERT INTO {history} ({history_columns})
        SELECT n.organisasjonsnummer, {", ".join("n." + c for c in HISTORY_COLUMNS)}, n.row_hash,
               {int(snapshot_id)}, CAST(NULL AS INT), n.snapshot_date, CAST(NULL AS DATE), true
        FROM history_current n
        LEFT ANTI JOIN {history} h
          ON h.organisasjonsnummer = n.organisasjonsnummer AND h.is_current
        """
    )
    stats = spark.sql(
        f"""
        SELECT count(*) AS rows_total,
               sum(CASE WHEN is_current THEN 1 ELSE 0 END) AS rows_current,
               sum(CASE WHEN valid_from_snapshot = {int(snapshot_id)} THEN 1 ELSE 0 END) AS opened,
               sum(CASE WHEN valid_to_snapshot = {int(snapshot_id)} THEN 1 ELSE 0 END) AS closed
        FROM {history}
        """
    ).first()
    summary = {k: int(stats[k] or 0) for k in ("rows_total", "rows_current", "opened", "closed")}
    log.info("silver history snapshot %d: %s", snapshot_id, summary)
    return summary
