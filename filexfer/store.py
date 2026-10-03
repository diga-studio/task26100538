"""SQLite 恢复信息存储。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .errors import TaskNotFoundError


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    source_path: str
    dest_path: str
    staging_path: str
    total_size: int
    chunk_size: int
    completed: bool


class Store:
    """任务与分块进度的持久化。"""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id      TEXT PRIMARY KEY,
                source_path  TEXT NOT NULL,
                dest_path    TEXT NOT NULL,
                staging_path TEXT NOT NULL,
                total_size   INTEGER NOT NULL,
                chunk_size   INTEGER NOT NULL,
                completed    INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chunks (
                task_id  TEXT NOT NULL REFERENCES tasks(task_id),
                idx      INTEGER NOT NULL,
                sha256   TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (task_id, idx)
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_task(
        self,
        task_id: str,
        source_path: str,
        dest_path: str,
        staging_path: str,
        total_size: int,
        chunk_size: int,
        chunk_hashes: tuple[str, ...],
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO tasks"
                " (task_id, source_path, dest_path, staging_path,"
                "  total_size, chunk_size, completed)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                (task_id, source_path, dest_path, staging_path,
                 total_size, chunk_size),
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO chunks (task_id, idx, sha256, verified)"
                " VALUES (?, ?, ?, 0)",
                [(task_id, i, h) for i, h in enumerate(chunk_hashes)],
            )

    def get_task(self, task_id: str) -> TaskRecord:
        row = self._conn.execute(
            "SELECT task_id, source_path, dest_path, staging_path,"
            " total_size, chunk_size, completed FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return TaskRecord(
            task_id=row[0],
            source_path=row[1],
            dest_path=row[2],
            staging_path=row[3],
            total_size=row[4],
            chunk_size=row[5],
            completed=bool(row[6]),
        )

    def chunk_hashes(self, task_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT sha256 FROM chunks WHERE task_id = ? ORDER BY idx",
            (task_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def confirmed_prefix(self, task_id: str) -> int:
        """从 0 起连续已确认的分块数量。"""
        rows = self._conn.execute(
            "SELECT idx, verified FROM chunks WHERE task_id = ? ORDER BY idx",
            (task_id,),
        ).fetchall()
        count = 0
        for idx, verified in rows:
            if idx != count or not verified:
                break
            count += 1
        return count

    def mark_chunk_verified(self, task_id: str, index: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE chunks SET verified = 1 WHERE task_id = ? AND idx = ?",
                (task_id, index),
            )

    def mark_completed(self, task_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET completed = 1 WHERE task_id = ?",
                (task_id,),
            )
