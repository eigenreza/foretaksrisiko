"""Registry operations against a local MLflow registry: aliases, promotion, rollback, events."""

from __future__ import annotations

import pytest

mlflow = pytest.importorskip("mlflow")
pytest.importorskip("sklearn")

from foretaksrisiko.config import PromotionConfig, RegistryConfig  # noqa: E402
from foretaksrisiko.models.train import log_to_mlflow, run_experiment  # noqa: E402
from foretaksrisiko.registry.client import PREVIOUS_CHAMPION_TAG, Registry  # noqa: E402
from test_models import CFG, synthetic_frame  # noqa: E402

LENIENT = PromotionConfig(
    min_average_precision=0.01,
    min_precision_top_1pct=0.0,
    max_brier=1.0,
    max_expected_calibration_error=1.0,
    min_positives_valid=1,
)


@pytest.fixture(scope="module")
def run_ids(tmp_path_factory) -> tuple[str, str]:
    uri = f"sqlite:///{(tmp_path_factory.mktemp('mlflow') / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    mlflow.set_experiment("test-registry")
    result = run_experiment(
        synthetic_frame(1500), "retro", CFG, ablations=("all",), bootstrap=False
    )
    tags = {"design": "retro", "scope": "sample"}
    first = log_to_mlflow(result, CFG, run_name="candidate-1", tags={**tags, "snapshot_id": "1"})
    second = log_to_mlflow(result, CFG, run_name="candidate-2", tags={**tags, "snapshot_id": "2"})
    return first, second


def test_validation_metrics_are_logged(run_ids) -> None:
    metrics = mlflow.get_run(run_ids[0]).data.metrics
    assert "valid__hgb_calibrated__average_precision" in metrics
    assert "valid__hgb_calibrated__positives" in metrics
    assert "hgb_calibrated__average_precision" in metrics
    assert not any(k.startswith("test__") for k in metrics)


def test_register_challenge_promote_and_roll_back(run_ids) -> None:
    registry = Registry("test_proxy_outcome", RegistryConfig(promotion=LENIENT), actor="tests")
    assert registry.status() == {"model_name": "test_proxy_outcome", "registered": False}

    v1 = registry.register(run_ids[0], tags={"snapshot_id": "1"})
    assert v1 == "1"
    registry.set_challenger(v1)
    status = registry.status()
    assert status["aliases"]["challenger"]["version"] == "1" and "champion" not in status["aliases"]
    assert status["aliases"]["challenger"]["tags"]["snapshot_id"] == "1"
    assert "valid_average_precision" in status["aliases"]["challenger"]["tags"]

    refused = registry.promote(v1, approved=False)
    assert refused.eligible and "champion" not in registry.status()["aliases"]
    assert registry.events[-1].event == "promotion_refused"

    decision = registry.promote(v1, approved=True)
    assert decision.eligible
    status = registry.status()
    assert status["aliases"]["champion"]["version"] == "1" and "challenger" not in status["aliases"]
    assert status["previous_champion"] is None

    v2 = registry.register(run_ids[1], tags={"snapshot_id": "2"})
    registry.set_challenger(v2)
    registry.promote(v2, approved=True)
    status = registry.status()
    assert status["aliases"]["champion"]["version"] == "2"
    assert status["previous_champion"] == "1"
    assert (
        registry.client.get_registered_model("test_proxy_outcome").tags[PREVIOUS_CHAMPION_TAG]
        == "1"
    )

    assert registry.rollback(approved=False) is None
    assert registry.rollback(approved=True) == "1"
    status = registry.status()
    assert status["aliases"]["champion"]["version"] == "1" and status["previous_champion"] == "2"

    events = [e.event for e in registry.events]
    assert events == [
        "registered",
        "challenger_set",
        "evaluated",
        "promotion_refused",
        "evaluated",
        "promoted",
        "registered",
        "challenger_set",
        "evaluated",
        "promoted",
        "rollback_refused",
        "rollback",
    ]
    assert all(e.model_name == "test_proxy_outcome" and e.actor == "tests" for e in registry.events)
    promoted = [e for e in registry.events if e.event == "promoted"]
    assert (
        promoted[1].from_version == "1" and promoted[1].to_version == "2" and promoted[1].approved
    )


def test_strict_rule_blocks_promotion_even_when_approved(run_ids) -> None:
    strict = RegistryConfig(promotion=PromotionConfig(min_average_precision=0.999))
    registry = Registry("test_strict_model", strict)
    version = registry.register(run_ids[0])
    decision = registry.promote(version, approved=True)
    assert not decision.eligible and any("average_precision" in r for r in decision.reasons)
    assert "champion" not in registry.status()["aliases"]
    assert registry.events[-1].event == "promotion_refused" and registry.events[-1].approved
