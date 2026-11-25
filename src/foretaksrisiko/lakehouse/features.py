"""Gold features: one row per company per (design, reference snapshot), known at the reference time.

Masking rule: a value that may have changed after the reference time T is set to null and the
matching ``masked_*`` column is true. Those columns exist so the model stage can impute without
learning from them; they must never be model inputs, because missingness caused by changes after
T carries information about the outcome.
"""

from __future__ import annotations

import logging
from datetime import date

from foretaksrisiko.acquire.history import EVENTS_SCHEMA, ROLE_EVENTS_SCHEMA
from foretaksrisiko.acquire.regnskap import NUMERIC_PATHS
from foretaksrisiko.config import DesignConfig
from foretaksrisiko.lakehouse.gold import ddl_from_arrow
from foretaksrisiko.lakehouse.labels import add_months, reference_date, snapshot_dates
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, table_exists, write_partitions

log = logging.getLogger(__name__)

# Register fields whose later change masks the current value (field name in the register JSON).
MASKED_FIELDS = {
    "antallAnsatte": "antall_ansatte",
    "harRegistrertAntallAnsatte": "har_registrert_antall_ansatte",
    "forretningsadresse": "adresse",
    "naeringskode1": "naeringskode1",
    "kapital": "kapital",
    "registrertIMvaregisteret": "mva",
    "erIKonsern": "er_i_konsern",
    "vedtektsfestetFormaal": "formaal",
    "aktivitet": "aktivitet",
    "hjelpeenhetskode": "hjelpeenhetskode",
    "institusjonellSektorkode": "sektorkode",
}
COUNTED_FIELDS = {
    "forretningsadresse": "address",
    "navn": "name",
    "naeringskode1": "nace",
    "kapital": "kapital",
}

ACCOUNT_NUMERIC = list(NUMERIC_PATHS)
RATIO_FEATURES = [
    "equity_ratio",
    "debt_ratio",
    "operating_margin",
    "return_on_assets",
    "current_ratio",
    "cash_ratio",
    "interest_burden",
    "log_revenue",
    "log_assets",
    "revenue_growth",
    "asset_growth",
    "log_kapital",
    "age_years",
    "board_size",
]
ACCOUNT_OUTPUT = (
    [
        "acc_fiscal_year",
        "acc_period_days",
        "acc_oppstillingsplan",
        "acc_ikke_revidert",
        "acc_fravalg_revisjon",
        "acc_smaa_foretak",
        "acc_regnskapsregler",
        "acc_morselskap",
        "acc_avviklingsregnskap",
    ]
    + [f"acc_{c}" for c in ACCOUNT_NUMERIC]
    + [
        "acc_age_days",
        "acc_filing_lag_days",
        "acc_prev_fiscal_year",
        "acc_prev_sum_driftsinntekter",
        "acc_prev_driftsresultat",
        "acc_prev_aarsresultat",
        "acc_prev_sum_eiendeler",
        "acc_prev_sum_egenkapital",
        "acc_prev_sum_gjeld",
        "acc_n_statements_known",
    ]
)


def _lit(day: date) -> str:
    return f"DATE '{day.isoformat()}'"


def _changes_sql(events: str, t: date, cfg: DesignConfig) -> str:
    t_lit = _lit(t)
    masked = ",\n".join(
        f"max(CASE WHEN d > {t_lit} AND array_contains(fields, '{field}') THEN true ELSE false END)"
        f" AS masked_{alias}"
        for field, alias in MASKED_FIELDS.items()
    )
    windows = []
    for months in cfg.change_windows_months:
        start = _lit(add_months(t, -months))
        windows.append(
            f"sum(CASE WHEN d > {start} AND d <= {t_lit} AND endringstype = 'Endring' THEN 1 ELSE 0 END)"
            f" AS n_changes_{months}m"
        )
        for field, alias in COUNTED_FIELDS.items():
            windows.append(
                f"sum(CASE WHEN d > {start} AND d <= {t_lit} AND array_contains(fields, '{field}')"
                f" THEN 1 ELSE 0 END) AS n_{alias}_changes_{months}m"
            )
    return f"""
        SELECT organisasjonsnummer,
               {masked},
               {",".join(windows)},
               sum(CASE WHEN d > {t_lit} AND array_contains(fields, 'navn') THEN 1 ELSE 0 END)
                 AS n_name_changes_after_t,
               max(CASE WHEN d > {t_lit} THEN true ELSE false END) AS any_change_after_t
        FROM (SELECT DISTINCT organisasjonsnummer, oppdateringsid, endringstype,
                     to_date(substr(dato, 1, 10)) AS d,
                     coalesce(split(changed_fields, ';'), array()) AS fields
              FROM {events})
        GROUP BY organisasjonsnummer
    """


