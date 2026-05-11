"""Command line interface: one command per pipeline stage."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Annotated, BinaryIO

import typer

from foretaksrisiko import __version__
from foretaksrisiko.acquire.enheter import acquire_enheter
from foretaksrisiko.acquire.history import acquire_history, feed_timestamp
from foretaksrisiko.acquire.http import PoliteClient, gzip_stream, parse_http_date
from foretaksrisiko.acquire.klass import acquire_klass
from foretaksrisiko.acquire.landing import Landing, read_column
from foretaksrisiko.acquire.oppdateringer import acquire_updates
from foretaksrisiko.acquire.regnskap import RegnskapFetcher, filing_changed_companies
from foretaksrisiko.acquire.roller import acquire_roller
from foretaksrisiko.acquire.sampling import build_sample, copy_sample
from foretaksrisiko.acquire.underenheter import acquire_underenheter
from foretaksrisiko.acquire.verify import verify_landing
from foretaksrisiko.config import Settings, load_settings
from foretaksrisiko.lakehouse.bronze import load_bronze, read_manifest
from foretaksrisiko.lakehouse.features import build_features
from foretaksrisiko.lakehouse.gold import build_company_snapshot
from foretaksrisiko.lakehouse.labels import DESIGNS, build_labels
from foretaksrisiko.lakehouse.outcomes import build_outcomes
from foretaksrisiko.lakehouse.session import Names, get_spark, on_databricks
from foretaksrisiko.lakehouse.session import landing_root as resolve_landing_root
from foretaksrisiko.lakehouse.silver import (
    build_history,
    build_reference_tables,
    build_silver_enheter,
    build_silver_pass_through,
)
from foretaksrisiko.lakehouse.upload import upload_snapshot
from foretaksrisiko.quality.checks import run_layer_checks

app = typer.Typer(help="foretaksrisiko pipeline", no_args_is_help=True)
acquire_app = typer.Typer(help="Local acquisition with legal filters.", no_args_is_help=True)
app.add_typer(acquire_app, name="acquire")
lakehouse_app = typer.Typer(
    help="Bronze, silver and gold Delta tables with quality checks.", no_args_is_help=True
)
app.add_typer(lakehouse_app, name="lakehouse")
registry_app = typer.Typer(
    help="Model registry: status, promotion rule, approved promotion and rollback.",
    no_args_is_help=True,
)
app.add_typer(registry_app, name="registry")
figures_app = typer.Typer(help="Aggregate-only demo data and figures.", no_args_is_help=True)
app.add_typer(figures_app, name="figures")

log = logging.getLogger("foretaksrisiko")

SnapshotOpt = Annotated[int, typer.Option("--snapshot", "-s", min=1, help="Snapshot index")]
ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="YAML config path")]


def _configure_logging(settings: Settings, name: str) -> None:
    settings.paths.logs_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(settings.paths.logs_dir / f"{name}.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("py4j").setLevel(logging.WARNING)


def _setup(config: Path | None, snapshot: int) -> tuple[Settings, Landing]:
    settings = load_settings(config)
    landing = Landing(settings.paths.landing_dir, snapshot)
    _configure_logging(settings, f"acquire_snapshot_{snapshot}")
    log.info("foretaksrisiko %s, snapshot %d", __version__, snapshot)
    return settings, landing


def _client(settings: Settings, base_url: str | None = None) -> PoliteClient:
    http = settings.http
    return PoliteClient(
        base_url=base_url or settings.brreg.base_url,
        user_agent=http.user_agent,
        requests_per_second=http.requests_per_second,
        max_retries=http.max_retries,
        timeout_seconds=http.timeout_seconds,
        backoff_base_seconds=http.backoff_base_seconds,
        backoff_cap_seconds=http.backoff_cap_seconds,
    )


class BulkSource:
    """Opens a bulk download as a decompressed stream and remembers its file metadata."""

    def __init__(self, client: PoliteClient, landing: Landing, name: str, path: str, accept: str):
        self.client = client
        self.landing = landing
        self.name = name
        self.path = path
        self.accept = accept

    @contextmanager
    def __call__(self) -> Iterator[BinaryIO]:
        with self.client.stream(self.path, headers={"Accept": self.accept}) as response:
            if response.status_code != 200:
                raise RuntimeError(f"bulk download {self.name} failed: HTTP {response.status_code}")
            produced = parse_http_date(response.headers.get("last-modified"))
            meta = {
                "etag": response.headers.get("etag"),
                "last_modified": response.headers.get("last-modified"),
                "last_modified_iso": produced.astimezone(UTC).isoformat() if produced else None,
                "content_length": response.headers.get("content-length"),
                "content_type": response.headers.get("content-type"),
            }
            log.info("bulk %s: %s", self.name, meta)
            self.landing.update_manifest(self.name, {"source": meta})
            yield gzip_stream(response)


def _kept_orgnr(landing: Landing) -> set[str]:
    if not landing.table_exists("enheter"):
        raise typer.BadParameter("run 'acquire enheter' first; the kept population is missing")
    return set(read_column(landing.root / "enheter", "organisasjonsnummer"))


@acquire_app.command()
def enheter(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Download main units, keep AS and ASA, write landing tables."""
    settings, landing = _setup(config, snapshot)
    with _client(settings) as client:
        source = BulkSource(
            client,
            landing,
            "enheter",
            settings.brreg.enheter_bulk_path,
            settings.brreg.enheter_bulk_accept,
        )
        acquire_enheter(source, landing, settings.scope, settings.landing.rows_per_file)


