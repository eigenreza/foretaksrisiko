"""Bilingual text for figures and the demo: model, ablation, feature and group names, labels.

Every human-readable string that can appear in a figure or in the demo lives here, keyed by a
short identifier and stored in both Norwegian bokmål ("no") and English ("en"). ``Labels``
resolves a key, a model name, an ablation name, a feature identifier or a group type for one
language. The module imports nothing beyond the standard library, so the demo can use it
without matplotlib.
"""

from __future__ import annotations

LANGUAGES = ("no", "en")

MODEL_ORDER = ("rule", "isolation_forest", "mahalanobis", "hgb_calibrated")
MODEL_NAMES: dict[str, dict[str, str]] = {
    "rule": {"no": "Regelbasert referanse", "en": "Rule baseline"},
    "isolation_forest": {"no": "Isolation Forest", "en": "Isolation Forest"},
    "mahalanobis": {"no": "Robust Mahalanobis", "en": "Robust Mahalanobis"},
    "hgb_calibrated": {"no": "Kalibrert sannsynlighet", "en": "Calibrated probability"},
    "hgb": {"no": "Kalibrert sannsynlighet", "en": "Calibrated probability"},
}

ABLATION_ORDER = ("all", "no_network", "no_accounts", "no_text", "register_roles_only")
ABLATION_NAMES: dict[str, dict[str, str]] = {
    "all": {"no": "Alle trekk", "en": "All features"},
    "no_network": {"no": "Uten nettverk", "en": "Without network"},
    "no_accounts": {"no": "Uten regnskap", "en": "Without accounts"},
    "no_text": {"no": "Uten tekst", "en": "Without text"},
    "register_roles_only": {"no": "Bare register og roller", "en": "Register and roles only"},
}

GROUP_TYPE_ORDER = ("fylke", "nace_section", "age_band", "size_band")
GROUP_TYPE_NAMES: dict[str, dict[str, str]] = {
    "fylke": {"no": "Fylke", "en": "County"},
    "nace_section": {"no": "Næringshovedområde", "en": "Industry section"},
    "age_band": {"no": "Aldersbånd (år)", "en": "Age band (years)"},
    "size_band": {"no": "Størrelsesbånd", "en": "Size band"},
}

KIND_ORDER = ("auditor", "accountant")
KIND_NAMES: dict[str, dict[str, str]] = {
    "auditor": {"no": "Revisor", "en": "Auditor"},
    "accountant": {"no": "Regnskapsfører", "en": "Accountant"},
}

METRIC_NAMES: dict[str, dict[str, str]] = {
    "average_precision": {"no": "Gjennomsnittlig presisjon", "en": "Average precision"},
    "precision_top_1pct": {"no": "Presisjon i topp 1 %", "en": "Precision in top 1%"},
    "precision_top_5pct": {"no": "Presisjon i topp 5 %", "en": "Precision in top 5%"},
    "lift_top_1pct": {"no": "Løft i topp 1 %", "en": "Lift in top 1%"},
    "lift_top_5pct": {"no": "Løft i topp 5 %", "en": "Lift in top 5%"},
    "roc_auc": {"no": "ROC AUC", "en": "ROC AUC"},
    "brier": {"no": "Brier-skår", "en": "Brier score"},
    "expected_calibration_error": {
        "no": "Forventet kalibreringsfeil",
        "en": "Expected calibration error",
    },
}

