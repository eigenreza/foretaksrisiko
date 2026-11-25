"""Gold labels: proxy outcomes within a horizon after a reference time, for two designs.

retro:        reference time = first day of the month ``retro_offset_months`` before the snapshot
              date; outcomes come from what the register and the events show today, with the known
              deletion depletion.
prospective:  reference time = the snapshot date; outcomes arrive through later snapshots' events,
              complete by construction. Labels are recomputed from all knowledge on every run.
"""

from __future__ import annotations

import logging
from datetime import date

from foretaksrisiko.config import DesignConfig
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, overwrite_table

log = logging.getLogger(__name__)

DESIGNS = ("retro", "prospective")


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ][month - 1]
    return date(year, month, min(day.day, last_day))


def reference_date(design: str, snapshot_date: date, cfg: DesignConfig) -> date:
    if design == "prospective":
        return snapshot_date
    if design == "retro":
        return add_months(snapshot_date.replace(day=1), -cfg.retro_offset_months)
    raise ValueError(f"unknown design {design}")


def snapshot_dates(spark, names: Names) -> dict[int, date]:
    rows = spark.sql(
        f"SELECT snapshot_id, max(snapshot_date) AS d FROM {names.table('silver', 'enheter')} "
        "GROUP BY snapshot_id ORDER BY snapshot_id"
    ).collect()
    return {int(r["snapshot_id"]): r["d"] for r in rows}


def build_labels(spark, names: Names, cfg: DesignConfig) -> dict:
    """Rebuild gold.labels for every (design, reference snapshot) from gold.outcomes."""
    ensure_schemas(spark, names, ("gold",))
    dates = snapshot_dates(spark, names)
    latest_known = max(dates.values())
    outcomes = names.table("gold", "outcomes")
    enheter = names.table("silver", "enheter")
    parts = []
    summary: dict = {}
    for snapshot_id, snapshot_date in dates.items():
        for design in DESIGNS:
            t = reference_date(design, snapshot_date, cfg)
            end = add_months(t, cfg.horizon_months)
            t_lit, end_lit, known_lit = (f"DATE '{d.isoformat()}'" for d in (t, end, latest_known))
            parts.append(
                f"""
                SELECT e.organisasjonsnummer,
                       '{design}' AS design,
                       {snapshot_id} AS reference_snapshot_id,
                       {t_lit} AS reference_date,
                       {cfg.horizon_months} AS horizon_months,
                       {end_lit} AS window_end,
                       least({end_lit}, {known_lit}) AS observed_until,
                       {end_lit} <= {known_lit} AS fully_observed,
                       e.registreringsdato_enhetsregisteret <= {t_lit}
                         AND (o.first_bankruptcy_date IS NULL OR o.first_bankruptcy_date > {t_lit})
                         AND (o.first_forced_date IS NULL OR o.first_forced_date > {t_lit})
                         AND (o.first_voluntary_date IS NULL OR o.first_voluntary_date > {t_lit})
                         AND (o.deletion_date IS NULL OR o.deletion_date > {t_lit}) AS eligible,
                       CASE WHEN o.first_bankruptcy_date > {t_lit} AND o.first_bankruptcy_date <= {end_lit}
                            THEN o.first_bankruptcy_date END AS outcome_bankruptcy_date,
                       CASE WHEN o.first_forced_date > {t_lit} AND o.first_forced_date <= {end_lit}
                            THEN o.first_forced_date END AS outcome_forced_date,
                       CASE WHEN o.first_voluntary_date > {t_lit} AND o.first_voluntary_date <= {end_lit}
                            THEN o.first_voluntary_date END AS outcome_voluntary_date,
                       CASE WHEN o.deletion_date > {t_lit} AND o.deletion_date <= {end_lit}
                            THEN o.deletion_date END AS deletion_in_window_date
                FROM {enheter} e
                LEFT JOIN {outcomes} o ON o.organisasjonsnummer = e.organisasjonsnummer
                WHERE e.snapshot_id = {snapshot_id}
                """
            )
            summary[f"{design}_{snapshot_id}"] = {
                "reference_date": t.isoformat(),
                "window_end": end.isoformat(),
            }
    union = "\nUNION ALL\n".join(parts)
    labels = spark.sql(
        f"""
        SELECT *,
               eligible AND (outcome_bankruptcy_date IS NOT NULL OR outcome_forced_date IS NOT NULL)
                 AS label_strict,
               eligible AND (outcome_bankruptcy_date IS NOT NULL OR outcome_forced_date IS NOT NULL
                             OR outcome_voluntary_date IS NOT NULL) AS label_broad,
               eligible AND outcome_bankruptcy_date IS NULL AND outcome_forced_date IS NULL
                 AND outcome_voluntary_date IS NULL AND deletion_in_window_date IS NOT NULL
                 AS left_register_without_outcome
        FROM ({union})
        """
    )
    target = names.table("gold", "labels")
    overwrite_table(labels, target)
    stats = spark.sql(
        f"""
        SELECT design, reference_snapshot_id, count(*) AS rows, sum(CAST(eligible AS INT)) AS eligible,
               sum(CAST(label_strict AS INT)) AS strict, sum(CAST(label_broad AS INT)) AS broad,
               max(fully_observed) AS fully_observed
        FROM {target} GROUP BY design, reference_snapshot_id ORDER BY design, reference_snapshot_id
        """
    ).collect()
    for r in stats:
        key = f"{r['design']}_{r['reference_snapshot_id']}"
        summary[key].update(
            {
                "rows": int(r["rows"]),
                "eligible": int(r["eligible"] or 0),
                "label_strict": int(r["strict"] or 0),
                "label_broad": int(r["broad"] or 0),
                "fully_observed": bool(r["fully_observed"]),
            }
        )
    log.info("gold labels: %s", summary)
    return summary
