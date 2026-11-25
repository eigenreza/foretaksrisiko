"""Upload one snapshot's landing files to a Unity Catalog Volume. Company-level data only."""

from __future__ import annotations

import logging
from pathlib import Path

from foretaksrisiko.lakehouse.session import Names

log = logging.getLogger(__name__)

UPLOAD_SUFFIXES = {".parquet", ".json"}


def _create_ignoring_existing(action, *args, **kwargs) -> bool:
    try:
        action(*args, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 - the SDK raises several classes for "exists"
        if "already exists" in str(exc).lower() or "ALREADY_EXISTS" in str(exc):
            return False
        raise


def ensure_volume(client, names: Names) -> None:
    from databricks.sdk.service.catalog import VolumeType

    schema = f"{names.prefix}landing"
    _create_ignoring_existing(client.schemas.create, name=schema, catalog_name=names.catalog)
    _create_ignoring_existing(
        client.volumes.create,
        catalog_name=names.catalog,
        schema_name=schema,
        name=names.volume_name,
        volume_type=VolumeType.MANAGED,
    )


def upload_snapshot(
    landing_dir: Path,
    names: Names,
    snapshot_id: int,
    exclude: list[str],
    client=None,
) -> dict:
    """Upload Parquet tables and the manifest. Excluded tables and ledgers stay on the laptop."""
    if client is None:
        from databricks.sdk import WorkspaceClient

        client = WorkspaceClient()
    ensure_volume(client, names)
    root = Path(landing_dir) / f"snapshot={snapshot_id}"
    if not root.is_dir():
        raise FileNotFoundError(f"no landing folder for snapshot {snapshot_id}")
    summary = {"uploaded_files": 0, "skipped_files": 0, "bytes": 0, "tables": set()}
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(root).as_posix()
        top = rel.split("/")[0]
        if top in exclude or file.suffix not in UPLOAD_SUFFIXES:
            summary["skipped_files"] += 1
            continue
        with file.open("rb") as handle:
            client.files.upload(f"{names.snapshot_root(snapshot_id)}/{rel}", handle, overwrite=True)
        summary["uploaded_files"] += 1
        summary["bytes"] += file.stat().st_size
        if "/" in rel:
            summary["tables"].add(top)
    summary["tables"] = sorted(summary["tables"])
    summary["destination"] = names.snapshot_root(snapshot_id)
    log.info("upload done: %s", summary)
    return summary