# Feature identifiers used in the explanation tables. Unknown identifiers fall back to the
# identifier itself.
FEATURE_NAMES: dict[str, dict[str, str]] = {
    "nace_division": {"no": "Næring (tosifret NACE)", "en": "Industry division (2-digit NACE)"},
    "nace_section": {"no": "Næringshovedområde", "en": "Industry section"},
    "fylke_code": {"no": "Fylke", "en": "County"},
    "acc_age_days": {
        "no": "Alder på siste regnskap (dager)",
        "en": "Age of latest accounts (days)",
    },
    "acc_n_statements_known": {"no": "Antall kjente regnskap", "en": "Number of known statements"},
    "har_registrert_antall_ansatte": {
        "no": "Har registrert antall ansatte",
        "en": "Has registered employee count",
    },
    "years_registered": {"no": "År siden registrering", "en": "Years since registration"},
    "age_years": {"no": "Alder (år)", "en": "Age (years)"},
    "acc_filing_lag_days": {
        "no": "Forsinkelse ved innsending av regnskap (dager)",
        "en": "Accounts filing lag (days)",
    },
    "has_auditor": {"no": "Har revisor", "en": "Has auditor"},
    "acc_netto_finans": {"no": "Netto finansposter", "en": "Net financial items"},
    "acc_sum_driftsinntekter": {"no": "Sum driftsinntekter", "en": "Total operating income"},
    "acc_salgsinntekter": {"no": "Salgsinntekter", "en": "Sales revenue"},
    "acc_sum_driftskostnad": {"no": "Sum driftskostnader", "en": "Total operating expenses"},
    "acc_loennskostnad": {"no": "Lønnskostnader", "en": "Payroll expenses"},
    "acc_driftsresultat": {"no": "Driftsresultat", "en": "Operating result"},
    "acc_aarsresultat": {"no": "Årsresultat", "en": "Net result"},
    "acc_sum_finanskostnad": {"no": "Sum finanskostnader", "en": "Total financial expenses"},
    "acc_sum_eiendeler": {"no": "Sum eiendeler", "en": "Total assets"},
    "acc_sum_omloepsmidler": {"no": "Sum omløpsmidler", "en": "Total current assets"},
    "acc_sum_bankinnskudd_og_kontanter": {
        "no": "Bankinnskudd og kontanter",
        "en": "Bank deposits and cash",
    },
    "acc_sum_egenkapital": {"no": "Sum egenkapital", "en": "Total equity"},
    "acc_sum_opptjent_egenkapital": {"no": "Opptjent egenkapital", "en": "Retained equity"},
    "acc_sum_innskutt_egenkapital": {"no": "Innskutt egenkapital", "en": "Paid-in equity"},
    "acc_sum_gjeld": {"no": "Sum gjeld", "en": "Total debt"},
    "acc_sum_kortsiktig_gjeld": {"no": "Sum kortsiktig gjeld", "en": "Total current liabilities"},
    "acc_sum_langsiktig_gjeld": {"no": "Sum langsiktig gjeld", "en": "Total long-term debt"},
    "acc_goodwill": {"no": "Goodwill", "en": "Goodwill"},
    "acc_period_days": {
        "no": "Regnskapsperiodens lengde (dager)",
        "en": "Accounting period (days)",
    },
    "acc_prev_sum_driftsinntekter": {
        "no": "Sum driftsinntekter, året før",
        "en": "Total operating income, previous year",
    },
    "acc_prev_aarsresultat": {"no": "Årsresultat, året før", "en": "Net result, previous year"},
    "acc_prev_sum_eiendeler": {
        "no": "Sum eiendeler, året før",
        "en": "Total assets, previous year",
    },
    "acc_prev_sum_egenkapital": {
        "no": "Sum egenkapital, året før",
        "en": "Total equity, previous year",
    },
    "acc_ikke_revidert": {"no": "Ikke revidert", "en": "Not audited"},
    "acc_fravalg_revisjon": {
        "no": "Fravalg av revisjon i regnskapet",
        "en": "Audit opt-out in accounts",
    },
    "acc_smaa_foretak": {"no": "Små foretak", "en": "Small enterprise rules"},
    "acc_morselskap": {"no": "Morselskap", "en": "Parent company"},
    "board_size": {"no": "Styrestørrelse", "en": "Board size"},
    "equity_ratio": {"no": "Egenkapitalandel", "en": "Equity ratio"},
    "debt_ratio": {"no": "Gjeldsgrad", "en": "Debt ratio"},
    "operating_margin": {"no": "Driftsmargin", "en": "Operating margin"},
    "return_on_assets": {"no": "Avkastning på eiendelene", "en": "Return on assets"},
    "current_ratio": {"no": "Likviditetsgrad", "en": "Current ratio"},
    "cash_ratio": {"no": "Kontantandel", "en": "Cash ratio"},
    "interest_burden": {"no": "Rentebelastning", "en": "Interest burden"},
    "log_revenue": {"no": "Omsetning (log)", "en": "Revenue (log)"},
    "log_assets": {"no": "Sum eiendeler (log)", "en": "Total assets (log)"},
    "revenue_growth": {"no": "Omsetningsvekst", "en": "Revenue growth"},
    "asset_growth": {"no": "Vekst i eiendeler", "en": "Asset growth"},
    "negative_equity": {"no": "Negativ egenkapital", "en": "Negative equity"},
    "has_accounts": {"no": "Har regnskap", "en": "Has accounts"},
    "size_band": {"no": "Størrelsesbånd", "en": "Size band"},
    "kapital_belop": {"no": "Aksjekapital", "en": "Share capital"},
    "log_kapital": {"no": "Aksjekapital (log)", "en": "Share capital (log)"},
    "n_changes_12m": {"no": "Endringer siste 12 måneder", "en": "Changes in the last 12 months"},
    "n_role_events_12m": {
        "no": "Rolleendringer siste 12 måneder",
        "en": "Role events in the last 12 months",
    },
    "days_since_board_change": {"no": "Dager siden styreendring", "en": "Days since board change"},
    "days_since_ceo_change": {
        "no": "Dager siden skifte av daglig leder",
        "en": "Days since CEO change",
    },
    "auditor_portfolio_size": {
        "no": "Antall kunder hos revisoren",
        "en": "Auditor portfolio size",
    },
    "auditor_other_clients_adverse_share": {
        "no": "Andel registrerte utfall hos revisorens andre kunder",
        "en": "Adverse share among the auditor's other clients",
    },
    "accountant_portfolio_size": {
        "no": "Antall kunder hos regnskapsføreren",
        "en": "Accountant portfolio size",
    },
    "accountant_other_clients_adverse_share": {
        "no": "Andel registrerte utfall hos regnskapsførerens andre kunder",
        "en": "Adverse share among the accountant's other clients",
    },
    "n_changes_6m": {"no": "Endringer siste 6 måneder", "en": "Changes in the last 6 months"},
    "n_role_events_6m": {
        "no": "Rolleendringer siste 6 måneder",
        "en": "Role events in the last 6 months",
    },
    "n_person_roleholders": {
        "no": "Antall personer med rolle",
        "en": "Number of persons holding a role",
    },
    "fravalg_revisjon": {
        "no": "Fravalg av revisjon i registeret",
        "en": "Audit opt-out in the register",
    },
    "acc_regnskapsregler": {"no": "Regnskapsregler", "en": "Accounting rules"},
    "acc_avviklingsregnskap": {"no": "Avviklingsregnskap", "en": "Liquidation accounts"},
    "pct_board_size": {"no": "Styrestørrelse (persentil)", "en": "Board size (percentile)"},
    "z_log_kapital": {"no": "Aksjekapital (log, z)", "en": "Share capital (log, z)"},
    "z_log_revenue": {"no": "Omsetning (log, z)", "en": "Revenue (log, z)"},
    "text_sim_own_code": {
        "no": "Tekstlikhet med egen næringskode",
        "en": "Text similarity to own industry code",
    },
    "z_revenue_growth": {"no": "Omsetningsvekst (z)", "en": "Revenue growth (z)"},
    "z_operating_margin": {"no": "Driftsmargin (z)", "en": "Operating margin (z)"},
    "z_interest_burden": {"no": "Rentebelastning (z)", "en": "Interest burden (z)"},
    "z_equity_ratio": {"no": "Egenkapitalandel (z)", "en": "Equity ratio (z)"},
    "z_debt_ratio": {"no": "Gjeldsgrad (z)", "en": "Debt ratio (z)"},
}

