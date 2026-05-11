"""Registry operations on MLflow: register, challenger, evaluate, promote, rollback.

Works against the Unity Catalog registry on Databricks (three-level model names) and against a
plain MLflow registry locally and in tests. Every operation appends a ``RegistryEvent`` that the
lakehouse glue writes to ``monitoring.registry_events``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from foretaksrisiko.config import RegistryConfig
from foretaksrisiko.registry.promotion import (
    PromotionDecision,
    promotion_check,
    validation_metrics,
)

log = logging.getLogger(__name__)

PREVIOUS_CHAMPION_TAG = "previous_champion_version"
EVENT_COLUMNS = [
    "event_time",
    "event",
    "model_name",
    "version",
    "from_version",
    "to_version",
    "decision",
    "approved",
    "actor",
    "details",
]


@dataclass(frozen=True)
class RegistryEvent:
    event_time: str
    event: str
    model_name: str
    version: str | None
    from_version: str | None
    to_version: str | None
    decision: str | None
    approved: bool
    actor: str | None
    details: str | None


class Registry:
    def __init__(self, model_name: str, cfg: RegistryConfig, actor: str | None = None) -> None:
        from mlflow import MlflowClient

        self.model_name = model_name
        self.cfg = cfg
        self.actor = actor
        self.client = MlflowClient()
        self.events: list[RegistryEvent] = []

    # -- helpers -----------------------------------------------------------------------------

    def _record(
        self,
        event: str,
        version: str | None = None,
        from_version: str | None = None,
        to_version: str | None = None,
        decision: str | None = None,
        approved: bool = False,
        details: dict | list | str | None = None,
    ) -> RegistryEvent:
        record = RegistryEvent(
            event_time=datetime.now(UTC).isoformat(timespec="seconds"),
            event=event,
            model_name=self.model_name,
            version=None if version is None else str(version),
            from_version=None if from_version is None else str(from_version),
            to_version=None if to_version is None else str(to_version),
            decision=decision,
            approved=approved,
            actor=self.actor,
            details=details if isinstance(details, str) or details is None else json.dumps(details),
        )
        self.events.append(record)
        log.info("registry %s: %s", event, {k: v for k, v in asdict(record).items() if v})
        return record

    def version_by_alias(self, alias: str):
        from mlflow.exceptions import MlflowException

        try:
            return self.client.get_model_version_by_alias(self.model_name, alias)
        except MlflowException:
            return None

    def metrics_for_version(self, version: str) -> dict[str, float]:
        model_version = self.client.get_model_version(self.model_name, str(version))
        return validation_metrics(self.client.get_run(model_version.run_id).data.metrics)

    # -- operations --------------------------------------------------------------------------

    def register(self, run_id: str, tags: dict[str, str] | None = None) -> str:
        """Create a model version from a run and tag it with its validation metrics."""
        import mlflow

        version = mlflow.register_model(
            f"runs:/{run_id}/{self.cfg.artifact_path}", self.model_name
        ).version
        metrics = validation_metrics(self.client.get_run(run_id).data.metrics)
        for key, value in {
            **(tags or {}),
            **{f"valid_{k}": f"{v:.6f}" for k, v in metrics.items()},
        }.items():
            self.client.set_model_version_tag(self.model_name, version, key, str(value))
        self._record("registered", version=version, details=metrics)
        return str(version)

    def set_challenger(self, version: str) -> None:
        self.client.set_registered_model_alias(self.model_name, self.cfg.challenger_alias, version)
        self._record("challenger_set", version=version, to_version=version)

    def evaluate(self, version: str) -> PromotionDecision:
        """Apply the promotion rule to a version, against the current champion if there is one."""
        champion = self.version_by_alias(self.cfg.champion_alias)
        champion_metrics = self.metrics_for_version(champion.version) if champion else None
        decision = promotion_check(
            self.metrics_for_version(version), champion_metrics, self.cfg.promotion
        )
        self._record(
            "evaluated", version=version, decision=decision.summary(), details=decision.checks
        )
        return decision

    def promote(self, version: str, approved: bool) -> PromotionDecision:
        """Move the champion alias to ``version`` when the rule passes and approval is given."""
        decision = self.evaluate(version)
        if not approved:
            self._record(
                "promotion_refused",
                version=version,
                decision=decision.summary(),
                details="manual approval missing",
            )
            return decision
        if not decision.eligible:
            self._record(
                "promotion_refused",
                version=version,
                decision=decision.summary(),
                approved=True,
                details="promotion rule not met",
            )
            return decision
        champion = self.version_by_alias(self.cfg.champion_alias)
        if champion is not None:
            self.client.set_registered_model_tag(
                self.model_name, PREVIOUS_CHAMPION_TAG, str(champion.version)
            )
        self.client.set_registered_model_alias(self.model_name, self.cfg.champion_alias, version)
        challenger = self.version_by_alias(self.cfg.challenger_alias)
        if challenger is not None and str(challenger.version) == str(version):
            self.client.delete_registered_model_alias(self.model_name, self.cfg.challenger_alias)
        self._record(
            "promoted",
            version=version,
            from_version=None if champion is None else champion.version,
            to_version=version,
            decision=decision.summary(),
            approved=True,
        )
        return decision

    def rollback(self, approved: bool) -> str | None:
        """Move the champion alias back to the previous champion; returns the restored version."""
        model = self.client.get_registered_model(self.model_name)
        previous = (model.tags or {}).get(PREVIOUS_CHAMPION_TAG)
        champion = self.version_by_alias(self.cfg.champion_alias)
        if not approved or previous is None or champion is None:
            reason = (
                "manual approval missing"
                if not approved
                else "no previous champion recorded"
                if previous is None
                else "no champion to roll back"
            )
            self._record("rollback_refused", details=reason, approved=approved)
            return None
        self.client.set_registered_model_alias(self.model_name, self.cfg.champion_alias, previous)
        self.client.set_registered_model_tag(
            self.model_name, PREVIOUS_CHAMPION_TAG, str(champion.version)
        )
        self._record(
            "rollback",
            version=previous,
            from_version=champion.version,
            to_version=previous,
            approved=True,
        )
        return str(previous)

    def status(self) -> dict:
        from mlflow.exceptions import MlflowException

        try:
            model = self.client.get_registered_model(self.model_name)
        except MlflowException:
            return {"model_name": self.model_name, "registered": False}
        out: dict = {
            "model_name": self.model_name,
            "registered": True,
            "previous_champion": (model.tags or {}).get(PREVIOUS_CHAMPION_TAG),
            "aliases": {},
        }
        for alias in (self.cfg.champion_alias, self.cfg.challenger_alias):
            mv = self.version_by_alias(alias)
            if mv is not None:
                out["aliases"][alias] = {
                    "version": str(mv.version),
                    "run_id": mv.run_id,
                    "tags": dict(mv.tags or {}),
                }
        return out


def registry_model_name(cfg: RegistryConfig, names, local: bool) -> str:
    """Three-level Unity Catalog name on Databricks, the bare name locally."""
    return cfg.model_name if local else names.table(cfg.layer, cfg.model_name)


def make_registry(cfg: RegistryConfig, names, local: bool, actor: str | None = None) -> Registry:
    import mlflow

    if not local:
        mlflow.set_registry_uri("databricks-uc")
    return Registry(registry_model_name(cfg, names, local), cfg, actor)


def write_events(spark, names, events: list[RegistryEvent]) -> int:
    """Append registry events to monitoring.registry_events."""
    if not events:
        return 0
    from pyspark.sql import functions as F

    from foretaksrisiko.lakehouse.session import ensure_schemas

    ensure_schemas(spark, names, ("monitoring",))
    rows = [asdict(e) for e in events]
    schema = (
        "event_time STRING, event STRING, model_name STRING, version STRING, from_version STRING, "
        "to_version STRING, decision STRING, approved BOOLEAN, actor STRING, details STRING"
    )
    frame = spark.createDataFrame(
        [tuple(r[c] for c in EVENT_COLUMNS) for r in rows], schema
    ).withColumn("logged_at", F.current_timestamp())
    frame.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(
        names.table("monitoring", "registry_events")
    )
    return len(rows)
