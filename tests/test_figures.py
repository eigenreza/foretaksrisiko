"""Figure rendering on small synthetic aggregate tables, in both languages.

All numbers are invented. Group labels are placeholders, snapshot ids are small integers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from foretaksrisiko.figures import build
from foretaksrisiko.figures.style import (
    ABLATION_NAMES,
    FEATURE_NAMES,
    GROUP_TYPE_NAMES,
    KIND_NAMES,
    LABELS,
    LANGUAGES,
    METRIC_NAMES,
    MODEL_NAMES,
    Labels,
)

MODELS = ["rule", "isolation_forest", "mahalanobis", "hgb_calibrated"]
ABLATIONS = ["all", "no_network", "no_accounts", "no_text", "register_roles_only"]
METRICS = ["average_precision", "precision_top_1pct", "precision_top_5pct", "roc_auc", "brier"]
SIZE_BINS = ["1", "2-4", "5-9", "10-19", "20-49", "50-99", "100-199", "200-499", "500+"]
FEATURES = [
    "equity_ratio",
    "debt_ratio",
    "operating_margin",
    "log_revenue",
    "board_size",
    "has_auditor",
    "acc_filing_lag_days",
    "nace_section",
    "fylke_code",
    "age_years",
    "n_changes_12m",
    "auditor_portfolio_size",
    "text_sim_own_code",
    "z_equity_ratio",
    "negative_equity",
    "size_band",
    "unknown_feature_a",
    "unknown_feature_b",
]
EM_DASH = chr(0x2014)


def _evaluation_metrics(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for model in MODELS:
        for ablation in ABLATIONS if model == "hgb_calibrated" else ["all"]:
            for split in ("valid", "test"):
                for seed in (1, 2):
                    for metric in METRICS:
                        value = float(rng.uniform(0.05, 0.9))
                        with_ci = metric in ("average_precision", "precision_top_1pct")
                        rows.append(
                            {
                                "model": model,
                                "ablation": ablation,
                                "split": split,
                                "seed": seed,
                                "metric": metric,
                                "value": value,
                                "ci_low": value - 0.03 if with_ci else None,
                                "ci_high": value + 0.03 if with_ci else None,
                            }
                        )
    # One row without seed and without an interval, to exercise the empty cases.
    rows.append(
        {
            "model": "hgb_calibrated",
            "ablation": "no_text",
            "split": "test",
            "seed": None,
            "metric": "precision_top_1pct",
            "value": 0.4,
            "ci_low": None,
            "ci_high": None,
        }
    )
    return pd.DataFrame(rows)


def _calibration() -> pd.DataFrame:
    predicted = np.array([0.001, 0.003, 0.006, 0.01, 0.02, 0.04, 0.07, 0.12, 0.2, 0.35])
    observed = predicted * np.array([0.0, 1.3, 0.8, 1.1, 0.9, 1.0, 1.2, 0.95, 0.85, 1.05])
    return pd.DataFrame(
        {
            "bin": np.arange(1, 11),
            "n": [5000, 4000, 3000, 2000, 1500, 1000, 600, 300, 150, 60],
            "mean_predicted": predicted,
            "observed_rate": observed,
        }
    )


def _explanations(rng: np.random.Generator) -> pd.DataFrame:
    rows = [
        {
            "model": "hgb",
            "feature": f,
            "mean_abs_shap": float(rng.uniform(0.01, 0.5)),
            "ratio": None,
        }
        for f in FEATURES
    ]
    rows += [
        {"model": model, "feature": f, "mean_abs_shap": None, "ratio": float(rng.uniform(0.5, 3))}
        for model in ("mahalanobis", "rule")
        for f in FEATURES[:5]
    ]
    return pd.DataFrame(rows)


def _fairness(rng: np.random.Generator) -> pd.DataFrame:
    groups = {
        "fylke": [(f"{i:02d}", f"Fylke {c}", f"County {c}") for i, c in enumerate("ABCDE", 3)],
        "nace_section": [(c, f"Område {c}", f"Section {c}") for c in "FGHJ"],
        "age_band": [("0-2", "0-2", "0-2"), ("3-9", "3-9", "3-9"), ("10+", "10+", "10+")],
        "size_band": [("micro", "Mikro", "Micro"), ("small", "Liten", "Small")],
    }
    rows = []
    for model in ("hgb_calibrated", "isolation_forest"):
        for group_type, values in groups.items():
            for value, label_no, label_en in values:
                for per_group in (False, True):
                    base = float(rng.uniform(0.005, 0.03))
                    rows.append(
                        {
                            "model": model,
                            "group_type": group_type,
                            "group_value": value,
                            "group_label_no": label_no,
                            "group_label_en": label_en,
                            "n": int(rng.integers(200, 5000)),
                            "base_rate": base,
                            "flag_rate": base * float(rng.uniform(0.5, 2.0)),
                            "precision": float(rng.uniform(0.05, 0.4)),
                            "per_group_threshold": per_group,
                        }
                    )
    return pd.DataFrame(rows)


def _population_by_section(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for snapshot in (1, 2):
        for code in "ABCFGHJKLM":
            rows.append(
                {
                    "snapshot_id": snapshot,
                    "nace_section": code,
                    "section_label_no": f"Område {code}",
                    "section_label_en": f"Section {code}",
                    "n": int(rng.integers(500, 40000)),
                }
            )
    return pd.DataFrame(rows)


def _population_by_fylke(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for snapshot in (1, 2):
        for index, code in enumerate("ABCDEFGH", 3):
            rows.append(
                {
                    "snapshot_id": snapshot,
                    "fylke_code": f"{index:02d}",
                    "fylke_name": f"Fylke {code}",
                    "n": int(rng.integers(2000, 60000)),
                }
            )
    return pd.DataFrame(rows)


def _score_quantiles(rng: np.random.Generator) -> pd.DataFrame:
    quantiles = np.round(np.arange(0.01, 1.0, 0.01), 2)
    rows = []
    for model in MODELS:
        for split in ("valid", "test"):
            values = np.sort(rng.exponential(0.05 if model == "hgb_calibrated" else 1.0, 99))
            rows += [
                {"model": model, "split": split, "quantile": q, "value": float(v)}
                for q, v in zip(quantiles, values, strict=True)
            ]
    return pd.DataFrame(rows)


def _topk(rng: np.random.Generator) -> pd.DataFrame:
    shares = [0.005, 0.01, 0.02, 0.05, 0.10, 0.20]
    rows = []
    for model in MODELS:
        precision = np.sort(rng.uniform(0.02, 0.5, len(shares)))[::-1]
        rows += [
            {
                "model": model,
                "share": share,
                "precision": float(p),
                "lift": float(p / 0.02),
                "recall": float(min(1.0, share * 8)),
            }
            for share, p in zip(shares, precision, strict=True)
        ]
    return pd.DataFrame(rows)


def _network_degree(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for kind in ("auditor", "accountant"):
        counts = np.sort(rng.integers(1, 50000, len(SIZE_BINS)))[::-1]
        counts[-1] = 0
        rows += [
            {"kind": kind, "size_bin": b, "bin_order": i, "n_companies": int(c)}
            for i, (b, c) in enumerate(zip(SIZE_BINS, counts, strict=True))
        ]
    return pd.DataFrame(rows)


def _drift(rng: np.random.Generator, snapshots: tuple[int, ...] = (2, 3, 4)) -> pd.DataFrame:
    rows = []
    for snapshot in snapshots:
        for scenario in ("default", "stress"):
            for feature in FEATURES[:12]:
                for metric in ("psi", "missing_rate", "max_share_delta"):
                    value = float(rng.uniform(0, 0.4)) if metric == "psi" else float(rng.uniform())
                    rows.append(
                        {
                            "snapshot_id": snapshot,
                            "reference_snapshot_id": snapshot - 1,
                            "scenario": scenario,
                            "feature": feature,
                            "metric": metric,
                            "value": value,
                            "severity": "ok" if value < 0.1 else "warn",
                        }
                    )
    return pd.DataFrame(rows)


def _score_summary(
    rng: np.random.Generator, snapshots: tuple[int, ...] = (2, 3, 4)
) -> pd.DataFrame:
    rows = []
    for snapshot in snapshots:
        for scenario in ("default", "stress"):
            for side in ("reference", "current"):
                rows.append(
                    {
                        "snapshot_id": snapshot,
                        "scenario": scenario,
                        "side": side,
                        "n": int(rng.integers(10000, 50000)),
                        "mean": float(rng.uniform(0.01, 0.05)),
                        "p50": float(rng.uniform(0.005, 0.02)),
                        "p90": float(rng.uniform(0.05, 0.1)),
                        "p99": float(rng.uniform(0.3, 0.6)),
                        "flag_share": float(rng.uniform(0.005, 0.02)),
                    }
                )
    return pd.DataFrame(rows)


def write_demo(demo_dir: Path, snapshots: tuple[int, ...] = (2, 3, 4)) -> None:
    rng = np.random.default_rng(7)
    demo_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "evaluation_metrics.csv": _evaluation_metrics(rng),
        "calibration.csv": _calibration(),
        "explanations.csv": _explanations(rng),
        "fairness.csv": _fairness(rng),
        "population_by_section.csv": _population_by_section(rng),
        "population_by_fylke.csv": _population_by_fylke(rng),
        "score_quantiles.csv": _score_quantiles(rng),
        "topk.csv": _topk(rng),
        "network_degree.csv": _network_degree(rng),
        "drift.csv": _drift(rng, snapshots),
        "score_summary.csv": _score_summary(rng, snapshots),
    }
    for name, frame in tables.items():
        frame.to_csv(demo_dir / name, index=False, encoding="utf-8")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, list[Path]]]:
    base = tmp_path_factory.mktemp("figures")
    write_demo(base / "demo")
    out_dir = base / "out"
    written = {lang: build.render_all(base / "demo", out_dir, lang) for lang in LANGUAGES}
    return out_dir, written


def test_render_all_writes_svg_and_png_for_every_figure(rendered) -> None:
    out_dir, written = rendered
    for lang in LANGUAGES:
        expected = {
            out_dir / f"{name}_{lang}.{fmt}" for name in build.FIGURES for fmt in ("svg", "png")
        }
        assert set(written[lang]) == expected
        for path in expected:
            assert path.is_file()
            assert path.stat().st_size > 0
    png_paths = [p for paths in written.values() for p in paths if p.suffix == ".png"]
    for path in png_paths:
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_svg_files_carry_no_date_and_no_em_dash(rendered) -> None:
    out_dir, written = rendered
    svg_paths = [p for paths in written.values() for p in paths if p.suffix == ".svg"]
    assert len(svg_paths) == len(build.FIGURES) * len(LANGUAGES)
    for path in svg_paths:
        svg_text = path.read_text(encoding="utf-8")
        assert "<dc:date>" not in svg_text
        assert "Date" not in svg_text[:2000]
        assert EM_DASH not in svg_text


def test_svg_text_is_kept_as_text_in_the_chosen_language(rendered) -> None:
    out_dir, _written = rendered
    for lang in LANGUAGES:
        svg_text = (out_dir / f"topk_{lang}.svg").read_text(encoding="utf-8")
        assert LABELS["topk.title"][lang] in svg_text
        assert MODEL_NAMES["rule"][lang] in svg_text


def test_render_all_with_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    demo_dir = tmp_path / "empty"
    demo_dir.mkdir()
    assert build.render_all(demo_dir, tmp_path / "out", "no") == []
    assert build.render_all(demo_dir, tmp_path / "out", "en") == []


def test_render_all_renders_only_figures_with_inputs(tmp_path: Path) -> None:
    demo_dir = tmp_path / "partial"
    demo_dir.mkdir()
    _topk(np.random.default_rng(1)).to_csv(demo_dir / "topk.csv", index=False)
    written = build.render_all(demo_dir, tmp_path / "out", "en")
    assert sorted(p.name for p in written) == [
        "pipeline_en.png",
        "pipeline_en.svg",
        "topk_en.png",
        "topk_en.svg",
    ]


def test_drift_with_a_single_snapshot_renders(tmp_path: Path) -> None:
    demo_dir = tmp_path / "single"
    demo_dir.mkdir()
    rng = np.random.default_rng(3)
    _drift(rng, (5,)).to_csv(demo_dir / "drift.csv", index=False)
    _score_summary(rng, (5,)).to_csv(demo_dir / "score_summary.csv", index=False)
    written = build.render_all(demo_dir, tmp_path / "out", "no")
    assert (tmp_path / "out" / "drift_no.svg") in written


def test_render_all_rejects_unknown_language(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build.render_all(tmp_path, tmp_path / "out", "de")


def test_every_label_exists_in_both_languages() -> None:
    tables = [LABELS, MODEL_NAMES, ABLATION_NAMES, FEATURE_NAMES, GROUP_TYPE_NAMES, KIND_NAMES]
    tables.append(METRIC_NAMES)
    for table in tables:
        for key, entry in table.items():
            assert set(entry) == set(LANGUAGES), key
            for lang in LANGUAGES:
                assert entry[lang].strip(), (key, lang)
                assert EM_DASH not in entry[lang], (key, lang)


def test_labels_fall_back_to_the_identifier() -> None:
    labels = Labels("en")
    assert labels.feature("not_a_known_feature") == "not_a_known_feature"
    assert labels.model("hgb") == labels.model("hgb_calibrated")
    assert Labels("no").percent(2.5) == "2,5 %"
    assert Labels("en").percent(2.5) == "2.5%"
    assert Labels("en").number(12345) == "12,345"
