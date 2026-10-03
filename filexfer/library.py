"""对上层暴露的库入口：登记、继续执行、查询状态。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import engine
from .manifest import DEFAULT_CHUNK_SIZE, Manifest
from .store import Store


@dataclass(frozen=True)
class Status:
    task_id: str
    confirmed_bytes: int
    total_bytes: int
    completed: bool


class TransferLibrary:
    def __init__(self, db_path: str) -> None:
        self._store = Store(db_path)

    def close(self) -> None:
        self._store.close()

    def register(
        self,
        source_path: str,
        dest_path: str,
        manifest: Manifest,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> str:
        """登记传输任务，返回任务身份。重复登记同一清单返回同一身份。"""
        task_id = manifest.task_id(chunk_size)
        dest_dir = os.path.dirname(os.path.abspath(dest_path))
        os.makedirs(dest_dir, exist_ok=True)
        staging_path = os.path.join(
            dest_dir,
            f".{os.path.basename(dest_path)}.filexfer-{task_id[:16]}.part",
        )
        self._store.create_task(
            task_id=task_id,
            source_path=source_path,
            dest_path=dest_path,
            staging_path=staging_path,
            total_size=manifest.total_size,
            chunk_size=chunk_size,
            chunk_hashes=manifest.chunk_hashes,
        )
        return task_id

    def run(self, task_id: str) -> None:
        """继续执行任务直到完成或遇到可重试的错误。"""
        task = self._store.get_task(task_id)
        engine.run_task(self._store, task, self._store.chunk_hashes(task_id))

    def status(self, task_id: str) -> Status:
        task = self._store.get_task(task_id)
        confirmed = self._store.confirmed_prefix(task_id)
        confirmed_bytes = min(confirmed * task.chunk_size, task.total_size)
        return Status(
            task_id=task_id,
            confirmed_bytes=confirmed_bytes,
            total_bytes=task.total_size,
            completed=task.completed,
        )
