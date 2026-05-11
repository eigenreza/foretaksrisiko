"""The demo: artefact export on a fake warehouse, synthetic-company scoring and the app pages.

Everything here is invented: a small model fitted on random rows, peer statistics drawn from
random numbers, and demo tables with made-up aggregates. No file written by these tests may
contain a nine-digit number.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from foretaksrisiko.config import ModelConfig, Settings
from foretaksrisiko.demo import artefacts as artefact_export
from foretaksrisiko.demo.synthetic import (
    QUANTILE_GRID,
    RATIO_FEATURES,
    Artefacts,
    Inputs,
    _percentile,
    build_features,
    drivers,
    peer_position,
    score,
)
from foretaksrisiko.figures.export import write_csv
from foretaksrisiko.lakehouse.session import Names
from foretaksrisiko.models.supervised import fit_supervised

ROOT = Path(__file__).resolve().parents[1]
NINE_DIGITS = re.compile(r"(?<![0-9A-Za-z])\d{9}(?![0-9A-Za-z])")
NAMES = Names(catalog="cat", prefix="p_")
FEATURES = [
    "is_asa",
    "age_years",
    "years_registered",
    "kapital_belop",
    "log_kapital",
    "har_registrert_antall_ansatte",
    "nace_section",
    "nace_division",
    "fylke_code",
    "board_size",
    "has_ceo",
    "ceo_is_chair",
    "has_auditor",
    "has_accountant",
    "n_changes_12m",
    "days_since_board_change",
    "has_accounts",
    "acc_sum_eiendeler",
    "acc_sum_driftsinntekter",
    "acc_age_days",
    "acc_filing_lag_days",
    "acc_n_statements_known",
    "equity_ratio",
    "operating_margin",
    "interest_burden",
    "log_revenue",
    "log_assets",
    "negative_equity",
    "loss",
    "size_band",
    "z_equity_ratio",
    "pct_equity_ratio",
    "z_log_assets",
    "pct_log_assets",
    "z_age_years",
    "pct_age_years",
    "n_extreme_z",
]
CATEGORICAL = ["nace_section", "nace_division", "fylke_code", "size_band"]
LEVELS = {
    "nace_section": ["F", "K", "M"],
    "nace_division": ["41", "62", "68"],
    "fylke_code": ["03", "46", "21"],
    "size_band": ["0", "1", "2", "3", "4", "5"],
}
MODES = {"nace_section": "K", "nace_division": "62", "fylke_code": "03", "size_band": "2"}
GROUPS = ["division:62|2", "section:K|2", "all:2", "all:0", "division:68|3", "all:3", "all:1"]
Z_COLUMNS = ["z_equity_ratio", "z_log_assets", "z_age_years"]


def _random_frame(rng: np.random.Generator, rows: int) -> pd.DataFrame:
    frame = pd.DataFrame(index=range(rows))
    for column in FEATURES:
        if column in CATEGORICAL:
            frame[column] = pd.Categorical(
                rng.choice(LEVELS[column], size=rows), categories=LEVELS[column]
            )
        elif column.startswith("pct_"):
            frame[column] = rng.uniform(0, 1, size=rows).astype("float32")
        elif column.startswith("z_"):
            frame[column] = rng.normal(0, 1.5, size=rows).astype("float32")
        elif column == "acc_age_days":
            frame[column] = rng.integers(100, 1200, size=rows).astype("float32")
        else:
            frame[column] = rng.uniform(0, 10, size=rows).astype("float32")
    return frame


def _fitted_model():
    rng = np.random.default_rng(7)
    train, valid = _random_frame(rng, 600), _random_frame(rng, 300)
    cfg = ModelConfig(
        hgb_grid_learning_rate=[0.1],
        hgb_grid_max_leaf_nodes=[7],
        hgb_grid_min_samples_leaf=[20],
        hgb_max_iter=40,
    )

    def label(frame: pd.DataFrame) -> np.ndarray:
        logit = -3.0 + 0.004 * frame["acc_age_days"].to_numpy() - 0.3 * frame["z_equity_ratio"]
        return (rng.uniform(size=len(frame)) < 1 / (1 + np.exp(-logit))).astype(int)

    fill_values = {"has_auditor": False, "board_size": 1.0, "nace_section": "K"}
    return fit_supervised(
        train, label(train), valid, label(valid), CATEGORICAL, cfg, 1, fill_values
    )


def _fake_query(statement: str) -> list[dict]:
    sql = " ".join(statement.split())
    rng = np.random.default_rng(abs(hash(sql)) % (2**32))
    if ".peer_stats" in sql:
        return [
            {"peer_group": g, "feature": f, "n": "50", "median": str(2 + i), "mad": "0.8"}
            for g in GROUPS
            for i, f in enumerate(RATIO_FEATURES)
        ]
    if "percentile_approx(CAST(" in sql:
        names = re.findall(r"AS (\w+)", sql)
        row = {name: "0.5" for name in names}
        row.update({"acc_sum_eiendeler": "500000", "kapital_belop": "30000", "has_accounts": "1"})
        row.update({"acc_sum_driftsinntekter": "123456789.0", "age_years": "8", "board_size": "1"})
        return [row]
    if "array(" in sql:
        feature = re.search(r"percentile_approx\((\w+), array", sql).group(1)
        base = 2 + RATIO_FEATURES.index(feature)
        return [
            {
                "peer_group": g,
                "n": "50",
                "q": json.dumps([round(base + 0.8 * (q - 0.5) * 4, 4) for q in QUANTILE_GRID]),
            }
            for g in GROUPS
        ]
    if "ORDER BY n DESC LIMIT 1" in sql:
        column = re.search(r"SELECT (\w+) AS value", sql).group(1)
        return [{"value": MODES[column], "n": "100"}]
    if "min(log_assets)" in sql:
        return [
            {"size_band": "0", "lo": None, "hi": None, "n": "900"},
            {"size_band": "1", "lo": "0", "hi": "12", "n": "100"},
            {"size_band": "2", "lo": "12.001", "hi": "14", "n": "100"},
            {"size_band": "3", "lo": "14.001", "hi": "16", "n": "100"},
            {"size_band": "4", "lo": "16.001", "hi": "18", "n": "60"},
            {"size_band": "5", "lo": "18.001", "hi": "30", "n": "40"},
        ]
    if "xxhash64" in sql:
        columns = re.search(r"SELECT (.+?) FROM", sql).group(1).split(", ")
        return [
            {c: (None if rng.uniform() < 0.1 else str(round(rng.normal(), 4))) for c in columns}
            for _ in range(300)
        ]
    raise AssertionError(f"unexpected statement: {sql[:120]}")


def _fake_code_lists(http, klass, out: Path) -> dict[str, int]:
    divisions = [
        {"code": "41", "section": "F", "name_no": "Bygg", "name_en": "Construction"},
        {"code": "62", "section": "K", "name_no": "IT", "name_en": "IT"},
        {"code": "68", "section": "M", "name_no": "Eiendom", "name_en": "Real estate"},
        {"code": "99", "section": "V", "name_no": "Ukjent", "name_en": "Unknown"},
    ]
    fylker = [
        {"code": "03", "name_no": "Oslo", "name_en": "Oslo"},
        {"code": "46", "name_no": "Vestland", "name_en": "Vestland"},
        {"code": "21", "name_no": "Svalbard", "name_en": "Svalbard"},
    ]
    return {
        "nace_divisions.csv": write_csv(
            out / "nace_divisions.csv", divisions, ["code", "section", "name_no", "name_en"]
        ),
        "fylker.csv": write_csv(out / "fylker.csv", fylker, ["code", "name_no", "name_en"]),
    }


def _demo_tables(demo_dir: Path) -> None:
    """Small aggregate tables with the same columns as the real exports."""
    models = ["rule", "isolation_forest", "mahalanobis", "hgb_calibrated"]
    metrics = []
    for model in models:
        for ablation in ["all", "no_accounts"] if model == "hgb_calibrated" else ["all"]:
            for metric, value in [
                ("average_precision", 0.25),
                ("precision_top_1pct", 0.2),
                ("precision_top_5pct", 0.08),
                ("lift_top_1pct", 30.0),
                ("lift_top_5pct", 12.0),
                ("roc_auc", 0.88),
                ("brier", 0.004),
                ("expected_calibration_error", 0.001),
            ]:
                metrics.append(
                    {
                        "model": model,
                        "ablation": ablation,
                        "split": "test",
                        "seed": 1,
                        "metric": metric,
                        "value": value if model == "hgb_calibrated" else value / 10,
                        "ci_low": value * 0.6 if metric == "average_precision" else None,
                        "ci_high": value * 1.4 if metric == "average_precision" else None,
                    }
                )
    write_csv(
        demo_dir / "evaluation_metrics.csv",
        metrics,
        ["model", "ablation", "split", "seed", "metric", "value", "ci_low", "ci_high"],
    )
    write_csv(
        demo_dir / "calibration.csv",
        [
            {"bin": b, "n": 900, "mean_predicted": b * 0.002, "observed_rate": b * 0.0021}
            for b in range(1, 11)
        ],
        ["bin", "n", "mean_predicted", "observed_rate"],
    )
    write_csv(
        demo_dir / "explanations.csv",
        [
            {"model": "hgb", "feature": f, "mean_abs_shap": 0.01 / (i + 1), "ratio": None}
            for i, f in enumerate(["acc_age_days", "nace_division", "age_years", "has_auditor"])
        ]
        + [
            {"model": "mahalanobis", "feature": "z_equity_ratio", "mean_abs_shap": None, "ratio": 2}
        ],
        ["model", "feature", "mean_abs_shap", "ratio"],
    )
    fairness = []
    for model in ["hgb_calibrated", "isolation_forest"]:
        for per_group in ["false", "true"]:
            for group_type, values in [("fylke", ["03", "46"]), ("size_band", ["0", "2"])]:
                for value in values:
                    fairness.append(
                        {
                            "model": model,
                            "group_type": group_type,
                            "group_value": value,
                            "group_label_no": f"Gruppe {value}",
                            "group_label_en": f"Group {value}",
                            "n": 1500,
                            "base_rate": 0.005,
                            "flag_rate": 0.05,
                            "precision": 0.06,
                            "per_group_threshold": per_group,
                        }
                    )
    write_csv(
        demo_dir / "fairness.csv",
        fairness,
        [
            "model",
            "group_type",
            "group_value",
            "group_label_no",
            "group_label_en",
            "n",
            "base_rate",
            "flag_rate",
            "precision",
            "per_group_threshold",
        ],
    )
    write_csv(
        demo_dir / "network_degree.csv",
        [
            {"kind": kind, "size_bin": b, "bin_order": i, "n_companies": 100 * (i + 1)}
            for kind in ["auditor", "accountant"]
            for i, b in enumerate(["1", "2-4", "5-9"])
        ],
        ["kind", "size_bin", "bin_order", "n_companies"],
    )
    write_csv(
        demo_dir / "population_by_fylke.csv",
        [
            {"snapshot_id": 1, "fylke_code": "03", "fylke_name": "Oslo", "n": 8000},
            {"snapshot_id": 1, "fylke_code": "46", "fylke_name": "Vestland", "n": 4000},
        ],
        ["snapshot_id", "fylke_code", "fylke_name", "n"],
    )
    write_csv(
        demo_dir / "population_by_section.csv",
        [
            {
                "snapshot_id": 1,
                "nace_section": "K",
                "section_label_no": "IT",
                "section_label_en": "IT",
                "n": 5000,
            },
            {
                "snapshot_id": 1,
                "nace_section": "M",
                "section_label_no": "Eiendom",
                "section_label_en": "Real estate",
                "n": 9000,
            },
        ],
        ["snapshot_id", "nace_section", "section_label_no", "section_label_en", "n"],
    )
    write_csv(
        demo_dir / "score_quantiles.csv",
        [
            {
                "model": m,
                "split": "test",
                "quantile": q / 100,
                "value": q / 100 * (0.05 if m == "hgb_calibrated" else 3),
            }
            for m in models
            for q in range(1, 100)
        ],
        ["model", "split", "quantile", "value"],
    )
    write_csv(
        demo_dir / "topk.csv",
        [
            {
                "model": m,
                "share": s,
                "precision": 0.2 / (i + 1),
                "lift": 30 / (i + 1),
                "recall": 0.1 * (i + 1),
            }
            for m in models
            for i, s in enumerate([0.005, 0.01, 0.02, 0.05, 0.1, 0.2])
        ],
        ["model", "share", "precision", "lift", "recall"],
    )
    write_csv(
        demo_dir / "drift.csv",
        [
            {
                "snapshot_id": 2,
                "reference_snapshot_id": 1,
                "scenario": scenario,
                "feature": f,
                "metric": "psi",
                "value": 0.05 * (i + 1),
                "severity": ["", "warn", "alert"][i % 3],
            }
            for scenario in ["default", "simulated_breach"]
            for i, f in enumerate(["age_years", "acc_age_days", "equity_ratio"])
        ],
        [
            "snapshot_id",
            "reference_snapshot_id",
            "scenario",
            "feature",
            "metric",
            "value",
            "severity",
        ],
    )
    write_csv(
        demo_dir / "score_summary.csv",
        [
            {
                "snapshot_id": s,
                "scenario": "default",
                "side": "current",
                "n": 40000,
                "mean": 0.005,
                "p50": 0.001,
                "p90": 0.01,
                "p99": 0.1,
                "flag_share": 0.05,
            }
            for s in [1, 2]
        ],
        ["snapshot_id", "scenario", "side", "n", "mean", "p50", "p90", "p99", "flag_share"],
    )


@pytest.fixture(scope="module")
def demo_root(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """A repository-shaped directory with demo tables, a figure and exported artefacts."""
    root = tmp_path_factory.mktemp("demo_root")
    demo_dir = root / "demo_data"
    demo_dir.mkdir()
    (root / "figures").mkdir()
    (root / "figures" / "pipeline_no.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<rect width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    _demo_tables(demo_dir)
    fitted = _fitted_model()
    info = {
        "model_name": "cat.p_gold.test_model",
        "alias": "champion",
        "version": "1",
        "tags": {"design": "retro", "snapshot_id": "1", "scope": "sample"},
    }
    original = artefact_export.export_code_lists
    artefact_export.export_code_lists = _fake_code_lists
    try:
        counts = artefact_export.export_all(
            _fake_query,
            NAMES,
            Settings(),
            demo_dir / "model",
            "cat.p_gold.test_model",
            "champion",
            fitted,
            info,
        )
    finally:
        artefact_export.export_code_lists = original
    assert counts["peer_stats.csv"] == len(GROUPS) * len(RATIO_FEATURES)
    assert counts["mahalanobis.json"] == 300
    return root


@pytest.fixture(scope="module")
def art(demo_root: Path) -> Artefacts:
    return Artefacts.load(demo_root / "demo_data" / "model")


def test_ratio_features_match_the_lakehouse() -> None:
    from foretaksrisiko.lakehouse import features

    assert RATIO_FEATURES == features.RATIO_FEATURES


def test_exported_files_have_no_nine_digit_numbers(demo_root: Path) -> None:
    model_dir = demo_root / "demo_data" / "model"
    names = {p.name for p in model_dir.iterdir()}
    assert {"hgb_calibrated.joblib", "hgb_meta.json", "mahalanobis.json", "peer_stats.csv"} <= names
    for path in model_dir.glob("*"):
        if path.suffix in (".csv", ".json"):
            assert not NINE_DIGITS.search(path.read_text(encoding="utf-8")), path.name
    defaults = pd.read_csv(model_dir / "feature_defaults.csv", dtype=str)
    revenue = defaults.loc[defaults["feature"] == "acc_sum_driftsinntekter", "value"].iloc[0]
    assert float(revenue) == pytest.approx(123457000.0)
    meta = json.loads((model_dir / "hgb_meta.json").read_text(encoding="utf-8"))
    assert meta["features"] == FEATURES and meta["version"] == "1"


def test_format_uses_six_significant_digits() -> None:
    assert artefact_export._fmt(123456789.0) == "1.23457e+08"
    assert artefact_export._fmt(None) is None
    assert artefact_export._fmt("0.123456789") == "0.123457"


def test_typical_company_scores_within_its_peer_group(art: Artefacts) -> None:
    typical = art.typical_inputs()
    assert typical.has_accounts and typical.nace_division == "62"
    features, context = build_features(typical, art)
    assert context["peer_group"] == "division:62|2"
    assert features["size_band"] == "2" and features["has_accounts"] == 1.0
    result = score(features, art)
    assert 0.0 <= result.probability <= 1.0
    assert result.mahalanobis >= 0.0
    assert result.mahalanobis_percentile is not None
    position = peer_position(features, context["peer_group"], art)
    assert position["z"].notna().sum() == len(RATIO_FEATURES)


def test_peer_group_falls_back_to_section_then_band(art: Artefacts) -> None:
    assert art.peer_group_for("41", "K", "2") == "section:K|2"
    assert art.peer_group_for("41", "F", "2") == "all:2"
    assert art.peer_group_for("68", "M", "3") == "division:68|3"
    assert art.size_band_for(float("nan")) == "0"
    assert art.size_band_for(13.0) == "2"
    assert art.size_band_for(99.0) == "5"


def test_no_accounts_company_has_missing_ratio_features(art: Artefacts) -> None:
    inputs = replace(art.typical_inputs(), has_accounts=False)
    features, context = build_features(inputs, art)
    assert context["size_band"] == "0"
    assert np.isnan(features["equity_ratio"]) and np.isnan(features["z_equity_ratio"])
    assert not np.isnan(features["z_age_years"])
    result = score(features, art)
    assert 0.0 <= result.probability <= 1.0


def test_drivers_list_only_inputs_that_changed_the_scores(art: Artefacts) -> None:
    typical = art.typical_inputs()
    assert drivers(typical, art, typical).empty
    changed = replace(typical, acc_age_days=typical.acc_age_days + 700, equity_ratio=-0.5)
    table = drivers(changed, art, typical)
    assert set(table["input"]) <= {"acc_age_days", "equity_ratio"}
    moved = (table["delta_probability"].abs() > 0) | (table["delta_mahalanobis"].abs() > 0)
    assert moved.all()


def test_percentile_interpolates_between_grid_points() -> None:
    points = np.array([float(i) for i in range(len(QUANTILE_GRID))])
    assert _percentile(-1.0, points, QUANTILE_GRID) == pytest.approx(QUANTILE_GRID[0] / 2)
    assert _percentile(100.0, points, QUANTILE_GRID) == pytest.approx((QUANTILE_GRID[-1] + 1) / 2)
    assert _percentile(0.5, points, QUANTILE_GRID) == pytest.approx(0.075)
    assert _percentile(3.0, points, QUANTILE_GRID) == pytest.approx(QUANTILE_GRID[3])


def test_charts_use_norwegian_number_format_only_in_the_norwegian_view() -> None:
    alt = pytest.importorskip("altair")
    sys.path.insert(0, str(ROOT / "app"))
    from demo_ui import charts

    chart = alt.Chart(pd.DataFrame({"group": ["a", "b"], "n": [100_000, 2_500]})).mark_bar()
    chart = chart.encode(x="n:Q", y="group:N")
    number = charts.localized(chart, "no").to_dict()["config"]["locale"]["number"]
    assert number["decimal"] == "," and number["thousands"] == " "
    assert "locale" not in charts.localized(chart, "en").to_dict().get("config", {})


def test_inputs_field_names_have_labels() -> None:
    sys.path.insert(0, str(ROOT / "app"))
    from demo_ui.texts import TEXT

    for name in Inputs.__dataclass_fields__:
        assert f"prov.in.{name}" in TEXT, name
    for key, value in TEXT.items():
        assert set(value) == {"no", "en"}, key
        assert chr(0x2014) not in value["no"] + value["en"], key


@pytest.mark.parametrize(
    ("lang", "page"),
    [
        ("no", "oversikt"),
        ("no", "monstre"),
        ("no", "modellen"),
        ("no", "prov_selv"),
        ("no", "overvaking"),
        ("no", "personvern"),
        ("en", "prov_selv"),
        ("en", "modellen"),
    ],
)
def test_app_pages_render_without_errors(demo_root: Path, lang: str, page: str) -> None:
    apptest = pytest.importorskip("streamlit.testing.v1")
    sys.path.insert(0, str(ROOT / "app"))
    previous = os.environ.get("FORETAKSRISIKO_DEMO_ROOT")
    os.environ["FORETAKSRISIKO_DEMO_ROOT"] = str(demo_root)
    try:
        at = apptest.AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120)
        at.session_state["lang"] = lang
        at.session_state["page"] = page
        at.run()
    finally:
        if previous is None:
            del os.environ["FORETAKSRISIKO_DEMO_ROOT"]
        else:
            os.environ["FORETAKSRISIKO_DEMO_ROOT"] = previous
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.title, "the page has no title"
    text = " ".join(m.value for m in at.markdown)
    assert chr(0x2014) not in text
    assert not NINE_DIGITS.search(text)


def test_overview_button_opens_the_try_it_page(demo_root: Path) -> None:
    apptest = pytest.importorskip("streamlit.testing.v1")
    sys.path.insert(0, str(ROOT / "app"))
    previous = os.environ.get("FORETAKSRISIKO_DEMO_ROOT")
    os.environ["FORETAKSRISIKO_DEMO_ROOT"] = str(demo_root)
    try:
        at = apptest.AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120)
        at.run()
        at.button(key="open_try").click().run()
    finally:
        if previous is None:
            del os.environ["FORETAKSRISIKO_DEMO_ROOT"]
        else:
            os.environ["FORETAKSRISIKO_DEMO_ROOT"] = previous
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["page"] == "prov_selv"
