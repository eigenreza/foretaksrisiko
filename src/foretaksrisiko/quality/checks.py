"""Quality checks: schema, counts, uniqueness, checksums, ranges and referential integrity."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from foretaksrisiko.acquire.enheter import ENHET_SCHEMA
from foretaksrisiko.acquire.regnskap import REGNSKAP_SCHEMA, REGNSKAP_STATUS_SCHEMA
from foretaksrisiko.acquire.roller import ROLLER_COUNTS_SCHEMA, ROLLER_LINKS_SCHEMA
from foretaksrisiko.acquire.sampling import SAMPLE_SCHEMA
from foretaksrisiko.acquire.underenheter import UNDERENHET_SCHEMA
from foretaksrisiko.config import QualityConfig, ScopeConfig
from foretaksrisiko.lakehouse.session import Names, ensure_schemas, table_exists
from foretaksrisiko.orgnr import WEIGHTS

log = logging.getLogger(__name__)

RESULTS_DDL = (
    "snapshot_id INT, layer STRING, table STRING, check STRING, severity STRING, passed BOOLEAN, "
    "observed DOUBLE, threshold DOUBLE, detail STRING, run_at TIMESTAMP"
)

EXPECTED_COLUMNS = {
    "enheter": ENHET_SCHEMA.names,
    "underenheter": UNDERENHET_SCHEMA.names,
    "roller_counts": ROLLER_COUNTS_SCHEMA.names,
    "roller_links": ROLLER_LINKS_SCHEMA.names,
    "sample": SAMPLE_SCHEMA.names,
    "regnskap": REGNSKAP_SCHEMA.names,
    "regnskap_status": REGNSKAP_STATUS_SCHEMA.names,
}

MANIFEST_COUNTS = {
    "enheter": ("enheter", "rows_kept"),
    "underenheter": ("underenheter", "rows_kept"),
    "roller_counts": ("roller", "entries_kept"),
    "roller_links": ("roller", "links"),
    "sample": ("sample", "sample_size"),
}


class QualityError(RuntimeError):
    """Raised when an error-level check fails."""


@dataclass
class CheckResult:
    snapshot_id: int
    layer: str
    table: str
    check: str
    severity: str
    passed: bool
    observed: float | None
    threshold: float | None
    detail: str = ""


def mod11_valid_sql(column: str) -> str:
    """SQL boolean: the nine-digit string in ``column`` has a valid MOD11 check digit."""
    weighted = " + ".join(
        f"CAST(substr({column}, {i + 1}, 1) AS INT) * {w}" for i, w in enumerate(WEIGHTS)
    )
    expected = f"((11 - (({weighted}) % 11)) % 11)"
    return (
        f"({column} RLIKE '^[0-9]{{9}}$' AND {expected} <> 10 "
        f"AND {expected} = CAST(substr({column}, 9, 1) AS INT))"
    )


class Checker:
    """Collects check results for one snapshot and layer, then writes them and raises on errors."""

    def __init__(self, spark, names: Names, snapshot_id: int, layer: str) -> None:
        self.spark = spark
        self.names = names
        self.snapshot_id = int(snapshot_id)
        self.layer = layer
        self.results: list[CheckResult] = []

    def _where(self, where: str | None) -> str:
        return where if where is not None else f"snapshot_id = {self.snapshot_id}"

    def _scalar(self, sql: str):
        return self.spark.sql(sql).first()[0]

    def _exists(self, table: str) -> bool:
        return table_exists(self.spark, self.names.table(self.layer, table))

    def record(self, table, check, passed, observed, threshold, severity="error", detail=""):
        result = CheckResult(
            self.snapshot_id,
            self.layer,
            table,
            check,
            severity,
            bool(passed),
            None if observed is None else float(observed),
            None if threshold is None else float(threshold),
            detail,
        )
        self.results.append(result)
        log.log(
            logging.INFO if passed else logging.WARNING,
            "check %s.%s %s: %s (observed %s, threshold %s)",
            self.layer,
            table,
            check,
            "pass" if passed else "FAIL",
            observed,
            threshold,
        )
        return result

    def count_equals(self, table, expected, where=None, severity="error", check="row_count"):
        name = self.names.table(self.layer, table)
        observed = self._scalar(f"SELECT count(*) FROM {name} WHERE {self._where(where)}")
        return self.record(table, check, observed == expected, observed, expected, severity)

    def count_positive(self, table, where=None, severity="error"):
        name = self.names.table(self.layer, table)
        observed = self._scalar(f"SELECT count(*) FROM {name} WHERE {self._where(where)}")
        return self.record(table, "rows_present", observed > 0, observed, 1, severity)

    def unique(self, table, keys, where=None, severity="error"):
        name = self.names.table(self.layer, table)
        cols = ", ".join(keys)
        observed = self._scalar(
            f"SELECT count(*) - count(*) FILTER (WHERE rn = 1) FROM ("
            f"SELECT row_number() OVER (PARTITION BY {cols} ORDER BY {keys[0]}) AS rn "
            f"FROM {name} WHERE {self._where(where)})"
        )
        return self.record(table, f"unique_{'_'.join(keys)}", observed == 0, observed, 0, severity)

    def subset(
        self, table, columns, parent_table, parent_columns, where=None, severity="error", check=None
    ):
        child = self.names.table(self.layer, table)
        parent = self.names.table(self.layer, parent_table)
        on = " AND ".join(f"c.{a} = p.{b}" for a, b in zip(columns, parent_columns, strict=True))
        observed = self._scalar(
            f"SELECT count(*) FROM {child} c LEFT ANTI JOIN "
            f"(SELECT * FROM {parent} WHERE {self._where(where)}) p ON {on} "
            f"WHERE c.{self._where(where)}"
        )
        check = check or f"{'_'.join(columns)}_in_{parent_table}"
        return self.record(table, check, observed == 0, observed, 0, severity)

    def share(
        self, table, condition, check, minimum=None, maximum=None, where=None, severity="error"
    ):
        name = self.names.table(self.layer, table)
        observed = self._scalar(
            f"SELECT avg(CASE WHEN {condition} THEN 1.0 ELSE 0.0 END) FROM {name} "
            f"WHERE {self._where(where)}"
        )
        observed = 0.0 if observed is None else float(observed)
        passed = True
        threshold = None
        if minimum is not None:
            passed = passed and observed >= minimum
            threshold = minimum
        if maximum is not None:
            passed = passed and observed <= maximum
            threshold = maximum
        return self.record(table, check, passed, observed, threshold, severity)

    def columns_present(self, table, expected, severity="error"):
        name = self.names.table(self.layer, table)
        missing = sorted(set(expected) - set(self.spark.table(name).columns))
        return self.record(
            table, "expected_columns", not missing, len(missing), 0, severity, ", ".join(missing)
        )

    def write(self) -> None:
        from pyspark.sql import functions as F

        ensure_schemas(self.spark, self.names, ("monitoring",))
        rows = [tuple(asdict(r).values()) + (None,) for r in self.results]
        df = self.spark.createDataFrame(rows, RESULTS_DDL).withColumn(
            "run_at", F.current_timestamp()
        )
        df.write.format("delta").mode("append").saveAsTable(
            self.names.table("monitoring", "quality_results")
        )

    def raise_if_failed(self) -> None:
        failed = [r for r in self.results if not r.passed and r.severity == "error"]
        if failed:
            lines = ", ".join(f"{r.table}.{r.check} (observed {r.observed})" for r in failed)
            raise QualityError(f"{len(failed)} quality check(s) failed in {self.layer}: {lines}")


def bronze_checks(checker: Checker, manifest: dict, scope: ScopeConfig, cfg: QualityConfig) -> None:
    for table, columns in EXPECTED_COLUMNS.items():
        if checker._exists(table):
            checker.columns_present(table, columns)
    for table, (section, key) in MANIFEST_COUNTS.items():
        expected = (manifest.get(section) or {}).get(key)
        if checker._exists(table) and expected is not None:
            checker.count_equals(table, int(expected), check="row_count_matches_manifest")
    for table in ("enheter", "underenheter", "roller_counts", "sample"):
        if checker._exists(table):
            checker.unique(table, ["organisasjonsnummer"])
    if checker._exists("enheter"):
        forms = ", ".join(f"'{f}'" for f in scope.organisasjonsformer)
        checker.share(
            "enheter",
            mod11_valid_sql("organisasjonsnummer"),
            "valid_mod11",
            minimum=1.0,
            severity=cfg.mod11_severity,
        )
        checker.share("enheter", f"organisasjonsform IN ({forms})", "forms_in_scope", minimum=1.0)
        checker.share(
            "enheter",
            "registrert_i_frivillighetsregisteret",
            "no_frivillighetsregisteret",
            maximum=0.0,
        )


def silver_checks(checker: Checker, cfg: QualityConfig) -> None:
    bronze_count = checker._scalar(
        f"SELECT count(*) FROM {checker.names.table('bronze', 'enheter')} "
        f"WHERE snapshot_id = {checker.snapshot_id}"
    )
    checker.count_equals("enheter", int(bronze_count), check="row_count_matches_bronze")
    checker.unique("enheter", ["organisasjonsnummer"])
    checker.share(
        "enheter",
        "nace_section IS NOT NULL",
        "nace_section_coverage",
        minimum=cfg.min_nace_section_share,
        severity="warn",
    )
    checker.share(
        "enheter",
        "nace_code IS NULL OR nace_standard IS NOT NULL",
        "nace_code_known_in_a_standard",
        minimum=1.0,
        severity="warn",
    )
    checker.share(
        "enheter",
        "fylke_name IS NOT NULL",
        "fylke_coverage",
        minimum=cfg.min_fylke_coverage,
        severity="warn",
    )
    checker.share(
        "enheter",
        "kommune_name IS NOT NULL",
        "kommune_coverage",
        minimum=cfg.min_kommune_coverage,
        severity="warn",
    )
    checker.share(
        "enheter",
        "kapital_belop IS NULL OR kapital_belop >= 0",
        "kapital_non_negative",
        minimum=1.0,
    )
    checker.share(
        "enheter",
        "antall_ansatte IS NULL OR antall_ansatte >= 5",
        "antall_ansatte_published_threshold",
        minimum=1.0,
        severity="warn",
    )
    checker.share(
        "enheter",
        "stiftelsesdato IS NOT NULL AND stiftelsesdato > snapshot_date",
        "stiftelsesdato_in_future",
        maximum=cfg.max_future_date_share,
    )
    checker.share(
        "enheter",
        "konkursdato IS NOT NULL AND konkursdato > snapshot_date",
        "konkursdato_in_future",
        maximum=0.0,
        severity="warn",
    )
    for table, columns in (
        ("underenheter", ["overordnet_enhet"]),
        ("roller_counts", ["organisasjonsnummer"]),
        ("roller_links", ["organisasjonsnummer"]),
        ("roller_links", ["rolleholder_organisasjonsnummer"]),
        ("regnskap", ["organisasjonsnummer"]),
        ("regnskap_status", ["organisasjonsnummer"]),
        ("sample", ["organisasjonsnummer"]),
    ):
        if checker._exists(table):
            checker.subset(table, columns, "enheter", ["organisasjonsnummer"])
    if checker._exists("roller_counts"):
        checker.share(
            "roller_counts",
            "board_size >= 0 AND n_roles_active <= n_roles_total",
            "role_counts_consistent",
            minimum=1.0,
        )
    if checker._exists("regnskap"):
        checker.unique("regnskap", ["organisasjonsnummer", "regnskap_id"])
        # Both dates are inclusive, so a period that starts and ends on the same day is one day
        # long and valid. Only an end before the start is an error.
        checker.share(
            "regnskap",
            "regnskapsperiode_til_dato >= regnskapsperiode_fra_dato",
            "period_end_not_before_start",
            minimum=1.0,
        )
        checker.share(
            "regnskap",
            "sum_eiendeler IS NULL OR sum_eiendeler >= 0",
            "assets_non_negative",
            minimum=1.0,
            severity="warn",
        )
    if checker._exists("enheter_history"):
        history = checker.names.table("silver", "enheter_history")
        enheter = checker.names.table("silver", "enheter")
        observed = checker._scalar(
            f"SELECT count(*) FROM (SELECT e.organisasjonsnummer, "
            f"count(h.organisasjonsnummer) AS c "
            f"FROM {enheter} e LEFT JOIN {history} h "
            f"ON h.organisasjonsnummer = e.organisasjonsnummer AND h.is_current "
            f"WHERE e.snapshot_id = {checker.snapshot_id} GROUP BY e.organisasjonsnummer) "
            f"WHERE c <> 1"
        )
        checker.record("enheter_history", "one_current_row_per_company", observed == 0, observed, 0)


def gold_checks(checker: Checker) -> None:
    silver_count = checker._scalar(
        f"SELECT count(*) FROM {checker.names.table('silver', 'enheter')} "
        f"WHERE snapshot_id = {checker.snapshot_id}"
    )
    checker.count_equals("company_snapshot", int(silver_count), check="row_count_matches_silver")
    checker.unique("company_snapshot", ["organisasjonsnummer"])
    checker.share(
        "company_snapshot",
        "organisasjonsnummer IS NOT NULL AND snapshot_date IS NOT NULL "
        "AND organisasjonsform IS NOT NULL",
        "keys_not_null",
        minimum=1.0,
    )
    checker.share("company_snapshot", "has_accounts", "has_accounts_share", severity="info")
    checker.share("company_snapshot", "has_ceo", "has_ceo_share", severity="info")
    checker.share("company_snapshot", "n_sub_units > 0", "has_sub_units_share", severity="info")


def run_layer_checks(
    spark,
    names: Names,
    snapshot_id: int,
    layer: str,
    cfg: QualityConfig,
    scope: ScopeConfig | None = None,
    manifest: dict | None = None,
) -> list[CheckResult]:
    checker = Checker(spark, names, snapshot_id, layer)
    if layer == "bronze":
        bronze_checks(checker, manifest or {}, scope or ScopeConfig(), cfg)
    elif layer == "silver":
        silver_checks(checker, cfg)
    elif layer == "gold":
        gold_checks(checker)
    else:
        raise ValueError(f"unknown layer {layer}")
    checker.write()
    checker.raise_if_failed()
    return checker.results
