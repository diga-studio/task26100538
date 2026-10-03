"""分块校验传输与原子发布。"""

from __future__ import annotations

import hashlib
import os

from .errors import SourceMismatchError, SourceReadError
from .store import Store, TaskRecord


def run_task(store: Store, task: TaskRecord, chunk_hashes: list[str]) -> None:
    """继续执行任务：校验并写入未确认分块，全部确认后原子发布。

    遇到读失败或摘要不匹配时抛出异常，已确认进度保留。
    """
    if task.completed:
        return
    total_chunks = len(chunk_hashes)
    confirmed = store.confirmed_prefix(task.task_id)
    if confirmed < total_chunks:
        confirmed = _transfer(store, task, chunk_hashes, confirmed)
    if confirmed == total_chunks:
        _publish(store, task)


def _transfer(
    store: Store,
    task: TaskRecord,
    chunk_hashes: list[str],
    confirmed: int,
) -> int:
    try:
        src = open(task.source_path, "rb")
    except OSError as exc:
        raise SourceReadError(
            f"无法打开源文件 {task.source_path}: {exc}"
        ) from exc
    with src, open(task.staging_path, "r+b" if os.path.exists(task.staging_path)
                   else "w+b") as staging:
        index = confirmed
        while index < len(chunk_hashes):
            offset = index * task.chunk_size
            expected_len = min(task.chunk_size, task.total_size - offset)
            try:
                src.seek(offset)
                data = src.read(expected_len)
            except OSError as exc:
                raise SourceReadError(
                    f"读取源文件分块 {index} 失败: {exc}"
                ) from exc
            if len(data) != expected_len:
                raise SourceMismatchError(
                    f"分块 {index} 长度 {len(data)} 与清单期望"
                    f" {expected_len} 不符，源文件内容可能已变化"
                )
            digest = hashlib.sha256(data).hexdigest()
            if digest != chunk_hashes[index]:
                raise SourceMismatchError(
                    f"分块 {index} 摘要 {digest} 与清单"
                    f" {chunk_hashes[index]} 不匹配"
                )
            staging.seek(offset)
            staging.write(data)
            staging.flush()
            os.fsync(staging.fileno())
            store.mark_chunk_verified(task.task_id, index)
            index += 1
    return index


def _publish(store: Store, task: TaskRecord) -> None:
    """全部数据确认后，将暂存文件原子切换为目标文件。"""
    if not os.path.exists(task.staging_path):
        # 零长度任务可能尚未产生暂存文件。
        open(task.staging_path, "wb").close()
    with open(task.staging_path, "rb") as staging:
        os.fsync(staging.fileno())
    os.replace(task.staging_path, task.dest_path)
    dir_fd = os.open(os.path.dirname(task.dest_path) or ".", os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    store.mark_completed(task.task_id)
