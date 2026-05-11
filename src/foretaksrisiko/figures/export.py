"""Export aggregate-only demo data from the lakehouse through a SQL warehouse.

Every file written here is public material: model-level metrics, calibration bins, global
explanations, group tables with small groups removed, population counts with small cells merged,
score quantiles, top-k curves and monitoring series. No organisation numbers, names or
per-company rows leave the lakehouse. Groups below ``MIN_GROUP`` companies are merged or dropped.
"""

from __future__ import annotations

import csv
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from foretaksrisiko.lakehouse.session import Names

log = logging.getLogger(__name__)

MIN_GROUP = 20
MODELS = ("rule", "isolation_forest", "mahalanobis", "hgb_calibrated")
SHARES = (0.005, 0.01, 0.02, 0.05, 0.10, 0.20)
QUANTILES = [round(i / 100, 2) for i in range(1, 100)]
# Share of the ranking compared between two snapshots, as in the stability across seeds.
STABILITY_SHARE = 0.01
SIZE_BINS = [
    (1, 1, "1"),
    (2, 4, "2-4"),
    (5, 9, "5-9"),
    (10, 19, "10-19"),
    (20, 49, "20-49"),
    (50, 99, "50-99"),
    (100, 199, "100-199"),
    (200, 499, "200-499"),
    (500, None, "500+"),
]
OTHER = {"no": "Andre", "en": "Other"}
MISSING = {"no": "Ukjent", "en": "Unknown"}
# SN2025 follows NACE Rev. 2.1, where the section letters from J onwards differ from SN2007.
NACE_SECTION_NO = {
    "A": "Jordbruk, skogbruk og fiske",
    "B": "Bergverksdrift og utvinning",
    "C": "Industri",
    "D": "Elektrisitet, gass og damp",
    "E": "Vann, avløp og renovasjon",
    "F": "Bygge- og anleggsvirksomhet",
    "G": "Varehandel",
    "H": "Transport og lagring",
    "I": "Overnatting og servering",
    "J": "Utgivelse og kringkasting",
    "K": "Telekommunikasjon og IT-tjenester",
    "L": "Finansiell tjenesteyting",
    "M": "Eiendomsvirksomhet",
    "N": "Faglig, vitenskapelig og teknisk tjenesteyting",
    "O": "Forretningsmessig tjenesteyting",
    "P": "Offentlig administrasjon og forsvar",
    "Q": "Undervisning",
    "R": "Helse- og sosialtjenester",
    "S": "Kultur, idrett og fritid",
    "T": "Annen tjenesteyting",
    "U": "Lønnet arbeid i private husholdninger",
    "V": "Internasjonale organisasjoner",
}
NACE_SECTION_EN = {
    "A": "Agriculture, forestry and fishing",
    "B": "Mining and quarrying",
    "C": "Manufacturing",
    "D": "Electricity, gas and steam",
    "E": "Water supply and waste",
    "F": "Construction",
    "G": "Wholesale and retail trade",
    "H": "Transportation and storage",
    "I": "Accommodation and food service",
    "J": "Publishing and broadcasting",
    "K": "Telecommunication and IT services",
    "L": "Financial and insurance activities",
    "M": "Real estate activities",
    "N": "Professional, scientific and technical",
    "O": "Administrative and support services",
    "P": "Public administration and defence",
    "Q": "Education",
    "R": "Human health and social work",
    "S": "Arts, sports and recreation",
    "T": "Other service activities",
    "U": "Households as employers",
    "V": "Extraterritorial organisations",
}
# The register uses county code 21 for Svalbard, which the county code list does not carry.
FYLKE_FALLBACK = {"21": "Svalbard"}
SIZE_BAND_LABELS = {
    "0": ("Uten regnskap", "No accounts"),
    "1": ("Minste firedel", "Smallest quarter"),
    "2": ("Nest minste firedel", "Second quarter"),
    "3": ("Nest største firedel", "Third quarter"),
    "4": ("75 til 90 prosent", "75th to 90th percentile"),
    "5": ("Største tidel", "Largest tenth"),
}