@acquire_app.command()
def underenheter(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Download sub-units of kept companies."""
    settings, landing = _setup(config, snapshot)
    kept = _kept_orgnr(landing)
    with _client(settings) as client:
        source = BulkSource(
            client,
            landing,
            "underenheter",
            settings.brreg.underenheter_bulk_path,
            settings.brreg.underenheter_bulk_accept,
        )
        acquire_underenheter(source, landing, kept, settings.landing.rows_per_file)


@acquire_app.command()
def roller(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Stream the roles file and reduce it to counts and organisation links. Nothing raw is kept."""
    settings, landing = _setup(config, snapshot)
    kept = _kept_orgnr(landing)
    with _client(settings) as client:
        source = BulkSource(
            client,
            landing,
            "roller",
            settings.brreg.roller_bulk_path,
            settings.brreg.roller_bulk_accept,
        )
        acquire_roller(source, landing, kept, settings.landing.rows_per_file)


@acquire_app.command()
def klass(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Download SSB code lists and correspondence tables."""
    settings, landing = _setup(config, snapshot)
    with _client(settings, base_url=settings.klass.base_url) as client:
        acquire_klass(client, landing, settings.klass)


@acquire_app.command()
def sample(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    copy_from: Annotated[
        int | None,
        typer.Option("--copy-from", help="Reuse this earlier snapshot's sample (kept companies)"),
    ] = None,
) -> None:
    """Draw the stratified development sample, or carry an earlier one forward."""
    settings, landing = _setup(config, snapshot)
    if copy_from is not None:
        previous = Landing(settings.paths.landing_dir, copy_from)
        typer.echo(json.dumps(copy_sample(landing, previous, _kept_orgnr(landing)), indent=2))
        return
    build_sample(landing, settings.sample.size, settings.sample.seed)


@acquire_app.command()
def regnskap(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    limit: Annotated[int | None, typer.Option(help="Fetch at most this many companies")] = None,
    full: Annotated[bool, typer.Option(help="Whole population instead of the sample")] = False,
    carry_forward_from: Annotated[
        int | None,
        typer.Option(
            "--carry-forward-from",
            help="Copy accounts from this snapshot; fetch only new, changed or due companies",
        ),
    ] = None,
) -> None:
    """Fetch accounts, one call per company, resumable."""
    settings, landing = _setup(config, snapshot)
    if full or carry_forward_from is not None:
        orgnrs = sorted(_kept_orgnr(landing))
    else:
        if not landing.table_exists("sample"):
            raise typer.BadParameter("run 'acquire sample' first, or pass --full")
        orgnrs = sorted(read_column(landing.root / "sample", "organisasjonsnummer"))
    with _client(settings) as client:
        fetcher = RegnskapFetcher(
            client,
            landing,
            settings.brreg.regnskap_path,
            settings.landing.regnskap_batch_size,
            workers=settings.http.workers,
        )
        if carry_forward_from is not None:
            previous = Landing(settings.paths.landing_dir, carry_forward_from)
            plan = fetcher.carry_forward(
                previous,
                set(orgnrs),
                filing_changed_companies(landing),
                settings.landing.regnskap_refresh_share,
            )
            typer.echo(json.dumps(plan, indent=2))
        fetcher.run(orgnrs, limit=limit)


def _previous_snapshot_time(settings: Settings, snapshot: int) -> str | None:
    """Production time of the previous snapshot's unit file, in the update feed's format."""
    return _snapshot_time(settings, snapshot - 1) if snapshot > 1 else None


def _snapshot_time(settings: Settings, snapshot: int) -> str | None:
    section = Landing(settings.paths.landing_dir, snapshot).read_manifest().get("enheter") or {}
    iso = (section.get("source") or {}).get("last_modified_iso") or section.get("updated_at")
    if not iso:
        return None
    return feed_timestamp(iso)


@acquire_app.command()
def updates(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    since: Annotated[
        str | None, typer.Option(help="ISO-8601 UTC start, default: previous snapshot")
    ] = None,
    until: Annotated[str | None, typer.Option(help="ISO-8601 UTC end")] = None,
) -> None:
    """Fetch change events since the previous snapshot, reduced to counts per company."""
    settings, landing = _setup(config, snapshot)
    since = since or _previous_snapshot_time(settings, snapshot)
    if not since:
        raise typer.BadParameter("no previous snapshot found; pass --since")
    kept = _kept_orgnr(landing)
    kept_sub = (
        set(read_column(landing.root / "underenheter", "organisasjonsnummer"))
        if landing.table_exists("underenheter")
        else None
    )
    with _client(settings) as client:
        acquire_updates(client, settings.brreg, landing, since, kept, kept_sub, until)


@acquire_app.command()
def history(
    snapshot: SnapshotOpt,
    since: Annotated[str, typer.Option(help="ISO-8601 UTC start of the event history window")],
    config: ConfigOpt = None,
    until: Annotated[str | None, typer.Option(help="ISO-8601 UTC end")] = None,
    no_roles: Annotated[bool, typer.Option("--no-roles", help="Skip the role event feed")] = False,
) -> None:
    """Fetch unit and role change events for the population, reduced to field names and counts."""
    settings, landing = _setup(config, snapshot)
    kept = _kept_orgnr(landing)
    since = feed_timestamp(since)
    until = feed_timestamp(until) if until else None
    with _client(settings) as client:
        summary = acquire_history(
            client, settings.brreg, landing, since, kept, until, include_roles=not no_roles
        )
    typer.echo(json.dumps(summary, indent=2))


@acquire_app.command()
def text(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Compute text similarity features locally from the free-text table (numbers only)."""
    from foretaksrisiko.features.text import build_text_features

    settings, landing = _setup(config, snapshot)
    typer.echo(json.dumps(build_text_features(landing), indent=2))


@acquire_app.command("all")
def run_all(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    limit: Annotated[int | None, typer.Option(help="Limit accounts fetch, for trial runs")] = None,
    previous: Annotated[
        int | None,
        typer.Option(
            "--previous",
            help="Earlier snapshot to build on: same sample, events since it, accounts carried",
        ),
    ] = None,
) -> None:
    """Run every acquisition stage in order for one snapshot.

    With ``--previous`` the snapshot reuses the earlier development sample, fetches the change
    events since that snapshot (field names and counts only) and fetches accounts only for new,
    changed or due companies, copying the rest. The first snapshot fetches everything.
    """
    enheter(snapshot, config)
    underenheter(snapshot, config)
    roller(snapshot, config)
    klass(snapshot, config)
    sample(snapshot, config, copy_from=previous)
    settings = load_settings(config)
    since = _snapshot_time(settings, previous) if previous else None
    if since:
        history(snapshot, since, config)
    text(snapshot, config)
    regnskap(snapshot, config, limit=limit, full=previous is not None, carry_forward_from=previous)


@acquire_app.command()
def verify(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Check the landing tables of one snapshot and print counts, shares and check results."""
    settings, landing = _setup(config, snapshot)
    report = verify_landing(landing, settings.scope)
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if not report["all_checks_passed"]:
        raise typer.Exit(code=1)


LandingDirOpt = Annotated[
    str | None, typer.Option("--landing-dir", help="Override the snapshot folder to read")
]


def _lakehouse_setup(config: Path | None, snapshot: int, landing_dir: str | None):
    settings = load_settings(config)
    _configure_logging(settings, f"lakehouse_snapshot_{snapshot}")
    local = not on_databricks()
    names = Names.from_config(settings.lakehouse, local)
    root = landing_dir or resolve_landing_root(settings, names, snapshot, local)
    spark = get_spark(settings.lakehouse)
    log.info("lakehouse: snapshot %d, local=%s, landing %s", snapshot, local, root)
    return settings, names, spark, root


@lakehouse_app.command()
def upload(snapshot: SnapshotOpt, config: ConfigOpt = None) -> None:
    """Upload one snapshot's landing tables to the Unity Catalog volume."""
    settings = load_settings(config)
    _configure_logging(settings, f"lakehouse_snapshot_{snapshot}")
    names = Names.from_config(settings.lakehouse, local=False)
    summary = upload_snapshot(
        settings.paths.landing_dir, names, snapshot, settings.lakehouse.upload_exclude
    )
    typer.echo(json.dumps(summary, indent=2))


@lakehouse_app.command()
def bronze(
    snapshot: SnapshotOpt, config: ConfigOpt = None, landing_dir: LandingDirOpt = None
) -> None:
    """Load landing tables into bronze Delta tables and run the bronze checks."""
    settings, names, spark, root = _lakehouse_setup(config, snapshot, landing_dir)
    counts = load_bronze(
        spark,
        names,
        root,
        snapshot,
        settings.lakehouse.bronze_tables,
        settings.lakehouse.klass_tables,
    )
    run_layer_checks(
        spark, names, snapshot, "bronze", settings.quality, settings.scope, read_manifest(root)
    )
    typer.echo(json.dumps(counts, indent=2))


@lakehouse_app.command()
def silver(
    snapshot: SnapshotOpt, config: ConfigOpt = None, landing_dir: LandingDirOpt = None
) -> None:
    """Build silver tables, the history table, and run the silver checks."""
    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    summary = {"reference": build_reference_tables(spark, names, snapshot)}
    summary["enheter"] = build_silver_enheter(spark, names, snapshot)
    summary["pass_through"] = build_silver_pass_through(spark, names, snapshot)
    summary["history"] = build_history(spark, names, snapshot)
    run_layer_checks(spark, names, snapshot, "silver", settings.quality)
    typer.echo(json.dumps(summary, indent=2))


@lakehouse_app.command()
def gold(
    snapshot: SnapshotOpt, config: ConfigOpt = None, landing_dir: LandingDirOpt = None
) -> None:
    """Build the gold company snapshot table and run the gold checks."""
    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    rows = build_company_snapshot(spark, names, snapshot)
    run_layer_checks(spark, names, snapshot, "gold", settings.quality)
    typer.echo(json.dumps({"company_snapshot_rows": rows}, indent=2))


@lakehouse_app.command()
def features(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    landing_dir: LandingDirOpt = None,
    design: Annotated[str, typer.Option(help="retro, prospective or all")] = "all",
) -> None:
    """Build gold outcomes, labels and features for the reference snapshot."""
    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    summary = {"outcomes_rows": build_outcomes(spark, names)}
    summary["labels"] = build_labels(spark, names, settings.design)
    designs = list(DESIGNS) if design == "all" else [design]
    summary["features"] = [
        build_features(spark, names, settings.design, snapshot, d) for d in designs
    ]
    typer.echo(json.dumps(summary, indent=2, default=str))


def _registry_for_lakehouse(settings: Settings, names: Names, spark):
    from foretaksrisiko.registry.client import make_registry

    local = not on_databricks()
    actor = "local" if local else spark.sql("SELECT current_user() AS u").first()["u"]
    return make_registry(settings.registry, names, local=local, actor=actor)


@lakehouse_app.command()
def train(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    landing_dir: LandingDirOpt = None,
    design: Annotated[str, typer.Option(help="retro or prospective")] = "retro",
    scope: Annotated[str, typer.Option(help="sample or population")] = "sample",
    register: Annotated[
        bool, typer.Option("--register/--no-register", help="Register the run as the challenger")
    ] = True,
) -> None:
    """Train and evaluate against the pre-registered plan; log to MLflow; register a challenger."""
    from foretaksrisiko.models.lakehouse_train import train_on_lakehouse

    if scope not in ("sample", "population"):
        raise typer.BadParameter("scope must be sample or population")
    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    summary = train_on_lakehouse(
        spark, names, settings, snapshot, design, sample_only=scope == "sample", register=register
    )
    typer.echo(json.dumps(summary, indent=2, default=str))


@lakehouse_app.command()
def score(
    snapshot: SnapshotOpt, config: ConfigOpt = None, landing_dir: LandingDirOpt = None
) -> None:
    """Score the snapshot's prospective features with the champion model."""
    from foretaksrisiko.models.lakehouse_score import score_with_champion

    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    registry = _registry_for_lakehouse(settings, names, spark)
    summary = score_with_champion(spark, names, settings, registry, snapshot)
    typer.echo(json.dumps(summary, indent=2, default=str))


ScenarioOpt = Annotated[
    str, typer.Option("--scenario", help="Threshold set: default or a scenario from the config")
]


@lakehouse_app.command()
def monitor(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    landing_dir: LandingDirOpt = None,
    reference: Annotated[
        int,
        typer.Option(
            "--reference", help="Reference snapshot; 0 means the champion's training snapshot"
        ),
    ] = 0,
    scenario: ScenarioOpt = "default",
) -> None:
    """Drift against the reference snapshot, score summaries, alerts and retraining advice."""
    from foretaksrisiko.monitoring.lakehouse_monitor import monitor_snapshot

    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    registry = _registry_for_lakehouse(settings, names, spark)
    summary = monitor_snapshot(
        spark, names, settings, registry, snapshot, reference or None, scenario
    )
    typer.echo(json.dumps(summary, indent=2, default=str))


@lakehouse_app.command()
def alert(
    snapshot: SnapshotOpt,
    config: ConfigOpt = None,
    landing_dir: LandingDirOpt = None,
    scenario: ScenarioOpt = "default",
) -> None:
    """Fail when alert-level monitoring records exist, so the job sends its email."""
    from foretaksrisiko.monitoring.lakehouse_monitor import check_alerts

    settings, names, spark, _ = _lakehouse_setup(config, snapshot, landing_dir)
    records = check_alerts(spark, names, snapshot, scenario)
    typer.echo(json.dumps({"snapshot_id": snapshot, "scenario": scenario, "records": records}))


@lakehouse_app.command("run")
def lakehouse_run(
    snapshot: SnapshotOpt, config: ConfigOpt = None, landing_dir: LandingDirOpt = None
) -> None:
    """Bronze, silver and gold for one snapshot, with checks after every layer."""
    bronze(snapshot, config, landing_dir)
    silver(snapshot, config, landing_dir)
    gold(snapshot, config, landing_dir)
    features(snapshot, config, landing_dir)


ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", help="Databricks CLI profile when run from the laptop"),
]
VersionArg = Annotated[str, typer.Argument(help="Model version number in the registry")]
ApproveOpt = Annotated[
    bool,
    typer.Option(
        "--approve", help="Record the manual approval; without it the command only reports"
    ),
]


def _registry_setup(config: Path | None, profile: str | None):
    """Registry plus an event sink: Spark inside Databricks, the SQL warehouse from the laptop."""
    from foretaksrisiko.registry.client import make_registry, write_events

    settings = load_settings(config)
    _configure_logging(settings, "registry")
    names = Names.from_config(settings.lakehouse, local=False)
    if on_databricks():
        spark = get_spark(settings.lakehouse)
        registry = _registry_for_lakehouse(settings, names, spark)
        return registry, lambda events: write_events(spark, names, events)
    from foretaksrisiko.registry.remote import connect, write_events_sql

    connect(profile)
    registry = make_registry(
        settings.registry, names, local=False, actor=f"cli:{profile or 'default'}"
    )
    return registry, lambda events: write_events_sql(profile, names, events)


@registry_app.command("status")
def registry_status(config: ConfigOpt = None, profile: ProfileOpt = None) -> None:
    """Show the champion and challenger versions and the previous champion."""
    registry, _ = _registry_setup(config, profile)
    typer.echo(json.dumps(registry.status(), indent=2, default=str))


@registry_app.command("evaluate")
def registry_evaluate(
    version: VersionArg, config: ConfigOpt = None, profile: ProfileOpt = None
) -> None:
    """Apply the promotion rule to a version without changing any alias."""
    registry, sink = _registry_setup(config, profile)
    decision = registry.evaluate(version)
    sink(registry.events)
    typer.echo(
        json.dumps(
            {"version": version, "eligible": decision.eligible, "checks": decision.checks},
            indent=2,
            default=str,
        )
    )


@registry_app.command("promote")
def registry_promote(
    version: VersionArg,
    approve: ApproveOpt = False,
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
) -> None:
    """Make a version the champion: needs the rule to pass and --approve (manual approval)."""
    registry, sink = _registry_setup(config, profile)
    decision = registry.promote(version, approved=approve)
    sink(registry.events)
    status = registry.status()
    champion = status.get("aliases", {}).get(registry.cfg.champion_alias, {}).get("version")
    typer.echo(
        json.dumps(
            {
                "version": version,
                "approved": approve,
                "eligible": decision.eligible,
                "promoted": str(champion) == str(version),
                "reasons": decision.reasons,
                "champion": champion,
            },
            indent=2,
            default=str,
        )
    )


@registry_app.command("rollback")
def registry_rollback(
    approve: ApproveOpt = False, config: ConfigOpt = None, profile: ProfileOpt = None
) -> None:
    """Move the champion alias back to the previous champion version."""
    registry, sink = _registry_setup(config, profile)
    restored = registry.rollback(approved=approve)
    sink(registry.events)
    typer.echo(
        json.dumps(
            {"approved": approve, "restored_version": restored, "status": registry.status()},
            indent=2,
            default=str,
        )
    )


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


def job_main() -> None:
    """Entry point for Databricks wheel tasks.

    Databricks runs wheel entry points inside an interpreter where a normal ``sys.exit(0)`` is
    reported as a failure, so the Typer app runs without standalone mode: success returns, and
    errors propagate as exceptions that fail the task.
    """
    import sys

    app(sys.argv[1:], standalone_mode=False)


DemoDirOpt = Annotated[Path, typer.Option("--demo-dir", help="Folder for the aggregate demo files")]
FiguresDirOpt = Annotated[Path, typer.Option("--out", help="Folder for the rendered figures")]
RunIdOpt = Annotated[str | None, typer.Option(help="Evaluation run id, default: the latest")]
PopSnapshotOpt = Annotated[
    int | None, typer.Option("--snapshot", help="Snapshot for population counts, default: latest")
]


@figures_app.command("export")
def figures_export(
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    run_id: RunIdOpt = None,
    snapshot: PopSnapshotOpt = None,
    demo_dir: DemoDirOpt = Path("demo_data"),
) -> None:
    """Export aggregate-only demo data from the lakehouse through the SQL warehouse."""
    from foretaksrisiko.figures.export import export_all, warehouse_query

    settings = load_settings(config)
    _configure_logging(settings, "figures")
    names = Names.from_config(settings.lakehouse, local=False)
    counts = export_all(warehouse_query(profile), names, demo_dir, run_id, snapshot)
    typer.echo(json.dumps(counts, indent=2))


@figures_app.command("render")
def figures_render(
    lang: Annotated[str, typer.Option(help="no, en or all")] = "all",
    demo_dir: DemoDirOpt = Path("demo_data"),
    out: FiguresDirOpt = Path("figures"),
) -> None:
    """Render every figure from the demo data files, in Norwegian and English."""
    from foretaksrisiko.figures.build import render_all

    written: list[Path] = []
    for code in ("no", "en") if lang == "all" else (lang,):
        written.extend(render_all(demo_dir, out, code))
    typer.echo(json.dumps([str(path) for path in written], indent=2))


demo_app = typer.Typer(help="Demo artefacts for the Streamlit app.", no_args_is_help=True)
app.add_typer(demo_app, name="demo")


@demo_app.command("export")
def demo_export(
    config: ConfigOpt = None,
    profile: ProfileOpt = None,
    out: Annotated[Path, typer.Option("--out", help="Directory for the demo artefacts")] = Path(
        "demo_data/model"
    ),
) -> None:
    """Export the champion model and aggregate statistics for the demo, never training rows."""
    from foretaksrisiko.demo.artefacts import export_all as export_demo_artefacts
    from foretaksrisiko.figures.export import warehouse_query
    from foretaksrisiko.registry.client import registry_model_name
    from foretaksrisiko.registry.remote import connect

    settings = load_settings(config)
    _configure_logging(settings, "demo")
    names = Names.from_config(settings.lakehouse, local=False)
    connect(profile)
    model_name = registry_model_name(settings.registry, names, local=False)
    counts = export_demo_artefacts(
        warehouse_query(profile), names, settings, out, model_name, settings.registry.champion_alias
    )
    typer.echo(json.dumps(counts, indent=1))


if __name__ == "__main__":
    app()
