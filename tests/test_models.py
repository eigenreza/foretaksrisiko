"""Model training and evaluation on a synthetic feature table with planted signal."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
pytest.importorskip("scipy")

from conftest import fake_orgnr  # noqa: E402
from foretaksrisiko.config import ModelConfig  # noqa: E402
from foretaksrisiko.evaluation.fairness import fairness_table  # noqa: E402
from foretaksrisiko.evaluation.metrics import (  # noqa: E402
    bootstrap_interval,
    calibration_table,
    precision_at_share,
    stability,
    top_overlap,
)
from foretaksrisiko.models.data import MASK_GOVERNS, feature_group, prepare, split_companies  # noqa: E402
from foretaksrisiko.models.train import run_experiment  # noqa: E402

CFG = ModelConfig(
    seeds=[1, 2],
    bootstrap_samples=40,
    iforest_estimators=50,
    iforest_max_samples=500,
    mahalanobis_fit_rows=800,
    hgb_grid_learning_rate=[0.1],
    hgb_grid_max_leaf_nodes=[15],
    hgb_grid_min_samples_leaf=[20],
    hgb_max_iter=60,
    shap_rows=200,
)


def synthetic_frame(n: int = 3000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    equity = rng.normal(0.3, 0.3, n)
    age = rng.gamma(2.0, 4.0, n)
    z_eq = (equity - np.median(equity)) / 0.3
    logit = -3.0 - 5.0 * equity - 0.1 * age + rng.normal(0, 0.3, n)
    label = rng.random(n) < 1 / (1 + np.exp(-logit))
    sections = rng.choice(list("ABCDEFG"), n, p=[0.3, 0.2, 0.15, 0.15, 0.1, 0.05, 0.05])
    frame = pd.DataFrame(
        {
            "design": "retro",
            "reference_snapshot_id": 1,
            "reference_date": "x",
            "organisasjonsnummer": [fake_orgnr(100_000 + i) for i in range(n)],
            "peer_group": "all:1",
            "age_years": age.astype("float32"),
            "kapital_belop": rng.lognormal(10.5, 1.0, n),
            "log_kapital": rng.normal(10.5, 1.0, n),
            "nace_section": sections,
            "nace_division": rng.choice(["41", "62", "68", "70"], n),
            "fylke_code": rng.choice(["03", "11", "46"], n, p=[0.6, 0.3, 0.1]),
            "size_band": rng.choice(["0", "1", "2", "3"], n),
            "board_size": rng.integers(1, 5, n).astype("float32"),
            "has_ceo": rng.random(n) < 0.7,
            "auditor_portfolio_size": np.where(
                rng.random(n) < 0.3, rng.integers(1, 200, n), np.nan
            ),
            "has_accounts": True,
            "equity_ratio": equity,
            "z_equity_ratio": z_eq,
            "z_log_assets": rng.normal(0, 1, n),
            "z_age_years": (age - np.median(age)) / 5,
            "pct_equity_ratio": rng.random(n),
            "n_extreme_z": (np.abs(z_eq) > 3).astype(int),
            "text_sim_own_code": rng.random(n),
            "antall_ansatte": np.where(rng.random(n) < 0.1, rng.integers(5, 50, n), np.nan),
            "masked_kapital": rng.random(n) < 0.05,
            "masked_board": rng.random(n) < 0.1,
            "any_change_after_t": True,
            "label_strict": label,
            "label_broad": label | (rng.random(n) < 0.01),
            "eligible": True,
        }
    )
    return frame


def test_split_is_deterministic_and_balanced() -> None:
    frame = synthetic_frame(5000)
    split = split_companies(frame["organisasjonsnummer"], CFG)
    again = split_companies(frame["organisasjonsnummer"], CFG)
    assert (split == again).all()
    shares = split.value_counts(normalize=True)
    assert abs(shares["train"] - 0.6) < 0.03 and abs(shares["valid"] - 0.2) < 0.03


def test_prepare_excludes_masks_and_imputes_masked_values() -> None:
    frame = synthetic_frame()
    prepared = prepare(frame, "retro", CFG)
    assert not any(c.startswith("masked_") for c in prepared.features)
    assert (
        "any_change_after_t" not in prepared.features
        and "organisasjonsnummer" not in prepared.features
    )
    assert "antall_ansatte" not in prepared.features
    masked = frame["masked_kapital"]
    fill = prepared.fill_values["kapital_belop"]
    assert np.allclose(prepared.frame.loc[masked, "kapital_belop"].astype(float), fill)
    assert str(prepared.frame["nace_section"].dtype) == "category"
    assert (
        feature_group("z_equity_ratio") == "accounts"
        and feature_group("z_board_size") == "peer"
        and feature_group("auditor_portfolio_size") == "network"
    )
    assert (
        feature_group("acc_sum_eiendeler") == "accounts" and feature_group("board_size") == "roles"
    )
    assert set(MASK_GOVERNS["masked_board"]) >= {"board_size", "has_chair"}


def test_metrics_helpers() -> None:
    y = np.array([0, 0, 1, 1, 0, 1, 0, 0])
    score = np.array([0.1, 0.2, 0.9, 0.8, 0.3, 0.7, 0.05, 0.4])
    precision, lift = precision_at_share(y, score, 0.25)
    assert precision == 1.0 and lift == pytest.approx(1.0 / (3 / 8))
    low, high = bootstrap_interval(y, score, lambda a, b: precision_at_share(a, b, 0.25)[0], 30)
    assert 0.0 <= low <= high <= 1.0
    table = calibration_table(y, score, 4)
    assert table["n"].sum() == 8 and list(table["bin"]) == [1, 2, 3, 4]
    assert top_overlap(score, score, 0.25) == 1.0
    assert stability({1: score, 2: score}, 0.25)["spearman_mean"] == pytest.approx(1.0)


def test_fairness_suppresses_small_groups() -> None:
    frame = synthetic_frame(400)
    y = frame["label_strict"].astype(int).to_numpy()
    score = -frame["equity_ratio"].to_numpy()
    table = fairness_table(frame, y, score, 0.05, min_group_size=20)
    small = table[table["suppressed"]]
    assert small["group_value"].isna().all() and small["n"].isna().all()
    big = table[~table["suppressed"]]
    assert (big["n"] >= 20).all() and set(big["group_type"]) >= {
        "fylke",
        "nace_section",
        "age_band",
    }
    per_group = fairness_table(frame, y, score, 0.05, 20, thresholds_per_group=True)
    rates = per_group[(~per_group["suppressed"]) & (per_group["group_type"] == "fylke")][
        "flag_rate"
    ]
    assert (rates.between(0.045, 0.10)).all()


def test_run_experiment_end_to_end() -> None:
    frame = synthetic_frame(3000)
    result = run_experiment(frame, "retro", CFG, ablations=("all", "no_accounts"))
    metrics = result.metrics
    assert set(metrics["model"]) >= {
        "rule",
        "isolation_forest",
        "mahalanobis",
        "hgb_calibrated",
        "agreement_hgb_vs_rule",
    }
    test_ap = metrics[
        (metrics["model"] == "hgb_calibrated")
        & (metrics["split"] == "test")
        & (metrics["metric"] == "average_precision")
        & (metrics["ablation"] == "all")
        & (metrics["seed"] == 1)
    ]
    base = metrics[
        (metrics["model"] == "hgb_calibrated")
        & (metrics["split"] == "test")
        & (metrics["metric"] == "base_rate")
        & (metrics["ablation"] == "all")
        & (metrics["seed"] == 1)
    ]
    assert float(test_ap["value"].iloc[0]) > 2 * float(base["value"].iloc[0])
    assert test_ap["ci_low"].notna().all() and float(test_ap["ci_low"].iloc[0]) <= float(
        test_ap["value"].iloc[0]
    )
    assert "no_accounts" in set(metrics["ablation"])
    assert len(result.scores) == len(frame) and {
        "rule",
        "isolation_forest",
        "mahalanobis",
        "hgb_calibrated",
    } <= set(result.scores.columns)
    assert result.calibration["n"].sum() == (result.scores["split"] == "test").sum()
    assert not result.fairness.empty and set(result.fairness["model"]) == {
        "hgb_calibrated",
        "isolation_forest",
    }
    assert "hgb" in set(result.explanations["model"]) and "mahalanobis" in set(
        result.explanations["model"]
    )
    assert result.params["positives"] > 0 and result.params["hgb_params"]["n_iter"] > 0
    probabilities = result.supervised.predict_proba(result.prepared.matrix().head(10))
    assert (
        probabilities.shape == (10,) and (0 <= probabilities).all() and (probabilities <= 1).all()
    )


def test_run_experiment_without_labels_gives_anomaly_scores_only() -> None:
    frame = synthetic_frame(800)
    frame["label_strict"] = False
    result = run_experiment(frame, "prospective", CFG, bootstrap=False)
    assert set(result.scores.columns) >= {"rule", "isolation_forest", "mahalanobis"}
    assert "hgb_calibrated" not in result.scores.columns
    assert (
        result.supervised is None
        and result.metrics.empty
        or "hgb_calibrated" not in set(result.metrics["model"])
    )


def test_log_to_mlflow_writes_run_and_model(tmp_path) -> None:
    mlflow = pytest.importorskip("mlflow")
    from foretaksrisiko.models.train import log_to_mlflow

    mlflow.set_tracking_uri(f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("test-foretaksrisiko")
    frame = synthetic_frame(1500)
    result = run_experiment(frame, "retro", CFG, ablations=("all",), bootstrap=False)
    run_id = log_to_mlflow(result, CFG, run_name="unit-test", tags={"design": "retro"})
    run = mlflow.get_run(run_id)
    assert run.data.params["design"] == "retro" and "hgb_learning_rate" in run.data.params
    assert any(k.startswith("hgb_calibrated__") for k in run.data.metrics)
    loaded = mlflow.pyfunc.load_model(f"runs:/{run_id}/hgb_calibrated")
    sample = result.prepared.matrix().head(5)
    predictions = loaded.predict(sample.astype({c: "str" for c in result.supervised.categorical}))
    assert len(predictions) == 5 and (0 <= predictions).all() and (predictions <= 1).all()
