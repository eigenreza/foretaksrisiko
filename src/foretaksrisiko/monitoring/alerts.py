"""Alert records from drift tables, and the retraining trigger rules.

Retraining is recommended, never started automatically, when any rule fires:

* R1 data drift: at least ``retrain_min_alert_features`` features at alert-level PSI.
* R2 prediction drift: score PSI or flagged share at alert level.
* R3 outcomes matured: at least ``retrain_min_new_positives`` fully observed positives in
  snapshots after the champion's training snapshot.
* R4 age: the champion is at least ``retrain_max_champion_age_snapshots`` snapshots old.

Retraining produces a challenger; a champion only changes through an approved promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from foretaksrisiko.config import MonitoringConfig

ALERT_COLUMNS = ["alert_type", "feature", "value", "threshold", "severity", "message"]


class AlertBreach(Exception):
    """Raised by the alert stage when alert-level records exist for a snapshot."""


@dataclass(frozen=True)
class Alert:
    alert_type: str
    feature: str | None
    value: float | None
    threshold: float | None
    severity: str
    message: str


@dataclass(frozen=True)
class RetrainingDecision:
    recommended: bool
    reasons: list[str]


def alerts_from_drift(drift: pd.DataFrame) -> list[Alert]:
    """One alert per warn-level or alert-level drift row."""
    alerts: list[Alert] = []
    if drift.empty:
        return alerts
    for _, row in drift[drift["severity"].isin(["warn", "alert"])].iterrows():
        kind = "prediction_drift" if row["kind"] == "prediction" else "data_drift"
        threshold = row["alert_threshold"] if row["severity"] == "alert" else row["warn_threshold"]
        level = f" (level {row['level']})" if isinstance(row.get("level"), str) else ""
        alerts.append(
            Alert(
                alert_type=f"{kind}:{row['metric']}",
                feature=str(row["feature"]),
                value=float(row["value"]),
                threshold=float(threshold),
                severity=str(row["severity"]),
                message=(
                    f"{row['metric']} for {row['feature']}{level} is {row['value']:.4f}, "
                    f"{row['severity']} threshold {threshold:.4f}"
                ),
            )
        )
    return alerts


def retraining_decision(
    drift: pd.DataFrame,
    cfg: MonitoringConfig,
    champion_age_snapshots: int | None,
    new_positives: int | None,
) -> RetrainingDecision:
    reasons: list[str] = []
    if not drift.empty:
        data_alerts = drift[
            (drift["metric"] == "psi")
            & (drift["kind"] != "prediction")
            & (drift["severity"] == "alert")
        ]
        n_features = int(data_alerts["feature"].nunique())
        if n_features >= cfg.retrain_min_alert_features:
            reasons.append(
                f"R1 data drift: {n_features} features at alert-level PSI "
                f"(rule {cfg.retrain_min_alert_features})"
            )
        prediction = drift[(drift["kind"] == "prediction") & (drift["severity"] == "alert")]
        if not prediction.empty:
            metrics = ", ".join(sorted(prediction["metric"].unique()))
            reasons.append(f"R2 prediction drift at alert level: {metrics}")
    if new_positives is not None and new_positives >= cfg.retrain_min_new_positives:
        reasons.append(
            f"R3 outcomes matured: {new_positives} new fully observed positives "
            f"(rule {cfg.retrain_min_new_positives})"
        )
    if (
        champion_age_snapshots is not None
        and champion_age_snapshots >= cfg.retrain_max_champion_age_snapshots
    ):
        reasons.append(
            f"R4 champion age: {champion_age_snapshots} snapshots "
            f"(rule {cfg.retrain_max_champion_age_snapshots})"
        )
    return RetrainingDecision(recommended=bool(reasons), reasons=reasons)


def alert_frame(alerts: list[Alert], decision: RetrainingDecision | None = None) -> pd.DataFrame:
    rows = [asdict(a) for a in alerts]
    if decision is not None and decision.recommended:
        rows.append(
            asdict(
                Alert(
                    alert_type="retraining_recommended",
                    feature=None,
                    value=None,
                    threshold=None,
                    severity="warn",
                    message="; ".join(decision.reasons),
                )
            )
        )
    return pd.DataFrame(rows, columns=ALERT_COLUMNS)


def raise_on_alerts(alerts: pd.DataFrame, snapshot_id: int, scenario: str) -> None:
    """Fail loudly when alert-level records exist; the job email follows from the failure."""
    if alerts.empty:
        return
    breached = alerts[alerts["severity"] == "alert"]
    if breached.empty:
        return
    shown = breached["message"].head(20).tolist()
    lines = "".join(f"\n- {m}" for m in shown)
    more = "" if len(breached) <= 20 else f"\n- and {len(breached) - 20} more"
    raise AlertBreach(
        f"snapshot {snapshot_id}, scenario {scenario}: "
        f"{len(breached)} alert-level records{lines}{more}"
    )