LABELS: dict[str, dict[str, str]] = {
    # Shared axis labels
    "axis.share_flagged": {"no": "Andel flagget", "en": "Share flagged"},
    "axis.precision": {"no": "Presisjon", "en": "Precision"},
    "axis.lift": {"no": "Løft mot grunnrate", "en": "Lift over base rate"},
    "axis.quantile": {"no": "Kvantil", "en": "Quantile"},
    "axis.score": {"no": "Skår", "en": "Score"},
    "axis.companies": {"no": "Antall selskap", "en": "Number of companies"},
    "axis.rate": {"no": "Andel", "en": "Rate"},
    "axis.value": {"no": "Verdi", "en": "Value"},
    "axis.snapshot": {"no": "Øyeblikksbilde", "en": "Snapshot id"},
    "axis.psi": {
        "no": "Populasjonsstabilitetsindeks (PSI)",
        "en": "Population stability index (PSI)",
    },
    "axis.mean_abs_shap": {
        "no": "Gjennomsnittlig absolutt SHAP-verdi",
        "en": "Mean absolute SHAP value",
    },
    "axis.mean_predicted": {
        "no": "Gjennomsnittlig predikert sannsynlighet",
        "en": "Mean predicted probability",
    },
    "axis.observed_rate": {"no": "Observert andel", "en": "Observed rate"},
    "axis.feature_set": {"no": "Trekksett", "en": "Feature set"},
    "axis.clients": {"no": "Antall kundeselskap", "en": "Number of client companies"},
    # Pipeline diagram
    "pipeline.title": {
        "no": "Dataflyt fra innhenting til varsler",
        "en": "Data flow from acquisition to alerts",
    },
    "pipeline.acquire": {
        "no": "Innhenting og filtrering på lokal maskin",
        "en": "Acquisition and filtering on a local machine",
    },
    "pipeline.landing": {"no": "Landingsfiler", "en": "Landing files"},
    "pipeline.bronze": {"no": "Bronse", "en": "Bronze"},
    "pipeline.silver": {"no": "Sølv", "en": "Silver"},
    "pipeline.gold": {"no": "Gull", "en": "Gold"},
    "pipeline.models": {"no": "Modeller og register", "en": "Models and registry"},
    "pipeline.scoring": {"no": "Scoring og overvåking", "en": "Scoring and monitoring"},
    "pipeline.alerts": {"no": "Varsler", "en": "Alerts"},
    "pipeline.laptop": {"no": "Lokal maskin", "en": "Local machine"},
    "pipeline.cloud": {"no": "Databricks", "en": "Databricks"},
    "pipeline.note": {
        "no": "Bare selskapsnivå går videre",
        "en": "Only company level data moves on",
    },
    # Population overview
    "population.title": {
        "no": "Populasjonen av aksjeselskap",
        "en": "Population of limited companies",
    },
    "population.by_section": {"no": "Etter næringshovedområde", "en": "By industry section"},
    "population.by_fylke": {"no": "Etter fylke", "en": "By county"},
    # Score distributions
    "scores.title": {
        "no": "Fordeling av skår på testdelen",
        "en": "Score distribution on the test split",
    },
    # Precision and lift by share flagged
    "topk.title": {
        "no": "Presisjon og løft etter andel flagget",
        "en": "Precision and lift by share flagged",
    },
    # Calibration
    "calibration.title": {
        "no": "Kalibrering av predikert sannsynlighet",
        "en": "Calibration of predicted probability",
    },
    "calibration.diagonal": {"no": "Perfekt kalibrering", "en": "Perfect calibration"},
    "calibration.bins": {"no": "Intervaller", "en": "Bins"},
    "calibration.floor": {
        "no": "Observert andel null, tegnet ved gulvet",
        "en": "Observed rate zero, drawn at the floor",
    },
    "calibration.size": {"no": "Antall i intervallet", "en": "Count in bin"},
    # SHAP summary
    "shap.title": {
        "no": "Viktigste trekk i den kalibrerte modellen",
        "en": "Most important features in the calibrated model",
    },
    # Ablation
    "ablation.title": {
        "no": "Ablasjon: bidrag fra grupper av trekk",
        "en": "Ablation: contribution of feature groups",
    },
    # Fairness
    "fairness.title": {
        "no": "Andel flagget og grunnrate per gruppe",
        "en": "Flag rate and base rate per group",
    },
    "fairness.flag_rate": {"no": "Andel flagget", "en": "Flag rate"},
    "fairness.base_rate": {"no": "Grunnrate", "en": "Base rate"},
    # Drift
    "drift.title": {
        "no": "Drift i trekk og andel flagget mellom øyeblikksbilder",
        "en": "Feature drift and share flagged across snapshots",
    },
    "drift.psi_panel": {
        "no": "PSI for de ti trekkene med størst endring",
        "en": "PSI for the ten most shifted features",
    },
    "drift.flag_panel": {
        "no": "Andel flagget per øyeblikksbilde",
        "en": "Share flagged per snapshot",
    },
    "drift.warn": {"no": "advarsel", "en": "warn"},
    "drift.alert": {"no": "alarm", "en": "alert"},
    # Network degree
    "network.title": {
        "no": "Selskap etter hvor mange kunder revisoren og regnskapsføreren har",
        "en": "Companies by the portfolio size of their auditor and accountant",
    },
}


