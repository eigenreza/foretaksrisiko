"""The demo data export writes aggregate-only files and merges or drops small groups."""

from __future__ import annotations

import json
import re

from foretaksrisiko.figures.export import MIN_GROUP, MODELS, QUANTILES, SHARES, export_all
from foretaksrisiko.lakehouse.session import Names

NAMES = Names(catalog="cat", prefix="p_")


def fake_query(statement: str) -> list[dict]:
    sql = " ".join(statement.split())
    if "ORDER BY logged_at DESC" in sql:
        return [{"run_id": "run-a"}]
    if "max(reference_snapshot_id)" in sql:
        return [{"s": "2"}]
    if ".evaluation_metrics WHERE run_id" in sql:
        return [
            {
                "model": "hgb_calibrated",
                "ablation": "all",
                "split": "test",
                "seed": "1",
                "metric": "average_precision",
                "value": "0.28",
                "ci_low": "0.16",
                "ci_high": "0.40",
            }
        ]
    if ".calibration WHERE" in sql:
        return [{"bin": "1", "n": "900", "mean_predicted": "0.001", "observed_rate": "0.002"}]
    if ".explanations WHERE" in sql:
        return [{"model": "hgb", "feature": "age_years", "mean_abs_shap": "0.3", "ratio": None}]
    if ".fylke" in sql and "code, name" in sql:
        return [{"code": "03", "name": "Oslo"}, {"code": "46", "name": "Vestland"}]
    if "klass_sn2025" in sql:
        return [{"code": "F", "name": "Bygge- og anleggsvirksomhet"}]
    if ".fairness" in sql:
        return [
            {
                "model": "hgb_calibrated",
                "group_type": "fylke",
                "group_value": "03",
                "n": "1999.0",
                "base_rate": "0.005",
                "flag_rate": "0.05",
                "precision": "0.06",
                "per_group_threshold": "false",
            },
            {
                "model": "hgb_calibrated",
                "group_type": "size_band",
                "group_value": "0",
                "n": "907.0",
                "base_rate": "0.005",
                "flag_rate": "0.07",
                "precision": None,
                "per_group_threshold": "false",
            },
        ]
    if "coalesce(nace_section" in sql:
        return [
            {"nace_section": "F", "n": "800"},
            {"nace_section": "B", "n": "5"},
            {"nace_section": "E", "n": "17"},
        ]
    if "coalesce(fylke_code" in sql:
        return [
            {"fylke_code": "03", "n": "1999"},
            {"fylke_code": "46", "n": "1058"},
            {"fylke_code": "21", "n": "295"},
            {"fylke_code": "missing", "n": "1"},
        ]
    if "percentile_approx" in sql:
        row = {"split": "test"}
        for model in MODELS:
            row[model] = json.dumps([i / 100 for i in range(1, 100)])
        return [row]
    if "WITH ranked" in sql:
        return [
            {"share": str(s), "k": str(int(10000 * s)), "tp": "5", "n": "10000", "pos": "50"}
            for s in SHARES
        ]
    if "portfolio_size" in sql:
        return [{"bin_order": "0", "n": "500"}, {"bin_order": "8", "n": "3"}]
    if ".drift" in sql:
        raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")
    if ".score_summary" in sql:
        # The monitoring table names these columns rows and mean_score.
        assert "`rows` AS n, mean_score AS mean" in sql
        return [
            {
                "snapshot_id": "2",
                "scenario": "default",
                "side": "current",
                "n": "400000",
                "mean": "0.004",
                "p50": "0.001",
                "p90": "0.01",
                "p99": "0.05",
                "flag_share": "0.05",
            }
        ]
    if ".p_gold.champion_scores a JOIN" in sql:
        return [
            {
                "snapshot_id": "2",
                "previous_snapshot_id": "1",
                "model_version": "2",
                "n": "433000",
                "spearman": "0.98",
                "top_overlap": "0.9",
            }
        ]
    raise AssertionError(f"unexpected statement: {sql[:120]}")


def test_export_writes_aggregate_files_only(tmp_path) -> None:
    counts = export_all(fake_query, NAMES, tmp_path)

    assert counts["evaluation_metrics.csv"] == 1
    assert counts["score_quantiles.csv"] == len(MODELS) * len(QUANTILES)
    assert counts["topk.csv"] == len(MODELS) * len(SHARES)
    assert "drift.csv" not in counts and (tmp_path / "score_summary.csv").exists()

    stability = (tmp_path / "snapshot_stability.csv").read_text(encoding="utf-8").splitlines()
    assert stability == [
        "snapshot_id,previous_snapshot_id,model_version,n,spearman,top_share,top_overlap",
        "2,1,2,433000,0.98,0.01,0.9",
    ]

    sections = (tmp_path / "population_by_section.csv").read_text(encoding="utf-8").splitlines()
    assert any(
        line.startswith("2,F,Bygge- og anleggsvirksomhet,Construction,800") for line in sections
    )
    assert any(line.startswith("2,X,Andre,Other,22") for line in sections)
    assert not any(",B," in line or ",E," in line for line in sections)

    counties = (tmp_path / "population_by_fylke.csv").read_text(encoding="utf-8").splitlines()
    assert "2,21,Svalbard,295" in counties
    assert len(counties) == 4 and not any("Andre" in line or "missing" in line for line in counties)

    network = (tmp_path / "network_degree.csv").read_text(encoding="utf-8")
    assert "auditor,1,0,500" in network and "500+" not in network

    fairness = (tmp_path / "fairness.csv").read_text(encoding="utf-8")
    assert "fylke,03,Oslo,Oslo,1999" in fairness
    assert "size_band,0,Uten regnskap,No accounts,907" in fairness

    topk = (tmp_path / "topk.csv").read_text(encoding="utf-8").splitlines()[1]
    model, share, precision, lift, recall = topk.split(",")
    assert model == "rule" and float(share) == SHARES[0]
    assert abs(float(precision) - 0.1) < 1e-9 and abs(float(lift) - 20.0) < 1e-9
    assert abs(float(recall) - 0.1) < 1e-9

    for path in tmp_path.glob("*.csv"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{9}\b", text), path.name
        assert "organisasjonsnummer" not in text, path.name
    assert all(count >= 0 for count in counts.values())
    assert MIN_GROUP == 20