def build_features(spark, names: Names, cfg: DesignConfig, snapshot_id: int, design: str) -> dict:
    """Build gold.features and gold.peer_stats for one design and one reference snapshot."""
    from pyspark.sql import functions as F

    ensure_schemas(spark, names, ("gold",))
    s = names.table
    dates = snapshot_dates(spark, names)
    snapshot_date = dates[snapshot_id]
    t = reference_date(design, snapshot_date, cfg)
    t_lit = _lit(t)
    deadline_expr = (
        f"make_date(r.fiscal_year + 1, {cfg.filing_deadline_month}, {cfg.filing_deadline_day})"
    )
    lookback_lit = _lit(add_months(t, -cfg.adverse_lookback_months))
    twelve = _lit(add_months(t, -12))

    def view(name: str, sql: str) -> None:
        spark.sql(f"CREATE OR REPLACE TEMP VIEW {name} AS {sql}")

    view("f_base", f"SELECT * FROM {s('silver', 'enheter')} WHERE snapshot_id = {snapshot_id}")

    if table_exists(spark, s("silver", "events_enheter")):
        view("f_changes", _changes_sql(s("silver", "events_enheter"), t, cfg))
        view(
            "f_filings",
            f"""
            SELECT organisasjonsnummer, siste_innsendte_aarsregnskap AS fiscal_year,
                   min(to_date(substr(dato, 1, 10))) AS filing_date
            FROM {s("silver", "events_enheter")}
            WHERE siste_innsendte_aarsregnskap IS NOT NULL
            GROUP BY organisasjonsnummer, siste_innsendte_aarsregnskap
            """,
        )
    else:
        spark.createDataFrame([], ddl_from_arrow(EVENTS_SCHEMA)).createOrReplaceTempView(
            "f_events_empty"
        )
        view("f_changes", _changes_sql("f_events_empty", t, cfg))
        view(
            "f_filings",
            "SELECT organisasjonsnummer, CAST(NULL AS INT) AS fiscal_year, "
            "CAST(NULL AS DATE) AS filing_date FROM f_base WHERE 1 = 0",
        )

    if table_exists(spark, s("silver", "events_roller")):
        role_windows = ", ".join(
            f"sum(CASE WHEN d > {_lit(add_months(t, -m))} AND d <= {t_lit} THEN 1 ELSE 0 END) AS n_role_events_{m}m"
            for m in cfg.change_windows_months
        )
        view(
            "f_role_events",
            f"""
            SELECT organisasjonsnummer, {role_windows}
            FROM (SELECT DISTINCT organisasjonsnummer, event_id, to_date(substr(time, 1, 10)) AS d
                  FROM {s("silver", "events_roller")})
            GROUP BY organisasjonsnummer
            """,
        )
    else:
        spark.createDataFrame([], ddl_from_arrow(ROLE_EVENTS_SCHEMA)).createOrReplaceTempView(
            "f_role_events_empty"
        )
        cols = ", ".join(
            f"CAST(NULL AS BIGINT) AS n_role_events_{m}m" for m in cfg.change_windows_months
        )
        view("f_role_events", f"SELECT organisasjonsnummer, {cols} FROM f_role_events_empty")

    account_cols = ", ".join(f"r.{c}" for c in ACCOUNT_NUMERIC)
    view(
        "f_statements",
        f"""
        SELECT r.organisasjonsnummer, r.regnskap_id, r.fiscal_year, r.regnskapsperiode_fra_dato,
               r.regnskapsperiode_til_dato, r.period_days, r.valuta, r.avviklingsregnskap,
               r.oppstillingsplan, r.ikke_revidert_aarsregnskap, r.fravalg_revisjon, r.smaa_foretak,
               r.regnskapsregler, r.morselskap, {account_cols},
               f.filing_date,
               row_number() OVER (PARTITION BY r.organisasjonsnummer
                                  ORDER BY r.regnskapsperiode_til_dato DESC, r.regnskap_id DESC) AS rn
        FROM {s("silver", "regnskap")} r
        LEFT JOIN f_filings f
          ON f.organisasjonsnummer = r.organisasjonsnummer AND f.fiscal_year = r.fiscal_year
        WHERE r.snapshot_id = {snapshot_id} AND r.regnskapstype = 'SELSKAP'
          AND r.regnskapsperiode_til_dato <= {t_lit}
          AND ({t_lit} >= {deadline_expr} OR (f.filing_date IS NOT NULL AND f.filing_date <= {t_lit}))
        """,
    )
    view(
        "f_acc",
        f"""
        SELECT a.organisasjonsnummer,
               a.fiscal_year AS acc_fiscal_year, a.period_days AS acc_period_days,
               a.oppstillingsplan AS acc_oppstillingsplan, a.ikke_revidert_aarsregnskap AS acc_ikke_revidert,
               a.fravalg_revisjon AS acc_fravalg_revisjon, a.smaa_foretak AS acc_smaa_foretak,
               a.regnskapsregler AS acc_regnskapsregler, a.morselskap AS acc_morselskap,
               a.avviklingsregnskap AS acc_avviklingsregnskap,
               {", ".join(f"a.{c} AS acc_{c}" for c in ACCOUNT_NUMERIC)},
               datediff({t_lit}, a.regnskapsperiode_til_dato) AS acc_age_days,
               datediff(a.filing_date, a.regnskapsperiode_til_dato) AS acc_filing_lag_days,
               p.fiscal_year AS acc_prev_fiscal_year,
               p.sum_driftsinntekter AS acc_prev_sum_driftsinntekter,
               p.driftsresultat AS acc_prev_driftsresultat,
               p.aarsresultat AS acc_prev_aarsresultat,
               p.sum_eiendeler AS acc_prev_sum_eiendeler,
               p.sum_egenkapital AS acc_prev_sum_egenkapital,
               p.sum_gjeld AS acc_prev_sum_gjeld,
               n.n_statements AS acc_n_statements_known
        FROM f_statements a
        LEFT JOIN f_statements p ON p.organisasjonsnummer = a.organisasjonsnummer AND p.rn = 2
        LEFT JOIN (SELECT organisasjonsnummer, count(*) AS n_statements FROM f_statements
                   GROUP BY organisasjonsnummer) n ON n.organisasjonsnummer = a.organisasjonsnummer
        WHERE a.rn = 1
        """,
    )

    def masked(group: str, column: str) -> str:
        return f"CASE WHEN r.{group}_sist_endret > {t_lit} THEN NULL ELSE r.{column} END"

    view(
        "f_roles",
        f"""
        SELECT r.organisasjonsnummer,
               {masked("styr", "board_size")} AS board_size,
               {masked("styr", "n_board_chair")} AS n_board_chair,
               {masked("styr", "n_board_deputy_chair")} AS n_board_deputy_chair,
               {masked("styr", "n_board_members")} AS n_board_members,
               {masked("styr", "n_deputy_members")} AS n_deputy_members,
               {masked("styr", "n_observers")} AS n_observers,
               {masked("styr", "has_chair")} AS has_chair,
               {masked("styr", "n_roles_valgt_av")} AS n_roles_valgt_av,
               {masked("dagl", "n_ceo")} AS n_ceo,
               {masked("dagl", "has_ceo")} AS has_ceo,
               CASE WHEN r.styr_sist_endret > {t_lit} OR r.dagl_sist_endret > {t_lit} THEN NULL
                    ELSE r.ceo_is_chair END AS ceo_is_chair,
               {masked("revi", "has_auditor")} AS has_auditor,
               {masked("regn", "has_accountant")} AS has_accountant,
               {masked("kont", "has_contact_person")} AS has_contact_person,
               CASE WHEN greatest(r.styr_sist_endret, r.dagl_sist_endret, r.revi_sist_endret,
                                  r.regn_sist_endret, r.kont_sist_endret) > {t_lit} THEN NULL
                    ELSE r.n_person_roleholders END AS n_person_roleholders,
               CASE WHEN greatest(r.styr_sist_endret, r.dagl_sist_endret, r.revi_sist_endret,
                                  r.regn_sist_endret, r.kont_sist_endret) > {t_lit} THEN NULL
                    ELSE r.n_distinct_persons END AS n_distinct_persons,
               CASE WHEN greatest(r.styr_sist_endret, r.dagl_sist_endret, r.revi_sist_endret,
                                  r.regn_sist_endret, r.kont_sist_endret) > {t_lit} THEN NULL
                    ELSE r.n_deceased_roleholders END AS n_deceased_roleholders,
               CASE WHEN greatest(r.styr_sist_endret, r.dagl_sist_endret, r.revi_sist_endret,
                                  r.regn_sist_endret, r.kont_sist_endret) > {t_lit} THEN NULL
                    ELSE r.n_org_roleholders END AS n_org_roleholders,
               CASE WHEN greatest(r.styr_sist_endret, r.dagl_sist_endret, r.revi_sist_endret,
                                  r.regn_sist_endret, r.kont_sist_endret) > {t_lit} THEN NULL
                    ELSE r.n_deregistered_roles END AS n_deregistered_roles,
               CASE WHEN r.styr_sist_endret <= {t_lit} THEN datediff({t_lit}, r.styr_sist_endret) END
                 AS days_since_board_change,
               CASE WHEN r.dagl_sist_endret <= {t_lit} THEN datediff({t_lit}, r.dagl_sist_endret) END
                 AS days_since_ceo_change,
               r.styr_sist_endret > {t_lit} AS masked_board,
               r.dagl_sist_endret > {t_lit} AS masked_ceo,
               r.revi_sist_endret > {t_lit} AS masked_auditor,
               r.regn_sist_endret > {t_lit} AS masked_accountant,
               coalesce(greatest(r.styr_sist_endret, r.dagl_sist_endret, r.revi_sist_endret,
                                 r.regn_sist_endret, r.kont_sist_endret) > {t_lit}, false)
                 AS masked_roles_any
        FROM {s("silver", "roller_counts")} r WHERE r.snapshot_id = {snapshot_id}
        """,
    )

    view(
        "f_sub",
        f"""
        SELECT overordnet_enhet AS organisasjonsnummer,
               sum(CASE WHEN (oppstartsdato IS NULL OR oppstartsdato <= {t_lit})
                             AND (registreringsdato_enhetsregisteret IS NULL
                                  OR registreringsdato_enhetsregisteret <= {t_lit})
                             AND (nedleggelsesdato IS NULL OR nedleggelsesdato > {t_lit}) THEN 1 ELSE 0 END)
                 AS n_sub_units,
               count(DISTINCT CASE WHEN (oppstartsdato IS NULL OR oppstartsdato <= {t_lit})
                                        AND (nedleggelsesdato IS NULL OR nedleggelsesdato > {t_lit})
                                   THEN beliggenhetsadresse_kommunenummer END) AS n_sub_unit_municipalities,
               sum(CASE WHEN oppstartsdato > {twelve} AND oppstartsdato <= {t_lit} THEN 1 ELSE 0 END)
                 AS n_sub_units_opened_12m,
               sum(CASE WHEN nedleggelsesdato > {twelve} AND nedleggelsesdato <= {t_lit} THEN 1 ELSE 0 END)
                 AS n_sub_units_closed_12m,
               sum(CASE WHEN dato_eierskifte > {twelve} AND dato_eierskifte <= {t_lit} THEN 1 ELSE 0 END)
                 AS n_ownership_changes_12m
        FROM {s("silver", "underenheter")} WHERE snapshot_id = {snapshot_id}
        GROUP BY overordnet_enhet
        """,
    )

    view(
        "f_links",
        f"""
        SELECT l.organisasjonsnummer, l.rolletype, min(l.rolleholder_organisasjonsnummer) AS holder
        FROM {s("silver", "roller_links")} l
        WHERE l.snapshot_id = {snapshot_id} AND NOT l.avregistrert AND l.rolletype IN ('REVI', 'REGN')
        GROUP BY l.organisasjonsnummer, l.rolletype
        """,
    )
    view(
        "f_portfolio",
        f"""
        SELECT l.rolletype, l.holder,
               count(*) AS portfolio_size,
               sum(CASE WHEN (o.first_bankruptcy_date > {lookback_lit} AND o.first_bankruptcy_date <= {t_lit})
                          OR (o.first_forced_date > {lookback_lit} AND o.first_forced_date <= {t_lit})
                        THEN 1 ELSE 0 END) AS adverse_clients
        FROM f_links l
        LEFT JOIN {s("gold", "outcomes")} o ON o.organisasjonsnummer = l.organisasjonsnummer
        GROUP BY l.rolletype, l.holder
        """,
    )
    view(
        "f_net",
        f"""
        SELECT b.organisasjonsnummer,
               a.holder AS auditor_orgnr, pa.portfolio_size AS auditor_portfolio_size,
               CASE WHEN pa.portfolio_size > 1 THEN
                 (pa.adverse_clients - CASE WHEN (oa.first_bankruptcy_date > {lookback_lit}
                                                   AND oa.first_bankruptcy_date <= {t_lit})
                                                 OR (oa.first_forced_date > {lookback_lit}
                                                     AND oa.first_forced_date <= {t_lit})
                                            THEN 1 ELSE 0 END) / (pa.portfolio_size - 1) END
                 AS auditor_other_clients_adverse_share,
               c.holder AS accountant_orgnr, pc.portfolio_size AS accountant_portfolio_size,
               CASE WHEN pc.portfolio_size > 1 THEN
                 (pc.adverse_clients - CASE WHEN (oa.first_bankruptcy_date > {lookback_lit}
                                                   AND oa.first_bankruptcy_date <= {t_lit})
                                                 OR (oa.first_forced_date > {lookback_lit}
                                                     AND oa.first_forced_date <= {t_lit})
                                            THEN 1 ELSE 0 END) / (pc.portfolio_size - 1) END
                 AS accountant_other_clients_adverse_share
        FROM f_base b
        LEFT JOIN f_links a ON a.organisasjonsnummer = b.organisasjonsnummer AND a.rolletype = 'REVI'
        LEFT JOIN f_portfolio pa ON pa.rolletype = 'REVI' AND pa.holder = a.holder
        LEFT JOIN f_links c ON c.organisasjonsnummer = b.organisasjonsnummer AND c.rolletype = 'REGN'
        LEFT JOIN f_portfolio pc ON pc.rolletype = 'REGN' AND pc.holder = c.holder
        LEFT JOIN {s("gold", "outcomes")} oa ON oa.organisasjonsnummer = b.organisasjonsnummer
        """,
    )

    if table_exists(spark, s("silver", "text_features")):
        view(
            "f_text",
            f"SELECT * FROM {s('silver', 'text_features')} WHERE snapshot_id = {snapshot_id}",
        )
    else:
        view(
            "f_text",
            "SELECT organisasjonsnummer, CAST(NULL AS INT) AS text_chars, CAST(NULL AS DOUBLE) AS text_sim_own_code,"
            " CAST(NULL AS DOUBLE) AS text_sim_best, CAST(NULL AS INT) AS text_rank_own_code,"
            " CAST(NULL AS DOUBLE) AS text_sim_section FROM f_base WHERE 1 = 0",
        )

    assembled = spark.sql(
        f"""
        SELECT
          '{design}' AS design, {snapshot_id} AS reference_snapshot_id, {t_lit} AS reference_date,
          b.organisasjonsnummer,
          b.organisasjonsform = 'ASA' AS is_asa,
          round(months_between({t_lit},
                coalesce(b.stiftelsesdato, b.registreringsdato_enhetsregisteret)) / 12, 2) AS age_years,
          round(months_between({t_lit}, b.registreringsdato_enhetsregisteret) / 12, 2) AS years_registered,
          CASE WHEN c.masked_kapital OR b.kapital_innfort_dato > {t_lit} THEN NULL ELSE b.kapital_belop END
            AS kapital_belop,
          CASE WHEN c.masked_kapital OR b.kapital_innfort_dato > {t_lit} THEN NULL
               ELSE log(1 + greatest(b.kapital_belop, 0)) END AS log_kapital,
          CASE WHEN c.masked_antall_ansatte OR b.registreringsdato_antall_ansatte_nav > {t_lit} THEN NULL
               ELSE b.antall_ansatte END AS antall_ansatte,
          CASE WHEN c.masked_har_registrert_antall_ansatte THEN NULL
               ELSE b.har_registrert_antall_ansatte END AS har_registrert_antall_ansatte,
          CASE WHEN c.masked_naeringskode1 THEN NULL ELSE b.nace_section END AS nace_section,
          CASE WHEN c.masked_naeringskode1 THEN NULL ELSE b.nace_division END AS nace_division,
          CASE WHEN c.masked_naeringskode1 THEN NULL ELSE b.nace_sn2025 END AS nace_sn2025,
          CASE WHEN c.masked_naeringskode1 THEN NULL ELSE b.nace_code IS NULL END AS nace_missing,
          CASE WHEN c.masked_adresse THEN NULL ELSE b.fylke_code END AS fylke_code,
          CASE WHEN c.masked_adresse THEN NULL ELSE b.forretningsadresse_kommunenummer END AS kommunenummer,
          CASE WHEN c.masked_adresse THEN NULL
               ELSE b.postadresse_kommunenummer IS NOT NULL
                    AND b.postadresse_kommunenummer <> b.forretningsadresse_kommunenummer END
            AS post_address_other_municipality,
          CASE WHEN b.registreringsdato_mvaregisteret > {t_lit} THEN false
               WHEN c.masked_mva THEN NULL ELSE b.registrert_i_mvaregisteret END AS registrert_i_mvaregisteret,
          CASE WHEN b.registreringsdato_foretaksregisteret IS NOT NULL
               THEN b.registreringsdato_foretaksregisteret <= {t_lit}
               ELSE b.registrert_i_foretaksregisteret END AS registrert_i_foretaksregisteret,
          b.fravalg_revisjon_dato IS NOT NULL AND b.fravalg_revisjon_dato <= {t_lit} AS fravalg_revisjon,
          CASE WHEN c.masked_er_i_konsern THEN NULL ELSE b.er_i_konsern END AS er_i_konsern,
          greatest(b.antall_historiske_navn - coalesce(c.n_name_changes_after_t, 0), 0)
            AS antall_historiske_navn,
          b.antall_paategninger, b.har_hjemmeside, b.har_epostadresse, b.har_telefon,
          b.maalform = 'Nynorsk' AS maalform_nynorsk,
          CASE WHEN c.masked_sektorkode THEN NULL ELSE b.institusjonell_sektorkode END AS institusjonell_sektorkode,
          coalesce(c.n_changes_6m, 0) AS n_changes_6m, coalesce(c.n_changes_12m, 0) AS n_changes_12m,
          coalesce(c.n_address_changes_12m, 0) AS n_address_changes_12m,
          coalesce(c.n_name_changes_12m, 0) AS n_name_changes_12m,
          coalesce(c.n_nace_changes_12m, 0) AS n_nace_changes_12m,
          coalesce(c.n_kapital_changes_12m, 0) AS n_kapital_changes_12m,
          coalesce(re.n_role_events_6m, 0) AS n_role_events_6m,
          coalesce(re.n_role_events_12m, 0) AS n_role_events_12m,
          r.board_size, r.n_board_chair, r.n_board_deputy_chair, r.n_board_members, r.n_deputy_members,
          r.n_observers, r.has_chair, r.n_roles_valgt_av, r.n_ceo, r.has_ceo, r.ceo_is_chair,
          r.has_auditor, r.has_accountant, r.has_contact_person, r.n_person_roleholders,
          r.n_distinct_persons, r.n_deceased_roleholders, r.n_org_roleholders, r.n_deregistered_roles,
          r.days_since_board_change, r.days_since_ceo_change,
          coalesce(sub.n_sub_units, 0) AS n_sub_units,
          coalesce(sub.n_sub_unit_municipalities, 0) AS n_sub_unit_municipalities,
          coalesce(sub.n_sub_units_opened_12m, 0) AS n_sub_units_opened_12m,
          coalesce(sub.n_sub_units_closed_12m, 0) AS n_sub_units_closed_12m,
          coalesce(sub.n_ownership_changes_12m, 0) AS n_ownership_changes_12m,
          CASE WHEN r.masked_auditor THEN NULL ELSE n.auditor_portfolio_size END AS auditor_portfolio_size,
          CASE WHEN r.masked_auditor THEN NULL ELSE n.auditor_other_clients_adverse_share END
            AS auditor_other_clients_adverse_share,
          CASE WHEN r.masked_auditor THEN NULL ELSE r.has_auditor AND n.auditor_orgnr IS NULL END
            AS auditor_outside_population,
          CASE WHEN r.masked_accountant THEN NULL ELSE n.accountant_portfolio_size END
            AS accountant_portfolio_size,
          CASE WHEN r.masked_accountant THEN NULL ELSE n.accountant_other_clients_adverse_share END
            AS accountant_other_clients_adverse_share,
          a.organisasjonsnummer IS NOT NULL AS has_accounts,
          {", ".join("a." + c for c in ACCOUNT_OUTPUT)},
          CASE WHEN c.masked_formaal OR c.masked_aktivitet THEN NULL ELSE tx.text_chars END AS text_chars,
          CASE WHEN c.masked_formaal OR c.masked_aktivitet OR c.masked_naeringskode1 THEN NULL
               ELSE tx.text_sim_own_code END AS text_sim_own_code,
          CASE WHEN c.masked_formaal OR c.masked_aktivitet THEN NULL ELSE tx.text_sim_best END AS text_sim_best,
          CASE WHEN c.masked_formaal OR c.masked_aktivitet OR c.masked_naeringskode1 THEN NULL
               ELSE tx.text_rank_own_code END AS text_rank_own_code,
          CASE WHEN c.masked_formaal OR c.masked_aktivitet OR c.masked_naeringskode1 THEN NULL
               ELSE tx.text_sim_section END AS text_sim_section,
          coalesce(c.masked_kapital, false) OR coalesce(b.kapital_innfort_dato > {t_lit}, false)
            AS masked_kapital,
          coalesce(c.masked_antall_ansatte, false)
            OR coalesce(b.registreringsdato_antall_ansatte_nav > {t_lit}, false) AS masked_antall_ansatte,
          coalesce(c.masked_naeringskode1, false) AS masked_naeringskode1,
          coalesce(c.masked_adresse, false) AS masked_adresse,
          coalesce(c.masked_mva, false) AS masked_mva,
          coalesce(c.masked_er_i_konsern, false) AS masked_er_i_konsern,
          coalesce(c.masked_formaal, false) OR coalesce(c.masked_aktivitet, false) AS masked_text,
          coalesce(r.masked_board, false) AS masked_board,
          coalesce(r.masked_ceo, false) AS masked_ceo,
          coalesce(r.masked_auditor, false) AS masked_auditor,
          coalesce(r.masked_accountant, false) AS masked_accountant,
          coalesce(r.masked_roles_any, false) AS masked_roles_any,
          coalesce(c.any_change_after_t, false) AS any_change_after_t
        FROM f_base b
        LEFT JOIN f_changes c ON c.organisasjonsnummer = b.organisasjonsnummer
        LEFT JOIN f_role_events re ON re.organisasjonsnummer = b.organisasjonsnummer
        LEFT JOIN f_roles r ON r.organisasjonsnummer = b.organisasjonsnummer
        LEFT JOIN f_sub sub ON sub.organisasjonsnummer = b.organisasjonsnummer
        LEFT JOIN f_net n ON n.organisasjonsnummer = b.organisasjonsnummer
        LEFT JOIN f_acc a ON a.organisasjonsnummer = b.organisasjonsnummer
        LEFT JOIN f_text tx ON tx.organisasjonsnummer = b.organisasjonsnummer
        """
    )
    ratios = assembled.selectExpr(
        "*",
        "CASE WHEN acc_sum_eiendeler > 0 THEN acc_sum_egenkapital / acc_sum_eiendeler END AS equity_ratio",
        "CASE WHEN acc_sum_eiendeler > 0 THEN acc_sum_gjeld / acc_sum_eiendeler END AS debt_ratio",
        "CASE WHEN acc_sum_driftsinntekter > 0 THEN acc_driftsresultat / acc_sum_driftsinntekter END"
        " AS operating_margin",
        "CASE WHEN acc_sum_eiendeler > 0 THEN acc_aarsresultat / acc_sum_eiendeler END AS return_on_assets",
        "CASE WHEN acc_sum_kortsiktig_gjeld > 0 THEN acc_sum_omloepsmidler / acc_sum_kortsiktig_gjeld END"
        " AS current_ratio",
        "CASE WHEN acc_sum_kortsiktig_gjeld > 0 THEN acc_sum_bankinnskudd_og_kontanter / acc_sum_kortsiktig_gjeld END"
        " AS cash_ratio",
        "CASE WHEN acc_sum_driftsinntekter > 0 THEN acc_sum_finanskostnad / acc_sum_driftsinntekter END"
        " AS interest_burden",
        "CASE WHEN acc_sum_driftsinntekter IS NOT NULL THEN log(1 + greatest(acc_sum_driftsinntekter, 0)) END"
        " AS log_revenue",
        "CASE WHEN acc_sum_eiendeler IS NOT NULL THEN log(1 + greatest(acc_sum_eiendeler, 0)) END AS log_assets",
        "CASE WHEN acc_prev_sum_driftsinntekter > 0 THEN"
        " (acc_sum_driftsinntekter - acc_prev_sum_driftsinntekter) / acc_prev_sum_driftsinntekter END"
        " AS revenue_growth",
        "CASE WHEN acc_prev_sum_eiendeler > 0 THEN (acc_sum_eiendeler - acc_prev_sum_eiendeler) / acc_prev_sum_eiendeler END"
        " AS asset_growth",
        "acc_sum_egenkapital IS NOT NULL AND acc_sum_egenkapital < 0 AS negative_equity",
        "acc_sum_driftsinntekter IS NOT NULL AND acc_sum_driftsinntekter <= 0 AS zero_revenue",
        "acc_aarsresultat IS NOT NULL AND acc_aarsresultat < 0 AS loss",
    )
    ratios.createOrReplaceTempView("f_ratios")

    # Size bands on log total assets; band 0 means no accounts known at T.
    quantiles = (
        spark.sql(
            f"SELECT percentile_approx(log_assets, array({', '.join(str(q) for q in cfg.size_band_quantiles)}), 10000)"
            " AS q FROM f_ratios WHERE log_assets IS NOT NULL"
        ).first()["q"]
        or []
    )
    band_case = " ".join(f"WHEN log_assets <= {q} THEN '{i + 1}'" for i, q in enumerate(quantiles))
    last_band = len(quantiles) + 1
    with_band = spark.sql(
        f"""
        SELECT *, CASE WHEN log_assets IS NULL THEN '0' {band_case} ELSE '{last_band}' END AS size_band
        FROM f_ratios
        """
    )
    with_band.createOrReplaceTempView("f_band")
    peers = spark.sql(
        f"""
        WITH d AS (SELECT concat(coalesce(nace_division, '??'), '|', size_band) AS g, count(*) AS n
                   FROM f_band GROUP BY 1),
             sct AS (SELECT concat(coalesce(nace_section, 'X'), '|', size_band) AS g, count(*) AS n
                     FROM f_band GROUP BY 1)
        SELECT b.*,
               CASE WHEN d.n >= {cfg.peer_min_size} THEN 'division:' || d.g
                    WHEN sct.n >= {cfg.peer_min_size} THEN 'section:' || sct.g
                    ELSE 'all:' || b.size_band END AS peer_group
        FROM f_band b
        LEFT JOIN d ON d.g = concat(coalesce(b.nace_division, '??'), '|', b.size_band)
        LEFT JOIN sct ON sct.g = concat(coalesce(b.nace_section, 'X'), '|', b.size_band)
        """
    )
    peers.createOrReplaceTempView("f_peers")

    # Robust z-scores and percentile ranks within peer groups: three flat aggregations, one join.
    med_exprs = ", ".join(
        f"percentile_approx({f}, 0.5, 10000) AS med_{f}, count({f}) AS n_{f}"
        for f in RATIO_FEATURES
    )
    view("f_med", f"SELECT peer_group, {med_exprs} FROM f_peers GROUP BY peer_group")
    dev_exprs = ", ".join(f"abs(p.{f} - m.med_{f}) AS dev_{f}" for f in RATIO_FEATURES)
    view(
        "f_dev", f"SELECT p.peer_group, {dev_exprs} FROM f_peers p JOIN f_med m USING (peer_group)"
    )
    mad_exprs = ", ".join(
        f"percentile_approx(dev_{f}, 0.5, 10000) AS mad_{f}" for f in RATIO_FEATURES
    )
    view("f_mad", f"SELECT peer_group, {mad_exprs} FROM f_dev GROUP BY peer_group")
    z_exprs = ", ".join(
        f"CASE WHEN m2.mad_{f} > 0 THEN (p.{f} - m.med_{f}) / (1.4826 * m2.mad_{f}) END AS z_{f}, "
        f"CASE WHEN p.{f} IS NOT NULL THEN percent_rank() OVER "
        f"(PARTITION BY p.peer_group, p.{f} IS NULL ORDER BY p.{f}) END AS pct_{f}"
        for f in RATIO_FEATURES
    )
    extreme_sum = " + ".join(
        f"CASE WHEN abs(z_{f}) > {cfg.extreme_z} THEN 1 ELSE 0 END" for f in RATIO_FEATURES
    )
    current = spark.sql(
        f"""
        SELECT *, ({extreme_sum}) AS n_extreme_z FROM (
          SELECT p.*, {z_exprs}
          FROM f_peers p
          LEFT JOIN f_med m USING (peer_group)
          LEFT JOIN f_mad m2 USING (peer_group)
        )
        """
    )
    stack_args = ", ".join(
        f"'{f}', CAST(n_{f} AS BIGINT), CAST(med_{f} AS DOUBLE), CAST(mad_{f} AS DOUBLE)"
        for f in RATIO_FEATURES
    )
    stats = spark.sql(
        f"""
        SELECT peer_group, stack({len(RATIO_FEATURES)}, {stack_args}) AS (feature, n, median, mad)
        FROM f_med JOIN f_mad USING (peer_group)
        """
    )

    where = f"design = '{design}' AND reference_snapshot_id = {snapshot_id}"
    write_partitions(current, s("gold", "features"), ["design", "reference_snapshot_id"], where)
    stats = stats.select(
        F.lit(design).alias("design"),
        F.lit(snapshot_id).alias("reference_snapshot_id"),
        F.lit(t).alias("reference_date"),
        "peer_group",
        "feature",
        F.col("n").cast("long"),
        "median",
        "mad",
    )
    write_partitions(stats, s("gold", "peer_stats"), ["design", "reference_snapshot_id"], where)
    rows = spark.table(s("gold", "features")).where(where).count()
    summary = {
        "design": design,
        "reference_snapshot_id": snapshot_id,
        "reference_date": t.isoformat(),
        "rows": rows,
        "size_band_cuts": [round(float(q), 3) for q in quantiles],
        "peer_groups": spark.table(s("gold", "peer_stats"))
        .where(where)
        .select("peer_group")
        .distinct()
        .count(),
    }
    log.info("gold features: %s", summary)
    return summary
