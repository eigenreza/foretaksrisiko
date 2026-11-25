"""Training and evaluation against the pre-registered plan, on pandas, with optional MLflow logging."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from foretaksrisiko.config import ModelConfig
from foretaksrisiko.evaluation.fairness import fairness_table
from foretaksrisiko.evaluation.metrics import (
    agreement,
    average_precision,
    bootstrap_interval,
    brier,
    calibration_table,
    precision_at_share,
    stability,
    summarize,
)
from foretaksrisiko.models.anomaly import (
    RobustMahalanobis,
    fit_isolation_forest,
    isolation_scores,
    robust_contributions,
    rule_score,
)
from foretaksrisiko.models.data import Prepared, numeric_matrix, prepare
from foretaksrisiko.models.supervised import FittedSupervised, fit_supervised

log = logging.getLogger(__name__)

ABLATIONS: dict[str, tuple[str, ...]] = {
    "all": (),
    "no_network": ("network",),
    "no_accounts": ("accounts",),
    "no_text": ("text",),
    "register_roles_only": ("network", "accounts", "text", "peer"),
}
ANOMALY_MODELS = ("rule", "isolation_forest", "mahalanobis")


@dataclass
class ExperimentResult:
    metrics: pd.DataFrame
    scores: pd.DataFrame
    fairness: pd.DataFrame
    explanations: pd.DataFrame
    calibration: pd.DataFrame
    params: dict = field(default_factory=dict)
    supervised: FittedSupervised | None = None
    prepared: Prepared | None = None


def _metric_rows(
    model: str,
    ablation: str,
    split: str,
    seed: int | None,
    values: dict[str, float],
    intervals: dict | None = None,
) -> list[dict]:
    rows = []
    for name, value in values.items():
        low, high = (intervals or {}).get(name, (None, None))
        rows.append(
            {
                "model": model,
                "ablation": ablation,
                "split": split,
                "seed": seed,
                "metric": name,
                "value": None
                if value is None or (isinstance(value, float) and np.isnan(value))
                else float(value),
                "ci_low": low,
                "ci_high": high,
            }
        )
    return rows


def run_experiment(
    frame: pd.DataFrame,
    design: str,
    cfg: ModelConfig,
    label: str = "label_strict",
    ablations: tuple[str, ...] = tuple(ABLATIONS),
    bootstrap: bool = True,
) -> ExperimentResult:
    """Fit every model family on the training split and evaluate on validation and test."""
    prepared = prepare(frame, design, cfg)
    data = prepared.frame
    y = data[label].fillna(False).astype(int).to_numpy()
    split = data["split"]
    masks = {name: (split == name).to_numpy() for name in ("train", "valid", "test")}
    has_labels = y[masks["train"]].sum() >= 10 and y[masks["valid"]].sum() >= 5
    metric_rows: list[dict] = []
    score_columns: dict[str, np.ndarray] = {}
    fairness_frames: list[pd.DataFrame] = []
    explanations: list[pd.DataFrame] = []
    calibration = pd.DataFrame()
    params: dict = {
        "design": design,
        "label": label,
        "rows": int(len(data)),
        "positives": int(y.sum()),
        "has_labels": bool(has_labels),
    }
    params.update({f"n_{k}": int(v.sum()) for k, v in masks.items()})

    def evaluate(
        model: str, ablation: str, score: np.ndarray, probability: bool, seed: int | None
    ) -> None:
        for split_name in ("valid", "test"):
            mask = masks[split_name]
            if y[mask].sum() == 0:
                continue
            values = summarize(
                y[mask], score[mask], cfg.top_shares, probability, cfg.calibration_bins
            )
            intervals = None
            if bootstrap and split_name == "test" and seed in (None, cfg.seeds[0]):
                intervals = {
                    "average_precision": bootstrap_interval(
                        y[mask], score[mask], average_precision, cfg.bootstrap_samples
                    ),
                    f"precision_top_{int(round(cfg.top_shares[0] * 100))}pct": bootstrap_interval(
                        y[mask],
                        score[mask],
                        lambda a, b: precision_at_share(a, b, cfg.top_shares[0])[0],
                        cfg.bootstrap_samples,
                    ),
                }
                if probability:
                    intervals["brier"] = bootstrap_interval(
                        y[mask], score[mask], brier, cfg.bootstrap_samples
                    )
            metric_rows.extend(_metric_rows(model, ablation, split_name, seed, values, intervals))

    # Anomaly scores, main ablation only, stability across seeds for the forest.
    numeric_all = numeric_matrix(prepared)
    numeric_train = numeric_all[masks["train"]]
    rule = rule_score(data)
    score_columns["rule"] = rule
    evaluate("rule", "all", rule, False, None)
    forest_by_seed: dict[int, np.ndarray] = {}
    for seed in cfg.seeds:
        forest = fit_isolation_forest(numeric_train, cfg, seed)
        forest_by_seed[seed] = isolation_scores(forest, numeric_all)
        evaluate("isolation_forest", "all", forest_by_seed[seed], False, seed)
    score_columns["isolation_forest"] = forest_by_seed[cfg.seeds[0]]
    metric_rows.extend(
        _metric_rows(
            "isolation_forest",
            "all",
            "test",
            None,
            stability({s: v[masks["test"]] for s, v in forest_by_seed.items()}, cfg.top_shares[0]),
        )
    )
    mahalanobis = RobustMahalanobis.fit(numeric_train, cfg, cfg.seeds[0])
    score_columns["mahalanobis"] = mahalanobis.score(numeric_all)
    evaluate("mahalanobis", "all", score_columns["mahalanobis"], False, None)
    explanations.append(
        robust_contributions(data, score_columns["mahalanobis"], cfg.top_shares[0]).assign(
            model="mahalanobis"
        )
    )
    explanations.append(robust_contributions(data, rule, cfg.top_shares[0]).assign(model="rule"))

    supervised_main: FittedSupervised | None = None
    if has_labels:
        for ablation in ablations:
            drop = ABLATIONS[ablation]
            x_all = prepared.matrix(drop_groups=drop)
            seeds = cfg.seeds if ablation == "all" else cfg.seeds[:1]
            by_seed: dict[int, np.ndarray] = {}
            for seed in seeds:
                fitted = fit_supervised(
                    x_all[masks["train"]],
                    y[masks["train"]],
                    x_all[masks["valid"]],
                    y[masks["valid"]],
                    prepared.categorical,
                    cfg,
                    seed,
                    prepared.fill_values,
                )
                probability = fitted.predict_proba(x_all)
                by_seed[seed] = probability
                evaluate("hgb_calibrated", ablation, probability, True, seed)
                if ablation == "all" and seed == cfg.seeds[0]:
                    supervised_main = fitted
                    score_columns["hgb_calibrated"] = probability
                    calibration = calibration_table(
                        y[masks["test"]], probability[masks["test"]], cfg.calibration_bins
                    )
                    params["hgb_params"] = fitted.params
                    params["hgb_grid"] = fitted.grid
            if ablation == "all" and len(seeds) > 1:
                metric_rows.extend(
                    _metric_rows(
                        "hgb_calibrated",
                        "all",
                        "test",
                        None,
                        stability(
                            {s: v[masks["test"]] for s, v in by_seed.items()}, cfg.top_shares[0]
                        ),
                    )
                )
        if supervised_main is not None:
            from foretaksrisiko.evaluation.explain import shap_summary

            try:
                explanations.append(
                    shap_summary(
                        supervised_main.predict_raw,
                        prepared.matrix()[masks["train"]],
                        supervised_main.categorical,
                        supervised_main.categories,
                        cfg.shap_rows,
                    ).assign(model="hgb")
                )
            except Exception as exc:  # noqa: BLE001 - explanations must never fail the run
                log.warning("shap summary skipped: %s", type(exc).__name__)
        for model in ("hgb_calibrated", "isolation_forest"):
            if model in score_columns:
                test = masks["test"]
                for per_group in (False, True):
                    table = fairness_table(
                        data[test],
                        y[test],
                        score_columns[model][test],
                        cfg.top_shares[-1],
                        cfg.min_group_size,
                        per_group,
                    )
                    fairness_frames.append(table.assign(model=model))
        if "hgb_calibrated" in score_columns:
            for other in ANOMALY_MODELS:
                values = agreement(
                    score_columns["hgb_calibrated"][masks["test"]],
                    score_columns[other][masks["test"]],
                    cfg.top_shares,
                )
                metric_rows.extend(
                    _metric_rows(f"agreement_hgb_vs_{other}", "all", "test", None, values)
                )

    scores = pd.DataFrame(
        {
            "organisasjonsnummer": data["organisasjonsnummer"].to_numpy(),
            "split": split.to_numpy(),
            "label": y,
        }
    )
    for name, values in score_columns.items():
        scores[name] = values
    result = ExperimentResult(
        metrics=pd.DataFrame(metric_rows),
        scores=scores,
        fairness=pd.concat(fairness_frames, ignore_index=True)
        if fairness_frames
        else pd.DataFrame(),
        explanations=pd.concat(explanations, ignore_index=True) if explanations else pd.DataFrame(),
        calibration=calibration,
        params=params,
        supervised=supervised_main,
        prepared=prepared,
    )
    return result


def log_to_mlflow(
    result: ExperimentResult, cfg: ModelConfig, run_name: str, tags: dict | None = None
) -> str:
    """One MLflow run with parameters, headline metrics, tables as artifacts and the model."""
    import mlflow
    from mlflow.models import infer_signature

    with mlflow.start_run(run_name=run_name, tags=tags or {}) as run:
        mlflow.log_params(
            {k: v for k, v in result.params.items() if not isinstance(v, (dict, list))}
        )
        if "hgb_params" in result.params:
            mlflow.log_params({f"hgb_{k}": v for k, v in result.params["hgb_params"].items()})
        # Test metrics keep their plain names; validation metrics carry a prefix and are what the
        # promotion rule reads (the validation split is frozen by the hash assignment).
        headline = result.metrics[
            (result.metrics["ablation"] == "all")
            & (result.metrics["seed"].isin([cfg.seeds[0]]) | result.metrics["seed"].isna())
        ]
        for _, row in headline.iterrows():
            if row["value"] is None or pd.isna(row["value"]):
                continue
            prefix = "" if row["split"] == "test" else f"{row['split']}__"
            mlflow.log_metric(f"{prefix}{row['model']}__{row['metric']}", float(row["value"]))
        with tempfile.TemporaryDirectory() as tmp:
            for name, table in (
                ("metrics", result.metrics),
                ("fairness", result.fairness),
                ("explanations", result.explanations),
                ("calibration", result.calibration),
            ):
                path = Path(tmp) / f"{name}.csv"
                table.to_csv(path, index=False)
                mlflow.log_artifact(str(path))
            (Path(tmp) / "params.json").write_text(
                json.dumps(result.params, default=str, indent=1), encoding="utf-8"
            )
            mlflow.log_artifact(str(Path(tmp) / "params.json"))
        if result.supervised is not None and result.prepared is not None:
            from foretaksrisiko.models.serving import SupervisedPyfunc

            sample = result.prepared.matrix().head(50)
            signature = infer_signature(
                sample.astype({c: "str" for c in result.supervised.categorical}),
                result.supervised.predict_proba(sample),
            )
            # artifact_path works in MLflow 2 (Databricks serverless) and 3 (local).
            mlflow.pyfunc.log_model(
                artifact_path="hgb_calibrated",
                python_model=SupervisedPyfunc(result.supervised),
                signature=signature,
                pip_requirements=["scikit-learn", "pandas", "numpy"],
            )
        return run.info.run_id
