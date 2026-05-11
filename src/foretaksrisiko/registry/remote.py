"""Registry access from the laptop: MLflow over a Databricks profile, events through the warehouse.

Promotion and rollback are manual, approved steps, so they run from the command line on the
laptop rather than inside a job. The registry itself is reached through MLflow's Databricks
URIs; the event records go to ``monitoring.registry_events`` through the SQL warehouse, which
is the only way to write a Delta table from outside a job on Free Edition.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict

from foretaksrisiko.registry.client import EVENT_COLUMNS, RegistryEvent

log = logging.getLogger(__name__)

EVENTS_DDL = (
    "event_time STRING, event STRING, model_name STRING, version STRING, from_version STRING, "
    "to_version STRING, decision STRING, approved BOOLEAN, actor STRING, details STRING, "
    "logged_at TIMESTAMP"
)


def connect(profile: str | None) -> None:
    """Point MLflow at the workspace's tracking server and Unity Catalog registry."""
    import mlflow

    suffix = f"://{profile}" if profile else ""
    mlflow.set_tracking_uri(f"databricks{suffix}")
    mlflow.set_registry_uri(f"databricks-uc{suffix}")


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def execute(profile: str | None, statement: str) -> None:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    warehouse = next(iter(client.warehouses.list()))
    response = client.statement_execution.execute_statement(
        warehouse_id=warehouse.id, statement=statement, wait_timeout="50s"
    )
    while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        response = client.statement_execution.get_statement(response.statement_id)
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"statement failed: {response.status.error}")


def write_events_sql(profile: str | None, names, events: list[RegistryEvent]) -> int:
    if not events:
        return 0
    table = names.table("monitoring", "registry_events")
    execute(profile, f"CREATE SCHEMA IF NOT EXISTS {names.schema('monitoring')}")
    execute(profile, f"CREATE TABLE IF NOT EXISTS {table} ({EVENTS_DDL})")
    values = ", ".join(
        "(" + ", ".join(sql_literal(asdict(e)[c]) for c in EVENT_COLUMNS) + ", current_timestamp())"
        for e in events
    )
    columns = ", ".join(EVENT_COLUMNS + ["logged_at"])
    execute(profile, f"INSERT INTO {table} ({columns}) VALUES {values}")
    log.info("wrote %d registry events to %s", len(events), table)
    return len(events)
