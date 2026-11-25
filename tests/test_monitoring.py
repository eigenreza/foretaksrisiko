"""Drift metrics, alert records, retraining rules and the promotion rule, on synthetic frames."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import fake_orgnr
from foretaksrisiko.config import MonitoringConfig, PromotionConfig
from foretaksrisiko.monitoring.alerts import (
    AlertBreach,
    alert_frame,
    alerts_from_drift,
    raise_on_alerts,
    retraining_decision,
)
from foretaksrisiko.monitoring.drift import (
    categorical_psi,
    drift_table,
    flag_threshold,
    monitored_columns,
    numeric_psi,
    score_drift,
)
from foretaksrisiko.registry.promotion import promotion_check, validation_metrics

CFG = MonitoringConfig(min_rows=100)


def frame(n: int, shift: float = 0.0, seed: int = 0, missing: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    equity = rng.normal(0.3 + shift, 0.3, n)
    if missing:
        equity[rng.random(n) < missing] = np.nan
    return pd.DataFrame(
        {
            "design": "prospective",
            "reference_snapshot_id": 1,
            "reference_date": "x",
            "organisasjonsnummer": [fake_orgnr(500_000 + i) for i in range(n)],
            "peer_group": "all:1",
            "equity_ratio": equity,
            "age_years": rng.gamma(2.0, 4.0, n),
            "nace_section": rng.choice(list("FGJ"), n, p=[0.5, 0.3, 0.2]),
            "has_ceo": rng.random(n) < 0.7,
            "masked_kapital": False,
            "any_change_after_t": False,
            "label_strict": False,
        }
    )


def test_numeric_psi_is_zero_for_identical_and_grows_with_shift() -> None:
    a = np.random.default_rng(1).normal(size=5000)
    assert numeric_psi(a, a, 10) == pytest.approx(0.0, abs=1e-9)
    assert numeric_psi(a, a + 1.0, 10) > 0.25
    assert numeric_psi(np.array([np.nan]), a, 10) is None
    assert numeric_psi(np.ones(50), np.ones(50) * 2, 10) == pytest.approx(0.0)


def test_numeric_psi_with_smoothed_edges_ignores_a_block_that_barely_moves() -> None:
    # Many rows share one value that sits exactly on a bin edge, as with a feature that is the
    # same for every client of one large auditor. The value changes by one.
    rng = np.random.default_rng(3)
    spread = rng.uniform(0.0, 1000.0, 9000)
    reference = np.concatenate([spread, np.full(1500, 800.0)])
    current = np.concatenate([spread, np.full(1500, 799.0)])
    assert numeric_psi(reference, current, 10) > 0.25
    assert numeric_psi(reference, current, 10, smoothing=0.02) < 0.01

    # A real shift is measured almost the same with and without smoothing.
    a = rng.normal(size=20_000)
    plain = numeric_psi(a, a + 0.5, 10)
    assert plain > 0.2
    assert numeric_psi(a, a + 0.5, 10, smoothing=0.02) == pytest.approx(plain, rel=0.05)

    # The drift table uses the smoothing from the configuration.
    frames = [pd.DataFrame({"portfolio": values}) for values in (reference, current)]
    table = drift_table(frames[0], frames[1], CFG)
    psi = table[(table["feature"] == "portfolio") & (table["metric"] == "psi")].iloc[0]
    assert psi["severity"] == "ok" and psi["value"] < 0.01
    hard = drift_table(frames[0], frames[1], CFG.model_copy(update={"psi_edge_smoothing": 0.0}))
    assert hard[hard["metric"] == "psi"].iloc[0]["severity"] == "alert"


def test_categorical_psi_and_largest_share_change() -> None:
    ref = pd.Series(["F"] * 50 + ["G"] * 30 + ["J"] * 20)
    cur = pd.Series(["F"] * 20 + ["G"] * 30 + ["J"] * 50)
    psi, delta, level = categorical_psi(ref, cur)
    assert psi > 0.25 and delta == pytest.approx(0.3) and level in {"F", "J"}
    same, zero, _ = categorical_psi(ref, ref)
    assert same == pytest.approx(0.0) and zero == 0.0


def test_monitored_columns_skip_identifiers_masks_and_labels() -> None:
    numeric, categorical = monitored_columns(frame(10))
    assert numeric == ["equity_ratio", "age_years"]
    assert categorical == ["nace_section", "has_ceo"]


def test_drift_table_flags_shift_and_missingness() -> None:
    reference = frame(4000)
    current = frame(4000, shift=0.6, seed=1, missing=0.2)
    current["nace_section"] = np.where(current["nace_section"] == "F", "J", current["nace_section"])
    table = drift_table(reference, current, CFG)
    by = table.set_index(["feature", "metric"])
    assert by.loc[("equity_ratio", "psi"), "severity"] == "alert"
    assert by.loc[("equity_ratio", "missing_rate"), "severity"] == "alert"
    assert by.loc[("age_years", "psi"), "severity"] == "ok"
    assert by.loc[("nace_section", "max_share_delta"), "severity"] == "alert"
    assert by.loc[("nace_section", "max_share_delta"), "level"] in {"F", "J"}
    assert (table["rows_reference"] == 4000).all()
    small = drift_table(frame(20), frame(20, shift=5.0), CFG)
    assert small["value"].isna().all() and (small["severity"] == "ok").all()


def test_score_drift_against_reference_flag_threshold() -> None:
    rng = np.random.default_rng(2)
    reference = rng.beta(1, 50, 5000)
    threshold = flag_threshold(reference, 0.05)
    assert (reference > threshold).mean() == pytest.approx(0.05, abs=0.002)
    stable = score_drift(reference, rng.beta(1, 50, 5000), CFG).set_index("metric")
    assert stable.loc["psi", "severity"] == "ok" and stable.loc["flag_share", "severity"] == "ok"
    inflated = score_drift(reference, rng.beta(1, 20, 5000), CFG).set_index("metric")
    assert inflated.loc["flag_share", "severity"] == "alert"
    assert (
        inflated.loc["flag_share", "current_value"]
        > 2 * inflated.loc["flag_share", "reference_value"]
    )
    assert {"mean_score", "p50", "p90", "p99"} <= set(inflated.index)


def test_alerts_and_retraining_rules() -> None:
    table = drift_table(frame(4000), frame(4000, shift=0.6, seed=1, missing=0.2), CFG)
    alerts = alerts_from_drift(table)
    assert alerts and all(a.severity in {"warn", "alert"} for a in alerts)
    assert all(a.alert_type.startswith("data_drift:") for a in alerts)
    no_retrain = retraining_decision(table, CFG, champion_age_snapshots=3, new_positives=10)
    assert not no_retrain.recommended
    r1 = retraining_decision(table, MonitoringConfig(retrain_min_alert_features=1), None, None)
    assert r1.recommended and r1.reasons[0].startswith("R1")
    r34 = retraining_decision(pd.DataFrame(), CFG, champion_age_snapshots=30, new_positives=250)
    assert [r[:2] for r in r34.reasons] == ["R3", "R4"]
    recorded = alert_frame(alerts, r34)
    assert recorded.iloc[-1]["alert_type"] == "retraining_recommended"
    assert recorded.iloc[-1]["severity"] == "warn"
    with pytest.raises(AlertBreach, match="alert-level records"):
        raise_on_alerts(recorded, 2, "default")
    raise_on_alerts(recorded[recorded["severity"] == "warn"], 2, "default")
    raise_on_alerts(alert_frame([]), 2, "default")


def test_scenarios_override_thresholds() -> None:
    cfg = MonitoringConfig(scenarios={"simulated_breach": {"psi_alert": 0.001, "min_rows": 1}})
    assert cfg.with_scenario("default") is cfg and cfg.with_scenario(None) is cfg
    tight = cfg.with_scenario("simulated_breach")
    assert tight.psi_alert == 0.001 and tight.min_rows == 1 and tight.psi_warn == cfg.psi_warn
    with pytest.raises(KeyError):
        cfg.with_scenario("unknown")


def test_promotion_rule() -> None:
    cfg = PromotionConfig()
    good = {
        "average_precision": 0.30,
        "precision_top_1pct": 0.20,
        "brier": 0.004,
        "expected_calibration_error": 0.002,
        "positives": 60,
    }
    assert promotion_check(good, None, cfg).eligible
    assert promotion_check(good, {"average_precision": 0.31}, cfg).eligible
    worse = promotion_check(good, {"average_precision": 0.40}, cfg)
    assert not worse.eligible and "champion floor" in worse.reasons[0]
    weak = promotion_check({**good, "average_precision": 0.05, "positives": 10}, None, cfg)
    assert len(weak.reasons) == 2 and not weak.eligible
    missing = promotion_check({k: v for k, v in good.items() if k != "brier"}, None, cfg)
    assert "brier missing" in missing.summary()
    metrics = validation_metrics(
        {"valid__hgb_calibrated__average_precision": 0.2, "hgb_calibrated__average_precision": 0.3}
    )
    assert metrics == {"average_precision": 0.2}