class Labels:
    """Resolve figure text for one language.

    ``labels("topk.title")`` returns the title text, and the named methods resolve display names
    for models, ablations, features, group types and network kinds, falling back to the raw
    identifier when no translation exists.
    """

    def __init__(self, lang: str) -> None:
        if lang not in LANGUAGES:
            raise ValueError(f"unknown language {lang!r}, expected one of {LANGUAGES}")
        self.lang = lang

    def __call__(self, key: str) -> str:
        return LABELS[key][self.lang]

    def _named(self, table: dict[str, dict[str, str]], name: str) -> str:
        entry = table.get(name)
        return name if entry is None else entry[self.lang]

    def model(self, name: str) -> str:
        return self._named(MODEL_NAMES, name)

    def ablation(self, name: str) -> str:
        return self._named(ABLATION_NAMES, name)

    def feature(self, name: str) -> str:
        return self._named(FEATURE_NAMES, name)

    def group_type(self, name: str) -> str:
        return self._named(GROUP_TYPE_NAMES, name)

    def kind(self, name: str) -> str:
        return self._named(KIND_NAMES, name)

    def metric(self, name: str) -> str:
        return self._named(METRIC_NAMES, name)

    def percent(self, value: float, decimals: int | None = None) -> str:
        """Format a percentage with the language's decimal separator and spacing."""
        text = f"{value:g}" if decimals is None else f"{value:.{decimals}f}"
        if self.lang == "no":
            return text.replace(".", ",") + " %"
        return text + "%"

    def number(self, value: float) -> str:
        """Format a count with the language's thousands separator."""
        text = f"{value:,.0f}"
        if self.lang == "no":
            return text.replace(",", " ")
        return text

    def percent_axis(self, axis_label: str) -> str:
        """Append the percent unit to an axis label."""
        return f"{axis_label} (%)"
