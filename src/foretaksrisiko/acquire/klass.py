"""SSB Klass code lists: industry (SN2007, SN2025), counties, municipalities, correspondences."""

from __future__ import annotations

import logging

import pyarrow as pa

from foretaksrisiko.acquire.http import PoliteClient
from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter
from foretaksrisiko.config import KlassConfig

log = logging.getLogger(__name__)

KLASS_LICENCE = "CC BY 4.0"

KLASS_ITEM_SCHEMA = pa.schema(
    [
        ("code", pa.string()),
        ("parent_code", pa.string()),
        ("level", pa.int32()),
        ("name", pa.string()),
        ("short_name", pa.string()),
        ("notes", pa.string()),
    ]
)

KLASS_CORR_SCHEMA = pa.schema(
    [
        ("source_code", pa.string()),
        ("source_name", pa.string()),
        ("target_code", pa.string()),
        ("target_name", pa.string()),
    ]
)

JSON = {"Accept": "application/json"}


def _item_row(item: dict) -> dict:
    return {
        "code": str(item.get("code")),
        "parent_code": item.get("parentCode") or None,
        "level": int(item["level"]) if item.get("level") is not None else None,
        "name": item.get("name"),
        "short_name": item.get("shortName") or None,
        "notes": item.get("notes") or None,
    }


def _corr_row(entry: dict) -> dict:
    return {
        "source_code": entry.get("sourceCode"),
        "source_name": entry.get("sourceName"),
        "target_code": entry.get("targetCode"),
        "target_name": entry.get("targetName"),
    }


def acquire_klass(client: PoliteClient, landing: Landing, cfg: KlassConfig) -> dict:
    versions = {
        "sn2025": cfg.sn2025_version,
        "sn2007": cfg.sn2007_version,
        "fylke": cfg.fylke_version,
        "kommune": cfg.kommune_version,
    }
    correspondences = {
        "sn_corr_2025_2007": cfg.sn_correspondence_table,
        "fylke_corr_2026_2024": cfg.fylke_correspondence_table,
        "kommune_corr_2026_2024": cfg.kommune_correspondence_table,
    }
    summary: dict = {"licence": KLASS_LICENCE, "source": cfg.base_url}
    for name, version in versions.items():
        response = client.get(f"/versions/{version}", headers=JSON)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("classificationItems") or []
        with ParquetBatchWriter(landing.table_dir(f"klass/{name}"), KLASS_ITEM_SCHEMA) as w:
            for item in items:
                w.write(_item_row(item))
        summary[name] = {
            "version_id": version,
            "name": payload.get("name"),
            "valid_from": payload.get("validFrom"),
            "n_items": len(items),
        }
    for name, table_id in correspondences.items():
        response = client.get(f"/correspondencetables/{table_id}", headers=JSON)
        response.raise_for_status()
        payload = response.json()
        maps = payload.get("correspondenceMaps") or []
        with ParquetBatchWriter(landing.table_dir(f"klass/{name}"), KLASS_CORR_SCHEMA) as w:
            for entry in maps:
                w.write(_corr_row(entry))
        summary[name] = {"table_id": table_id, "name": payload.get("name"), "n_maps": len(maps)}
    log.info("klass done: %s", {k: v for k, v in summary.items()})
    landing.update_manifest("klass", summary)
    return summary
