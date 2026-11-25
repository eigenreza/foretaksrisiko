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
    # The calibrated probability as the model gives it. Isotonic calibration is a step
    # function, so this value stays the same over wide ranges of input.
    step_probability: float | None = None


def smoothed_probability(calibrated, matrix: pd.DataFrame) -> float | None:
    """The calibrated probability with straight lines between the middles of its steps.

    Isotonic calibration maps the model's score to a probability with flat steps. In the demo
    that means many changes to a made-up company show no change at all. Joining the middle of
    each step to the next keeps the calibration, and every change moves the number. Returns
    None if the calibrator is not of the expected kind.
    """
    values = smoothed_probabilities(calibrated, matrix)
    return None if values is None else float(values[0])


def smoothed_probabilities(calibrated, matrix: pd.DataFrame) -> np.ndarray | None:
    """``smoothed_probability`` for every row of the matrix at once."""
    values = []
    try:
        for part in calibrated.calibrated_classifiers_:
            iso = part.calibrators[0]
            scores = np.ravel(part.estimator.decision_function(matrix)).astype(float)
            xs = np.asarray(iso.X_thresholds_, dtype=float)
            ys = np.asarray(iso.y_thresholds_, dtype=float)
            mid_x, mid_y, start = [], [], 0
            for i in range(1, len(ys) + 1):
                if i == len(ys) or ys[i] != ys[start]:
                    mid_x.append((xs[start] + xs[i - 1]) / 2.0)
                    mid_y.append(ys[start])
                    start = i
            values.append(np.interp(scores, mid_x, mid_y))
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    return np.mean(np.vstack(values), axis=0) if values else None


def _conform(features: dict[str, object], art: Artefacts) -> pd.DataFrame:
    """The serving pipeline's conformance: fill values, numeric casts, pinned categories."""
    return _conform_rows([features], art)


def _conform_rows(rows: list[dict[str, object]], art: Artefacts) -> pd.DataFrame:
    """``_conform`` for many companies at once, one row each."""
    meta = art.meta
    frame = pd.DataFrame(rows)
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
    """The share of the reference that lies strictly below ``value``; None without a reference.

    The calibrated probability comes in steps, so many companies share the same value. A value
    that ties with a run of quantiles is placed at the start of the run, not at its end, so the
    position is never better than the data supports.
    """
    if not quantiles:
        return None
    best = 0.0
    for q, threshold in quantiles.items():
        if threshold is not None and value > float(threshold):
            best = max(best, float(q))
    return best


def score(
    features: dict[str, object],
    art: Artefacts,
    probability_quantiles: dict[str, float] | None = None,
) -> Scores:
    matrix = _conform(features, art)
    step = float(art.calibrated.predict_proba(matrix)[0, 1])
    smooth = smoothed_probability(art.calibrated, matrix)
    probability = step if smooth is None else smooth
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
        # The reference quantiles come from the model's own output, so compare like with like.
        probability_percentile=percentile_of(step, probability_quantiles),
        mahalanobis_percentile=percentile_of(distance, art.mahalanobis.get("score_quantiles")),
        step_probability=step,
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


def _batch_scores(rows: list[dict[str, object]], art: Artefacts) -> tuple[np.ndarray, np.ndarray]:
    """The probability and the anomaly score for many companies, as ``score`` gives them."""
    matrix = _conform_rows(rows, art)
    probability = smoothed_probabilities(art.calibrated, matrix)
    if probability is None:
        probability = art.calibrated.predict_proba(matrix)[:, 1]
    distance = np.array([mahalanobis_distance(r, art) for r in rows], dtype=float)
    return np.asarray(probability, dtype=float), distance


# Up to this many changed inputs, every subset is scored and the Shapley values are exact.
EXACT_SHAPLEY_INPUTS = 10
# Above it, the values are averaged over this many random orders of the changed inputs.
SHAPLEY_ORDERS = 200


def drivers(
    inputs: Inputs,
    art: Artefacts,
    typical: Inputs | None = None,
    *,
    max_exact: int = EXACT_SHAPLEY_INPUTS,
    orders: int = SHAPLEY_ORDERS,
    seed: int = 0,
) -> pd.DataFrame:
    """Each changed input's share of the difference from the typical company.

    The shares are Shapley values over the inputs that differ from the typical company: the
    change in a score when an input goes from its typical value to the company's value,
    averaged over every order in which the changed inputs can be switched. The shares add up
    exactly to the company's score minus the typical company's score, so they can be read as
    parts of that difference. With up to ``max_exact`` changed inputs every subset is scored
    and the values are exact. With more, they are averaged over ``orders`` random orders; each
    order still runs from the typical company to this one, so the shares still add up exactly.
    """
    typical = typical or art.typical_inputs()
    names = [n for n in INPUT_FIELDS if getattr(inputs, n) != getattr(typical, n)]
    columns = ["input", "value", "typical", "delta_probability", "delta_mahalanobis"]
    if not names:
        return pd.DataFrame(columns=columns)
    n = len(names)

    def features_for(mask: int) -> dict[str, object]:
        switched = {names[i]: getattr(inputs, names[i]) for i in range(n) if mask >> i & 1}
        return build_features(replace(typical, **switched), art)[0]

    share_p, share_m = np.zeros(n), np.zeros(n)
    if n <= max_exact:
        masks = np.arange(1 << n)
        prob, dist = _batch_scores([features_for(int(m)) for m in masks], art)
        sizes = np.array([bin(int(m)).count("1") for m in masks])
        weights = np.array(
            [math.factorial(s) * math.factorial(n - s - 1) / math.factorial(n) for s in range(n)]
        )
        for i in range(n):
            without = masks[(masks >> i) & 1 == 0]
            with_i = without | (1 << i)
            w = weights[sizes[without]]
            share_p[i] = float(np.sum(w * (prob[with_i] - prob[without])))
            share_m[i] = float(np.sum(w * (dist[with_i] - dist[without])))
    else:
        rng = np.random.default_rng(seed)
        paths = [rng.permutation(n) for _ in range(orders)]
        needed = {0}
        for path in paths:
            mask = 0
            for i in path:
                mask |= 1 << int(i)
                needed.add(mask)
        order = sorted(needed)
        index = {m: k for k, m in enumerate(order)}
        prob, dist = _batch_scores([features_for(m) for m in order], art)
        for path in paths:
            mask = 0
            for i in path:
                new = mask | 1 << int(i)
                share_p[i] += prob[index[new]] - prob[index[mask]]
                share_m[i] += dist[index[new]] - dist[index[mask]]
                mask = new
        share_p /= orders
        share_m /= orders
    table = pd.DataFrame(
        {
            "input": names,
            "value": [getattr(inputs, name) for name in names],
            "typical": [getattr(typical, name) for name in names],
            "delta_probability": share_p,
            "delta_mahalanobis": share_m,
        },
        columns=columns,
    )
    if not table.empty:
        moved = (table["delta_probability"].abs() > 1e-9) | (
            table["delta_mahalanobis"].abs() > 1e-9
        )
        table = table[moved]
        table = table.reindex(table["delta_probability"].abs().sort_values(ascending=False).index)
    return table.reset_index(drop=True)
