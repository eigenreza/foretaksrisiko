"""The promotion rule: a challenger must meet pre-set thresholds on the frozen validation split.

The validation split is frozen by construction (companies are assigned by a salted hash of the
organisation number), so every candidate is judged on the same companies. The rule decides
eligibility only. Promotion is a separate, approved step, and rollback moves the champion alias
back to the previous version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from foretaksrisiko.config import PromotionConfig

VALID_PREFIX = "valid__hgb_calibrated__"
METRICS = (
    "average_precision",
    "precision_top_1pct",
    "brier",
    "expected_calibration_error",
    "positives",
)


def validation_metrics(run_metrics: dict) -> dict[str, float]:
    """Pick the validation-split metrics of the calibrated model out of an MLflow run."""
    return {
        name: float(run_metrics[VALID_PREFIX + name])
        for name in METRICS
        if VALID_PREFIX + name in run_metrics
    }


@dataclass
class PromotionDecision:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        verdict = "eligible" if self.eligible else "not eligible"
        return verdict if not self.reasons else f"{verdict}: " + "; ".join(self.reasons)


def promotion_check(
    candidate: dict[str, float], champion: dict[str, float] | None, cfg: PromotionConfig
) -> PromotionDecision:
    checks: list[dict] = []
    reasons: list[str] = []

    def check(name: str, value: float | None, threshold: float, at_least: bool) -> None:
        if value is None:
            passed = False
            reason = f"{name} missing from the candidate run"
        else:
            passed = value >= threshold if at_least else value <= threshold
            direction = "at least" if at_least else "at most"
            reason = f"{name} {value:.4f}, required {direction} {threshold:.4f}"
        checks.append({"check": name, "value": value, "threshold": threshold, "passed": passed})
        if not passed:
            reasons.append(reason)

    check("positives", candidate.get("positives"), cfg.min_positives_valid, True)
    check("average_precision", candidate.get("average_precision"), cfg.min_average_precision, True)
    check(
        "precision_top_1pct", candidate.get("precision_top_1pct"), cfg.min_precision_top_1pct, True
    )
    check("brier", candidate.get("brier"), cfg.max_brier, False)
    check(
        "expected_calibration_error",
        candidate.get("expected_calibration_error"),
        cfg.max_expected_calibration_error,
        False,
    )
    if cfg.require_not_worse_than_champion and champion and "average_precision" in champion:
        floor = champion["average_precision"] * (1.0 - cfg.relative_tolerance)
        value = candidate.get("average_precision")
        passed = value is not None and value >= floor
        checks.append(
            {
                "check": "not_worse_than_champion",
                "value": value,
                "threshold": floor,
                "passed": passed,
            }
        )
        if not passed:
            shown = "missing" if value is None else f"{value:.4f}"
            reasons.append(f"average_precision {shown} is below the champion floor {floor:.4f}")
    return PromotionDecision(eligible=not reasons, reasons=reasons, checks=checks)
