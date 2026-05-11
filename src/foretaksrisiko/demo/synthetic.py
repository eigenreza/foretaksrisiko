"""Score one synthetic company with the shipped artefacts: features, peer position, two scores.

The company exists only in the browser session and never touches the registers. A small set
of inputs sets the register, role and accounts features that matter most; everything else
takes a typical value, the population median or mode. The peer z-scores and percentiles come
from the shipped peer statistics, the probability from the champion model, and the anomaly
score from the robust Mahalanobis parameters. Drivers are measured by setting one input at a
time back to its typical value and reading the change in the two scores.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields, replace
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_FILE = "hgb_calibrated.joblib"
META_FILE = "hgb_meta.json"
MAHALANOBIS_FILE = "mahalanobis.json"
PEER_STATS_FILE = "peer_stats.csv"
PEER_QUANTILES_FILE = "peer_quantiles.csv"
DEFAULTS_FILE = "feature_defaults.csv"
SIZE_BANDS_FILE = "size_bands.csv"
DIVISIONS_FILE = "nace_divisions.csv"
FYLKER_FILE = "fylker.csv"
SVALBARD = "21"

# The same list as ``foretaksrisiko.lakehouse.features.RATIO_FEATURES``; copied here so that
# the demo never imports PySpark. A test keeps the two in step.
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
QUANTILE_GRID = [round(i / 20, 2) for i in range(1, 20)]
EXTREME_Z = 3.0
MAD_SCALE = 1.4826
TAX_RATE = 0.22
SHORT_TERM_DEBT_SHARE = 0.6
PAYROLL_SHARE = 0.3
NO_ACCOUNTS_BAND = "0"


def quantile_column(q: float) -> str:
    return f"q{int(round(q * 100)):02d}"


# -- inputs --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """What the sliders and dropdowns set. Every other feature takes a typical value."""

    nace_division: str = "68"
    fylke_code: str = "03"
    age_years: float = 8.0
    share_capital: float = 30_000.0
    registered_employees: bool = False
    registered_vat: bool = True
    in_group: bool = False
    board_size: int = 1
    has_ceo: bool = True
    ceo_is_chair: bool = False
    has_auditor: bool = False
    has_accountant: bool = True
    n_changes_12m: int = 0
    n_role_events_12m: int = 0
    days_since_board_change: int = 1500
    days_since_ceo_change: int = 2200
    has_accounts: bool = True
    total_assets: float = 2_000_000.0
    revenue: float = 2_500_000.0
    equity_ratio: float = 0.3
    operating_margin: float = 0.05
    current_ratio: float = 1.5
    cash_ratio: float = 0.5
    revenue_growth: float = 0.0
    asset_growth: float = 0.0
    acc_age_days: int = 400
    acc_filing_lag_days: int = 0
    acc_n_statements_known: int = 3


INPUT_FIELDS = [f.name for f in fields(Inputs)]

# Input field -> the population feature its typical value is read from.
TYPICAL_SOURCE = {
    "age_years": "age_years",
    "share_capital": "kapital_belop",
    "registered_employees": "har_registrert_antall_ansatte",
    "registered_vat": "registrert_i_mvaregisteret",
    "in_group": "er_i_konsern",
    "board_size": "board_size",
    "has_ceo": "has_ceo",
    "ceo_is_chair": "ceo_is_chair",
    "has_auditor": "has_auditor",
    "has_accountant": "has_accountant",
    "n_changes_12m": "n_changes_12m",
    "n_role_events_12m": "n_role_events_12m",
    "days_since_board_change": "days_since_board_change",
    "days_since_ceo_change": "days_since_ceo_change",
    "has_accounts": "has_accounts",
    "total_assets": "acc_sum_eiendeler",
    "revenue": "acc_sum_driftsinntekter",
    "equity_ratio": "equity_ratio",
    "operating_margin": "operating_margin",
    "current_ratio": "current_ratio",
    "cash_ratio": "cash_ratio",
    "revenue_growth": "revenue_growth",
    "asset_growth": "asset_growth",
    "acc_age_days": "acc_age_days",
    "acc_filing_lag_days": "acc_filing_lag_days",
    "acc_n_statements_known": "acc_n_statements_known",
}


# -- artefacts -----------------------------------------------------------------------------------


@dataclass
class Artefacts:
    """Everything the demo needs to score a synthetic company, loaded from one directory."""

    model: object
    calibrated: object
    meta: dict
    peer_stats: pd.DataFrame
    peer_quantiles: pd.DataFrame
    defaults: dict[str, object]
    size_bands: list[tuple[str, float, float]]
    mahalanobis: dict
    divisions: pd.DataFrame
    fylker: pd.DataFrame

    def __post_init__(self) -> None:
        self._stats: dict[tuple[str, str], tuple[int, float, float]] = {
            (r.peer_group, r.feature): (int(r.n), float(r.median), float(r.mad))
            for r in self.peer_stats.itertuples(index=False)
        }
        columns = [quantile_column(q) for q in QUANTILE_GRID]
        self._quantiles: dict[tuple[str, str], np.ndarray] = {
            (r["peer_group"], r["feature"]): r[columns].to_numpy(dtype="float64")
            for _, r in self.peer_quantiles.iterrows()
        }
        self._groups = {g for g, _ in self._stats}
        self._sections = dict(zip(self.divisions["code"], self.divisions["section"], strict=True))

    @classmethod
    def load(cls, path: Path) -> Artefacts:
        import joblib

        path = Path(path)
        bundle = joblib.load(path / MODEL_FILE)
        meta = json.loads((path / META_FILE).read_text(encoding="utf-8"))
        text = {"peer_group": str, "feature": str}
        peer_stats = pd.read_csv(path / PEER_STATS_FILE, dtype=text)
        peer_quantiles = pd.read_csv(path / PEER_QUANTILES_FILE, dtype=text)
        defaults_table = pd.read_csv(path / DEFAULTS_FILE, dtype=str, keep_default_na=False)
        defaults: dict[str, object] = {}
        for row in defaults_table.itertuples(index=False):
            if row.kind == "categorical":
                defaults[row.feature] = row.value or None
            else:
                defaults[row.feature] = float(row.value) if row.value else math.nan
        bands_table = pd.read_csv(path / SIZE_BANDS_FILE, dtype={"band": str})
        size_bands = [
            (str(r.band), float(r.lo), float(r.hi))
            for r in bands_table.itertuples(index=False)
            if str(r.band) != NO_ACCOUNTS_BAND and not pd.isna(r.hi)
        ]
        size_bands.sort(key=lambda b: b[2])
        mahalanobis = json.loads((path / MAHALANOBIS_FILE).read_text(encoding="utf-8"))
        divisions = pd.read_csv(path / DIVISIONS_FILE, dtype=str, keep_default_na=False)
        fylker = pd.read_csv(path / FYLKER_FILE, dtype=str, keep_default_na=False)
        return cls(
            model=bundle["model"],
            calibrated=bundle["calibrated"],
            meta=meta,
            peer_stats=peer_stats,
            peer_quantiles=peer_quantiles,
            defaults=defaults,
            size_bands=size_bands,
            mahalanobis=mahalanobis,
            divisions=divisions,
            fylker=fylker,
        )

    # -- lookups ---------------------------------------------------------------------------------

    def section_of(self, division: str) -> str | None:
        return self._sections.get(division)

    def size_band_for(self, log_assets: float) -> str:
        if log_assets is None or math.isnan(log_assets) or not self.size_bands:
            return NO_ACCOUNTS_BAND
        for band, _, hi in self.size_bands:
            if log_assets <= hi:
                return band
        return self.size_bands[-1][0]

    def peer_group_for(self, division: str | None, section: str | None, band: str) -> str:
        """The same fallback as the lakehouse: division, then section, then size band alone."""
        candidates = [
            f"division:{division or '??'}|{band}",
            f"section:{section or 'X'}|{band}",
            f"all:{band}",
        ]
        for group in candidates:
            if group in self._groups:
                return group
        return candidates[-1]

    def stats(self, group: str, feature: str) -> tuple[int, float, float] | None:
        return self._stats.get((group, feature))

    def quantiles(self, group: str, feature: str) -> np.ndarray | None:
        return self._quantiles.get((group, feature))

    def typical_inputs(self) -> Inputs:
        """Inputs that describe a typical company: population medians and modes."""
        values: dict[str, object] = {}
        for name, source in TYPICAL_SOURCE.items():
            value = self.defaults.get(source)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            kind = Inputs.__dataclass_fields__[name].type
            if kind == "bool":
                values[name] = bool(float(value) >= 0.5)
            elif kind == "int":
                values[name] = int(round(float(value)))
            else:
                values[name] = float(value)
        for name, feature in (("nace_division", "nace_division"), ("fylke_code", "fylke_code")):
            value = self.defaults.get(feature)
            if value:
                values[name] = str(value)
        # The demo company always starts with accounts: that is the case worth exploring, and
        # the typical accounts values are medians over companies that have accounts.
        values["has_accounts"] = True
        return Inputs(**values)


# -- feature construction ------------------------------------------------------------------------


def _log1p(value: float) -> float:
    return math.log1p(max(float(value), 0.0))


def _nan_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else math.nan


def build_features(inputs: Inputs, art: Artefacts) -> tuple[dict[str, object], dict[str, str]]:
    """Derive the full feature row for a synthetic company. Returns the row and its context."""
    f: dict[str, object] = {}
    for column in art.meta["features"]:
        if column.startswith("z_"):
            f[column] = 0.0
        elif column.startswith("pct_"):
            f[column] = 0.5
        elif column == "n_extreme_z":
            f[column] = 0.0
        else:
            f[column] = art.defaults.get(column, math.nan)

    section = art.section_of(inputs.nace_division)
    f["nace_division"] = inputs.nace_division
    f["nace_section"] = section
    f["nace_missing"] = 0.0
    f["fylke_code"] = inputs.fylke_code
    f["is_asa"] = 0.0
    f["age_years"] = float(inputs.age_years)
    f["years_registered"] = float(inputs.age_years)
    f["kapital_belop"] = float(inputs.share_capital)
    f["log_kapital"] = _log1p(inputs.share_capital)
    f["har_registrert_antall_ansatte"] = float(inputs.registered_employees)
    f["registrert_i_mvaregisteret"] = float(inputs.registered_vat)
    f["er_i_konsern"] = float(inputs.in_group)

    board = max(int(inputs.board_size), 0)
    f["board_size"] = float(board)
    f["n_board_chair"] = float(board >= 1)
    f["has_chair"] = float(board >= 1)
    f["n_board_members"] = float(max(board - 1, 0))
    f["n_ceo"] = float(inputs.has_ceo)
    f["has_ceo"] = float(inputs.has_ceo)
    f["ceo_is_chair"] = float(inputs.has_ceo and inputs.ceo_is_chair)
    persons = board + (1 if inputs.has_ceo and not inputs.ceo_is_chair else 0)
    f["n_person_roleholders"] = float(persons)
    f["n_distinct_persons"] = float(persons)
    f["has_auditor"] = float(inputs.has_auditor)
    f["fravalg_revisjon"] = float(not inputs.has_auditor)
    f["has_accountant"] = float(inputs.has_accountant)
    f["n_org_roleholders"] = float(inputs.has_auditor) + float(inputs.has_accountant)
    if not inputs.has_auditor:
        for column in (
            "auditor_portfolio_size",
            "auditor_other_clients_adverse_share",
            "auditor_outside_population",
        ):
            f[column] = math.nan
    if not inputs.has_accountant:
        for column in ("accountant_portfolio_size", "accountant_other_clients_adverse_share"):
            f[column] = math.nan
    f["n_changes_12m"] = float(inputs.n_changes_12m)
    f["n_changes_6m"] = float(round(inputs.n_changes_12m / 2))
    f["n_role_events_12m"] = float(inputs.n_role_events_12m)
    f["n_role_events_6m"] = float(round(inputs.n_role_events_12m / 2))
    f["days_since_board_change"] = float(inputs.days_since_board_change)
    f["days_since_ceo_change"] = float(inputs.days_since_ceo_change)

    acc_columns = [c for c in art.meta["features"] if c.startswith("acc_")]
    ratio_columns = [
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
        "negative_equity",
        "zero_revenue",
        "loss",
    ]
    if inputs.has_accounts:
        assets = max(float(inputs.total_assets), 0.0)
        revenue = max(float(inputs.revenue), 0.0)
        equity_share = float(inputs.equity_ratio)
        margin = float(inputs.operating_margin)
        equity = equity_share * assets
        debt = assets - equity
        short_debt = SHORT_TERM_DEBT_SHARE * debt
        operating_result = margin * revenue
        pre_tax = operating_result + float(f.get("acc_netto_finans") or 0.0)
        tax = TAX_RATE * pre_tax if pre_tax > 0 else 0.0
        net_result = pre_tax - tax
        current_assets = min(assets, float(inputs.current_ratio) * short_debt)
        cash = min(current_assets, float(inputs.cash_ratio) * short_debt)
        prev_revenue = (
            revenue / (1.0 + inputs.revenue_growth) if inputs.revenue_growth > -1 else 0.0
        )
        prev_assets = assets / (1.0 + inputs.asset_growth) if inputs.asset_growth > -1 else 0.0
        f["has_accounts"] = 1.0
        f["log_assets"] = _log1p(assets)
        f["log_revenue"] = _log1p(revenue)
        f["zero_revenue"] = float(revenue == 0)
        f["equity_ratio"] = equity_share
        f["debt_ratio"] = 1.0 - equity_share
        f["operating_margin"] = margin if revenue > 0 else math.nan
        f["return_on_assets"] = _nan_ratio(operating_result, assets)
        f["current_ratio"] = float(inputs.current_ratio)
        f["cash_ratio"] = float(inputs.cash_ratio)
        f["revenue_growth"] = float(inputs.revenue_growth)
        f["asset_growth"] = float(inputs.asset_growth)
        f["negative_equity"] = float(equity_share < 0)
        f["loss"] = float(net_result < 0)
        amounts = {
            "acc_sum_eiendeler": assets,
            "acc_sum_egenkapital_gjeld": assets,
            "acc_sum_egenkapital": equity,
            "acc_sum_gjeld": debt,
            "acc_sum_kortsiktig_gjeld": short_debt,
            "acc_sum_langsiktig_gjeld": debt - short_debt,
            "acc_sum_omloepsmidler": current_assets,
            "acc_sum_anleggsmidler": assets - current_assets,
            "acc_sum_bankinnskudd_og_kontanter": cash,
            "acc_sum_driftsinntekter": revenue,
            "acc_salgsinntekter": revenue,
            "acc_driftsresultat": operating_result,
            "acc_sum_driftskostnad": revenue - operating_result,
            "acc_loennskostnad": PAYROLL_SHARE * revenue if inputs.registered_employees else 0.0,
            "acc_ordinaert_resultat_foer_skattekostnad": pre_tax,
            "acc_ordinaert_resultat_skattekostnad": tax,
            "acc_aarsresultat": net_result,
            "acc_totalresultat": net_result,
            "acc_prev_sum_driftsinntekter": prev_revenue,
            "acc_prev_driftsresultat": margin * prev_revenue,
            "acc_prev_aarsresultat": net_result * (prev_revenue / revenue if revenue else 1.0),
            "acc_prev_sum_eiendeler": prev_assets,
            "acc_prev_sum_egenkapital": equity_share * prev_assets,
            "acc_prev_sum_gjeld": (1.0 - equity_share) * prev_assets,
            "acc_age_days": float(inputs.acc_age_days),
            "acc_filing_lag_days": float(inputs.acc_filing_lag_days),
            "acc_n_statements_known": float(inputs.acc_n_statements_known),
            "acc_fravalg_revisjon": float(not inputs.has_auditor),
        }
        for column, value in amounts.items():
            if column in f:
                f[column] = float(value)
    else:
        f["has_accounts"] = 0.0
        for column in acc_columns + ratio_columns:
            if column in f:
                f[column] = math.nan
        if "acc_n_statements_known" in f:
            f["acc_n_statements_known"] = 0.0
        if "acc_regnskapsregler" in f:
            f["acc_regnskapsregler"] = None

    band = art.size_band_for(float(f.get("log_assets", math.nan)))
    f["size_band"] = band
    group = art.peer_group_for(inputs.nace_division, section, band)
    extreme = 0
    for feature in RATIO_FEATURES:
        value = f.get(feature, math.nan)
        z, pct = peer_z_and_pct(value, group, feature, art)
        f[f"z_{feature}"] = z
        f[f"pct_{feature}"] = pct
        if not math.isnan(z) and abs(z) > EXTREME_Z:
            extreme += 1
    if "n_extreme_z" in f:
        f["n_extreme_z"] = float(extreme)
    context = {"section": section or "", "size_band": band, "peer_group": group}
    return f, context


def peer_z_and_pct(value, group: str, feature: str, art: Artefacts) -> tuple[float, float]:
    """Robust z-score and percentile of one value within its peer group."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return math.nan, math.nan
    value = float(value)
    z = math.nan
    stats = art.stats(group, feature)
    if stats is not None:
        _, median, mad = stats
        if mad > 0:
            z = (value - median) / (MAD_SCALE * mad)
    pct = math.nan
    grid = art.quantiles(group, feature)
    if grid is not None and len(grid) == len(QUANTILE_GRID):
        pct = _percentile(value, grid, QUANTILE_GRID)
    return z, pct


