"""Landing zone: one folder per snapshot, Parquet tables, a JSON manifest with counts only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class Landing:
    """Paths for one snapshot under the landing directory."""

    def __init__(self, landing_dir: Path, snapshot_id: int) -> None:
        if snapshot_id < 1:
            raise ValueError("snapshot_id starts at 1")
        self.snapshot_id = snapshot_id
        self.root = Path(landing_dir) / f"snapshot={snapshot_id}"

    def table_dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def table_exists(self, name: str) -> bool:
        path = self.root / name
        return path.is_dir() and any(path.glob("*.parquet"))

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def read_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {"snapshot_id": self.snapshot_id}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def update_manifest(self, section: str, values: dict) -> None:
        """Merge values into one section. Only counts and metadata belong here, never records."""
        manifest = self.read_manifest()
        manifest["snapshot_id"] = self.snapshot_id
        section_values = dict(manifest.get(section) or {})
        section_values.update(values)
        section_values["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        manifest[section] = section_values
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


class ParquetBatchWriter:
    """Buffers rows and writes fixed-schema Parquet files of bounded size."""

    def __init__(
        self,
        directory: Path,
        schema: pa.Schema,
        rows_per_file: int = 50_000,
        prefix: str = "part",
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self.rows_per_file = rows_per_file
        self.prefix = prefix
        self._rows: list[dict] = []
        self.files_written = 0
        self.rows_written = 0

    def write(self, row: dict) -> None:
        self._rows.append(row)
        if len(self._rows) >= self.rows_per_file:
            self._flush()

    def _flush(self) -> None:
        if not self._rows and self.files_written > 0:
            return
        table = pa.Table.from_pylist(self._rows, schema=self.schema)
        target = self.directory / f"{self.prefix}-{self.files_written:05d}.parquet"
        tmp = target.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp)
        tmp.replace(target)
        self.files_written += 1
        self.rows_written += len(self._rows)
        self._rows = []

    def close(self) -> int:
        """Flush remaining rows. Writes an empty file if nothing was written, to keep the schema."""
        self._flush()
        return self.rows_written

    def __enter__(self) -> ParquetBatchWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()


def read_table(directory: Path, columns: list[str] | None = None) -> pa.Table:
    files = sorted(Path(directory).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files in {directory}")
    return pq.read_table([str(f) for f in files], columns=columns, partitioning=None)


def read_column(directory: Path, column: str) -> list:
    return read_table(directory, columns=[column]).column(column).to_pylist()