Query = Callable[[str], list[dict]]


def warehouse_query(profile: str | None) -> Query:
    """Return a function that runs a statement on the first SQL warehouse and returns dict rows."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    warehouse = next(iter(client.warehouses.list()))

    def query(statement: str) -> list[dict]:
        response = client.statement_execution.execute_statement(
            warehouse_id=warehouse.id, statement=statement, wait_timeout="50s"
        )
        while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(3)
            response = client.statement_execution.get_statement(response.statement_id)
        if response.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"statement failed: {response.status.error}")
        columns = [c.name for c in response.manifest.schema.columns]
        chunk = response.result
        rows = list(chunk.data_array or [])
        while chunk is not None and chunk.next_chunk_index is not None:
            chunk = client.statement_execution.get_statement_result_chunk_n(
                response.statement_id, chunk.next_chunk_index
            )
            rows.extend(chunk.data_array or [])
        return [dict(zip(columns, row, strict=True)) for row in rows]

    return query


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})
    return len(rows)


def _num(value) -> float | None:
    return None if value in (None, "") else float(value)


def _int(value) -> int | None:
    return None if value in (None, "") else int(float(value))


def latest_run_id(query: Query, names: Names) -> str | None:
    rows = query(
        f"SELECT run_id FROM {names.table('monitoring', 'evaluation_metrics')} "
        "ORDER BY logged_at DESC LIMIT 1"
    )
    return rows[0]["run_id"] if rows else None


def latest_snapshot_id(query: Query, names: Names) -> int | None:
    rows = query(
        f"SELECT max(reference_snapshot_id) AS s FROM {names.table('gold', 'features')} "
        "WHERE design = 'prospective'"
    )
    return _int(rows[0]["s"]) if rows and rows[0]["s"] is not None else None


def export_metrics(query: Query, names: Names, run_id: str, out: Path) -> dict[str, int]:
    monitoring = names.table("monitoring", "evaluation_metrics")
    rows = query(
        f"SELECT model, ablation, split, seed, metric, value, ci_low, ci_high FROM {monitoring} "
        f"WHERE run_id = '{run_id}' ORDER BY model, ablation, split, seed, metric"
    )
    counts = {
        "evaluation_metrics.csv": write_csv(
            out / "evaluation_metrics.csv",
            rows,
            ["model", "ablation", "split", "seed", "metric", "value", "ci_low", "ci_high"],
        )
    }
    rows = query(
        f"SELECT bin, n, mean_predicted, observed_rate FROM "
        f"{names.table('monitoring', 'calibration')} WHERE run_id = '{run_id}' ORDER BY bin"
    )
    counts["calibration.csv"] = write_csv(
        out / "calibration.csv", rows, ["bin", "n", "mean_predicted", "observed_rate"]
    )
    rows = query(
        f"SELECT model, feature, mean_abs_shap, ratio FROM "
        f"{names.table('monitoring', 'explanations')} WHERE run_id = '{run_id}' "
        "ORDER BY model, feature"
    )
    counts["explanations.csv"] = write_csv(
        out / "explanations.csv", rows, ["model", "feature", "mean_abs_shap", "ratio"]
    )
    return counts


def _reference_names(query: Query, names: Names) -> tuple[dict[str, str], dict[str, str]]:
    fylke = {
        r["code"]: r["name"]
        for r in query(f"SELECT code, name FROM {names.table('silver', 'fylke')}")
    }
    sections = {
        r["code"]: r["name"]
        for r in query(
            f"SELECT code, name FROM {names.table('silver', 'klass_sn2025')} WHERE level = 1"
        )
    }
    return fylke, sections


def _group_labels(
    group_type: str, value: str, fylke: dict[str, str], sections: dict[str, str]
) -> tuple[str, str]:
    if value == "missing":
        return MISSING["no"], MISSING["en"]
    if group_type == "fylke":
        name = fylke.get(value) or FYLKE_FALLBACK.get(value, value)
        return name, name
    if group_type == "nace_section":
        label_no = NACE_SECTION_NO.get(value) or sections.get(value, value)
        return label_no, NACE_SECTION_EN.get(value, value)
    if group_type == "size_band":
        return SIZE_BAND_LABELS.get(value, (value, value))
    return value, value


def export_fairness(query: Query, names: Names, run_id: str, out: Path) -> dict[str, int]:
    fylke, sections = _reference_names(query, names)
    rows = query(
        "SELECT model, group_type, group_value, n, base_rate, flag_rate, precision, "
        f"per_group_threshold FROM {names.table('monitoring', 'fairness')} "
        f"WHERE run_id = '{run_id}' AND NOT suppressed AND n >= {MIN_GROUP} "
        "ORDER BY model, per_group_threshold, group_type, group_value"
    )
    for row in rows:
        row["group_label_no"], row["group_label_en"] = _group_labels(
            row["group_type"], str(row["group_value"]), fylke, sections
        )
        row["n"] = _int(row["n"])
    return {
        "fairness.csv": write_csv(
            out / "fairness.csv",
            rows,
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
    }


def _merge_small(rows: list[dict], key: str, other_code: str, labels: dict[str, str]) -> list[dict]:
    """Merge groups below the minimum size into one 'other' row, dropped if still too small."""
    kept = [r for r in rows if r["n"] >= MIN_GROUP]
    small = [r for r in rows if r["n"] < MIN_GROUP]
    if small:
        merged = dict(small[0])
        merged[key] = other_code
        merged["n"] = sum(r["n"] for r in small)
        for lang in ("no", "en"):
            if f"{labels['prefix']}_{lang}" in merged:
                merged[f"{labels['prefix']}_{lang}"] = OTHER[lang]
        if "fylke_name" in merged:
            merged["fylke_name"] = OTHER["no"]
        if merged["n"] >= MIN_GROUP:
            kept.append(merged)
    return kept


def export_population(query: Query, names: Names, snapshot_id: int, out: Path) -> dict[str, int]:
    fylke, sections = _reference_names(query, names)
    features = names.table("gold", "features")
    where = f"WHERE design = 'prospective' AND reference_snapshot_id = {snapshot_id}"
    rows = query(
        f"SELECT coalesce(nace_section, 'missing') AS nace_section, count(*) AS n "
        f"FROM {features} {where} GROUP BY 1 ORDER BY 1"
    )
    for row in rows:
        row["n"] = _int(row["n"])
        row["snapshot_id"] = snapshot_id
        row["section_label_no"], row["section_label_en"] = _group_labels(
            "nace_section", row["nace_section"], fylke, sections
        )
    rows = _merge_small(rows, "nace_section", "X", {"prefix": "section_label"})
    counts = {
        "population_by_section.csv": write_csv(
            out / "population_by_section.csv",
            rows,
            ["snapshot_id", "nace_section", "section_label_no", "section_label_en", "n"],
        )
    }
    rows = query(
        f"SELECT coalesce(fylke_code, 'missing') AS fylke_code, count(*) AS n "
        f"FROM {features} {where} GROUP BY 1 ORDER BY 1"
    )
    for row in rows:
        row["n"] = _int(row["n"])
        row["snapshot_id"] = snapshot_id
        row["fylke_name"] = _group_labels("fylke", row["fylke_code"], fylke, sections)[0]
    rows = _merge_small(rows, "fylke_code", "99", {"prefix": "fylke_label"})
    counts["population_by_fylke.csv"] = write_csv(
        out / "population_by_fylke.csv", rows, ["snapshot_id", "fylke_code", "fylke_name", "n"]
    )
    return counts


def export_scores(query: Query, names: Names, run_id: str, out: Path) -> dict[str, int]:
    scores = names.table("gold", "scores")
    quantile_list = ", ".join(str(q) for q in QUANTILES)
    columns = ", ".join(
        f"percentile_approx({m}, array({quantile_list}), 10000) AS {m}" for m in MODELS
    )
    rows = query(f"SELECT split, {columns} FROM {scores} WHERE run_id = '{run_id}' GROUP BY split")
    quantile_rows = []
    for row in rows:
        for model in MODELS:
            values = row[model]
            if isinstance(values, str):
                values = json.loads(values)
            if not values:
                continue
            for q, value in zip(QUANTILES, values, strict=True):
                quantile_rows.append(
                    {"model": model, "split": row["split"], "quantile": q, "value": value}
                )
    counts = {
        "score_quantiles.csv": write_csv(
            out / "score_quantiles.csv", quantile_rows, ["model", "split", "quantile", "value"]
        )
    }
    share_list = ", ".join(str(s) for s in SHARES)
    topk_rows = []
    for model in MODELS:
        rows = query(
            f"""
            WITH ranked AS (
              SELECT CAST(label AS INT) AS y,
                     row_number() OVER (ORDER BY {model} DESC) AS rk,
                     count(*) OVER () AS n,
                     sum(CAST(label AS INT)) OVER () AS pos
              FROM {scores}
              WHERE run_id = '{run_id}' AND split = 'test' AND {model} IS NOT NULL
            )
            SELECT share, count(*) AS k, sum(y) AS tp, max(n) AS n, max(pos) AS pos
            FROM ranked CROSS JOIN (SELECT explode(array({share_list})) AS share)
            WHERE rk <= ceil(n * share)
            GROUP BY share ORDER BY share
            """
        )
        for row in rows:
            k, tp, n, pos = (_num(row["k"]), _num(row["tp"]), _num(row["n"]), _num(row["pos"]))
            if not k or not n or not pos:
                continue
            precision = tp / k
            topk_rows.append(
                {
                    "model": model,
                    "share": _num(row["share"]),
                    "precision": precision,
                    "lift": precision / (pos / n),
                    "recall": tp / pos,
                }
            )
    counts["topk.csv"] = write_csv(
        out / "topk.csv", topk_rows, ["model", "share", "precision", "lift", "recall"]
    )
    return counts


def export_network(query: Query, names: Names, snapshot_id: int, out: Path) -> dict[str, int]:
    features = names.table("gold", "features")
    cases = " ".join(
        f"WHEN {{col}} >= {low} THEN {order}"
        for order, (low, _high, _label) in reversed(list(enumerate(SIZE_BINS)))
    )
    rows: list[dict] = []
    for kind in ("auditor", "accountant"):
        col = f"{kind}_portfolio_size"
        case = cases.format(col=col)
        result = query(
            f"SELECT CASE {case} END AS bin_order, count(*) AS n FROM {features} "
            f"WHERE design = 'prospective' AND reference_snapshot_id = {snapshot_id} "
            f"AND {col} IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        for row in result:
            order = _int(row["bin_order"])
            n = _int(row["n"])
            if order is None or n is None or n < MIN_GROUP:
                continue
            rows.append(
                {
                    "kind": kind,
                    "size_bin": SIZE_BINS[order][2],
                    "bin_order": order,
                    "n_companies": n,
                }
            )
    return {
        "network_degree.csv": write_csv(
            out / "network_degree.csv", rows, ["kind", "size_bin", "bin_order", "n_companies"]
        )
    }


def export_monitoring(query: Query, names: Names, out: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        rows = query(
            "SELECT snapshot_id, reference_snapshot_id, scenario, feature, metric, value, severity "
            f"FROM {names.table('monitoring', 'drift')} "
            "ORDER BY scenario, snapshot_id, feature, metric"
        )
    except RuntimeError as exc:
        log.info("drift table not exported: %s", exc)
        rows = []
    if rows:
        counts["drift.csv"] = write_csv(
            out / "drift.csv",
            rows,
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
    try:
        rows = query(
            "SELECT snapshot_id, scenario, side, `rows` AS n, mean_score AS mean, p50, p90, p99, "
            "flag_share "
            f"FROM {names.table('monitoring', 'score_summary')} "
            "ORDER BY scenario, snapshot_id, side"
        )
    except RuntimeError as exc:
        log.info("score summary not exported: %s", exc)
        rows = []
    if rows:
        counts["score_summary.csv"] = write_csv(
            out / "score_summary.csv",
            rows,
            ["snapshot_id", "scenario", "side", "n", "mean", "p50", "p90", "p99", "flag_share"],
        )
    return counts


def export_snapshot_stability(query: Query, names: Names, out: Path) -> dict[str, int]:
    """Rank stability of the champion score between consecutive snapshots, as aggregates.

    Only companies scored in both snapshots by the same model version are compared. Ties get
    their average rank for the correlation, and the organisation number breaks ties at the edge
    of the top share the same way on both sides.
    """
    scores = names.table("gold", "champion_scores")
    try:
        rows = query(
            f"""
            WITH pairs AS (
              SELECT b.snapshot_id, a.snapshot_id AS previous_snapshot_id, b.model_version,
                     a.organisasjonsnummer AS company, a.score AS previous_score, b.score AS score
              FROM {scores} a JOIN {scores} b
                ON b.organisasjonsnummer = a.organisasjonsnummer AND b.design = a.design
               AND b.model_version = a.model_version AND b.snapshot_id = a.snapshot_id + 1
            ),
            ranked AS (
              SELECT snapshot_id, previous_snapshot_id, model_version,
                     rank() OVER (PARTITION BY snapshot_id ORDER BY previous_score)
                       + (count(*) OVER (PARTITION BY snapshot_id, previous_score) - 1) / 2.0
                       AS previous_rank,
                     rank() OVER (PARTITION BY snapshot_id ORDER BY score)
                       + (count(*) OVER (PARTITION BY snapshot_id, score) - 1) / 2.0
                       AS current_rank,
                     row_number() OVER (
                       PARTITION BY snapshot_id ORDER BY previous_score DESC, company
                     ) AS previous_position,
                     row_number() OVER (
                       PARTITION BY snapshot_id ORDER BY score DESC, company
                     ) AS current_position,
                     ceil({STABILITY_SHARE} * count(*) OVER (PARTITION BY snapshot_id)) AS k
              FROM pairs
            )
            SELECT snapshot_id, previous_snapshot_id, max(model_version) AS model_version,
                   count(*) AS n, corr(previous_rank, current_rank) AS spearman,
                   sum(
                     CASE WHEN previous_position <= k AND current_position <= k THEN 1 ELSE 0 END
                   ) / max(k) AS top_overlap
            FROM ranked
            GROUP BY snapshot_id, previous_snapshot_id
            ORDER BY snapshot_id
            """
        )
    except RuntimeError as exc:
        log.info("snapshot stability not exported: %s", exc)
        rows = []
    if not rows:
        return {}
    for row in rows:
        row["top_share"] = STABILITY_SHARE
    return {
        "snapshot_stability.csv": write_csv(
            out / "snapshot_stability.csv",
            rows,
            [
                "snapshot_id",
                "previous_snapshot_id",
                "model_version",
                "n",
                "spearman",
                "top_share",
                "top_overlap",
            ],
        )
    }


def export_all(
    query: Query,
    names: Names,
    out: Path,
    run_id: str | None = None,
    snapshot_id: int | None = None,
) -> dict[str, int]:
    """Write every demo data file. Returns the row count per file."""
    run_id = run_id or latest_run_id(query, names)
    snapshot_id = snapshot_id or latest_snapshot_id(query, names)
    if run_id is None or snapshot_id is None:
        raise RuntimeError("no evaluation run or no prospective features found")
    log.info("exporting demo data for run %s and snapshot %s", run_id, snapshot_id)
    counts: dict[str, int] = {}
    counts.update(export_metrics(query, names, run_id, out))
    counts.update(export_fairness(query, names, run_id, out))
    counts.update(export_population(query, names, snapshot_id, out))
    counts.update(export_scores(query, names, run_id, out))
    counts.update(export_network(query, names, snapshot_id, out))
    counts.update(export_monitoring(query, names, out))
    counts.update(export_snapshot_stability(query, names, out))
    return counts
