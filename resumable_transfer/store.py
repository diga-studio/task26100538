"""SQLite-backed persistence for transfer tasks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .manifest import Manifest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    staging_path TEXT NOT NULL,
    total_size INTEGER NOT NULL,
    digests BLOB NOT NULL,
    confirmed_chunks INTEGER NOT NULL DEFAULT 0,
    published INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class TaskRecord:
    """Persisted state of one transfer task."""

    task_id: str
    source_path: str
    target_path: str
    staging_path: str
    manifest: Manifest
    confirmed_chunks: int
    published: bool


class TransferStore:
    """Persists task registrations and confirmed progress in SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def create_task(
        self,
        source_path: str,
        target_path: str,
        staging_path: str,
        manifest: Manifest,
    ) -> TaskRecord:
        task_id = manifest.identity().hex()
        packed = b"".join(manifest.digests)
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO tasks"
                " (task_id, source_path, target_path, staging_path,"
                "  total_size, digests, confirmed_chunks, published)"
                " VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                (task_id, source_path, target_path, staging_path,
                 manifest.total_size, packed),
            )
        record = self.get_task(task_id)
        assert record is not None
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute(
            "SELECT task_id, source_path, target_path, staging_path,"
            " total_size, digests, confirmed_chunks, published"
            " FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        packed = row[5]
        digests = tuple(
            packed[offset:offset + 32] for offset in range(0, len(packed), 32)
        )
        return TaskRecord(
            task_id=row[0],
            source_path=row[1],
            target_path=row[2],
            staging_path=row[3],
            manifest=Manifest(total_size=row[4], digests=digests),
            confirmed_chunks=row[6],
            published=bool(row[7]),
        )

    def set_confirmed_chunks(self, task_id: str, confirmed_chunks: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET confirmed_chunks = ? WHERE task_id = ?",
                (confirmed_chunks, task_id),
            )

    def set_published(self, task_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET published = 1 WHERE task_id = ?",
                (task_id,),
            )