def _percentile(value: float, points: np.ndarray, grid: list[float]) -> float:
    below = int(np.sum(points <= value))
    if below == 0:
        return grid[0] / 2
    if below == len(points):
        return (grid[-1] + 1.0) / 2
    lower, upper = points[below - 1], points[below]
    if upper > lower:
        fraction = (value - lower) / (upper - lower)
        return grid[below - 1] + fraction * (grid[below] - grid[below - 1])
    return grid[below - 1]


# -- scoring -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scores:
    probability: float
    raw_probability: float
    mahalanobis: float
    rule: float
    n_extreme_z: int
    probability_percentile: float | None
    mahalanobis_percentile: float | None


def _conform(features: dict[str, object], art: Artefacts) -> pd.DataFrame:
    """The serving pipeline's conformance: fill values, numeric casts, pinned categories."""
    meta = art.meta
    frame = pd.DataFrame([features])
    for column, value in meta["fill_values"].items():
        if column in frame.columns and value is not None:
            frame[column] = frame[column].fillna(value)
    for column in meta["features"]:
        if column not in frame.columns:
            frame[column] = np.nan
        if column not in meta["categorical"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float32")
    matrix = frame[meta["features"]].copy()
    for column in meta["categorical"]:
        matrix[column] = pd.Categorical(
            matrix[column].astype("string").fillna("missing"),
            categories=meta["categories"][column],
        )
    return matrix


def mahalanobis_distance(features: dict[str, object], art: Artefacts) -> float:
    spec = art.mahalanobis
    values = np.array(
        [
            float(spec["impute"][c])
            if features.get(c) is None or math.isnan(float(features.get(c)))
            else float(features[c])
            for c in spec["columns"]
        ],
        dtype="float64",
    )
    center = np.array(spec["center"], dtype="float64")
    scale = np.array(spec["scale"], dtype="float64")
    scaled = (values - center) / scale
    centred = scaled - np.array(spec["location"], dtype="float64")
    precision = np.array(spec["precision"], dtype="float64")
    return float(math.sqrt(max(float(centred @ precision @ centred), 0.0)))


def percentile_of(value: float, quantiles: dict[str, float] | None) -> float | None:
    """The largest quantile whose value is at or below ``value``; None without a reference."""
    if not quantiles:
        return None
    best = 0.0
    for q, threshold in quantiles.items():
        if threshold is not None and value >= float(threshold):
            best = max(best, float(q))
    return best


def score(
    features: dict[str, object],
    art: Artefacts,
    probability_quantiles: dict[str, float] | None = None,
) -> Scores:
    matrix = _conform(features, art)
    probability = float(art.calibrated.predict_proba(matrix)[0, 1])
    raw = float(art.model.predict_proba(matrix)[0, 1])
    distance = mahalanobis_distance(features, art)
    z_values = [
        abs(float(features[c]))
        for c in art.mahalanobis["columns"]
        if features.get(c) is not None and not math.isnan(float(features[c]))
    ]
    extreme = sum(1 for z in z_values if z > EXTREME_Z)
    rule = extreme + (max(z_values) if z_values else 0.0) / 1000.0
    return Scores(
        probability=probability,
        raw_probability=raw,
        mahalanobis=distance,
        rule=rule,
        n_extreme_z=extreme,
        probability_percentile=percentile_of(probability, probability_quantiles),
        mahalanobis_percentile=percentile_of(distance, art.mahalanobis.get("score_quantiles")),
    )


def peer_position(features: dict[str, object], group: str, art: Artefacts) -> pd.DataFrame:
    """One row per ratio feature: the value, the peer median and MAD, z-score and percentile."""
    rows = []
    for feature in RATIO_FEATURES:
        stats = art.stats(group, feature)
        value = features.get(feature, math.nan)
        rows.append(
            {
                "feature": feature,
                "value": value,
                "n": stats[0] if stats else None,
                "median": stats[1] if stats else math.nan,
                "mad": stats[2] if stats else math.nan,
                "z": features.get(f"z_{feature}", math.nan),
                "pct": features.get(f"pct_{feature}", math.nan),
            }
        )
    return pd.DataFrame(rows)


def drivers(
    inputs: Inputs,
    art: Artefacts,
    typical: Inputs | None = None,
    probability_quantiles: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Change in the scores when one input at a time is set back to its typical value."""
    typical = typical or art.typical_inputs()
    features, _ = build_features(inputs, art)
    base = score(features, art, probability_quantiles)
    rows = []
    for name in INPUT_FIELDS:
        current = getattr(inputs, name)
        reference = getattr(typical, name)
        if current == reference:
            continue
        alternative, _ = build_features(replace(inputs, **{name: reference}), art)
        other = score(alternative, art, probability_quantiles)
        rows.append(
            {
                "input": name,
                "value": current,
                "typical": reference,
                "delta_probability": base.probability - other.probability,
                "delta_mahalanobis": base.mahalanobis - other.mahalanobis,
            }
        )
    table = pd.DataFrame(
        rows, columns=["input", "value", "typical", "delta_probability", "delta_mahalanobis"]
    )
    if not table.empty:
        moved = (table["delta_probability"].abs() > 1e-9) | (
            table["delta_mahalanobis"].abs() > 1e-9
        )
        table = table[moved]
        table = table.reindex(table["delta_probability"].abs().sort_values(ascending=False).index)
    return table.reset_index(drop=True)
