"""Transfer engine: registration, resumable execution, status queries."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    SourceChangedError,
    SourceUnavailableError,
    TaskNotFoundError,
    TransferError,
)
from .manifest import CHUNK_SIZE, Manifest
from .store import TransferStore

_READ_BLOCK = 1024 * 1024


@dataclass(frozen=True)
class TransferStatus:
    """Snapshot of a task's confirmed progress."""

    task_id: str
    confirmed_chunks: int
    total_chunks: int
    confirmed_bytes: int
    total_bytes: int
    complete: bool


class TransferEngine:
    """High-level API used directly by callers."""

    def __init__(self, db_path: str | Path) -> None:
        self._store = TransferStore(db_path)

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "TransferEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def register(
        self,
        source_path: str | Path,
        target_path: str | Path,
        manifest: Manifest,
    ) -> str:
        """Register a transfer task; returns the task id."""
        source_path = str(source_path)
        target_path = str(target_path)
        staging_path = self._staging_path(target_path, manifest)
        record = self._store.create_task(
            source_path, target_path, staging_path, manifest
        )
        if record.source_path != source_path or record.target_path != target_path:
            raise TransferError(
                "manifest already registered with different paths: "
                f"source={record.source_path!r} target={record.target_path!r}"
            )
        return record.task_id

    def resume(self, task_id: str) -> TransferStatus:
        """Continue a task: verify/transfer pending chunks, publish when done."""
        record = self._require_task(task_id)
        if record.published:
            return self._to_status(record)

        confirmed = self._recover_staging(record)
        manifest = record.manifest

        if confirmed < manifest.chunk_count:
            confirmed = self._transfer_chunks(record, confirmed)

        self._publish(record)
        self._store.set_published(task_id)
        return self._to_status(self._require_task(task_id))

    def status(self, task_id: str) -> TransferStatus:
        """Query confirmed progress and completion state."""
        return self._to_status(self._require_task(task_id))

    @staticmethod
    def _staging_path(target_path: str, manifest: Manifest) -> str:
        return f"{target_path}.{manifest.identity().hex()}.part"

    def _require_task(self, task_id: str):
        record = self._store.get_task(task_id)
        if record is None:
            raise TaskNotFoundError(task_id)
        return record

    def _recover_staging(self, record) -> int:
        """Drop confirmed progress whose staging bytes are no longer present."""
        confirmed = record.confirmed_chunks
        if confirmed == 0:
            return 0
        manifest = record.manifest
        expected_size = sum(
            manifest.chunk_length(i) for i in range(confirmed)
        )
        try:
            actual_size = os.path.getsize(record.staging_path)
        except OSError:
            actual_size = -1
        if actual_size < expected_size:
            confirmed = 0
            self._store.set_confirmed_chunks(record.task_id, 0)
        return confirmed

    def _transfer_chunks(self, record, confirmed: int) -> int:
        manifest = record.manifest
        try:
            source = open(record.source_path, "rb")
        except OSError as exc:
            raise SourceUnavailableError(
                f"cannot open source {record.source_path!r}: {exc}"
            ) from exc
        with source:
            source.seek(0, os.SEEK_END)
            if source.tell() != manifest.total_size:
                raise SourceChangedError(
                    f"source size {source.tell()} does not match "
                    f"manifest size {manifest.total_size}"
                )
            staging = open(record.staging_path, "r+b" if confirmed else "w+b")
            with staging:
                for index in range(confirmed, manifest.chunk_count):
                    offset = CHUNK_SIZE * index
                    length = manifest.chunk_length(index)
                    source.seek(offset)
                    data = self._read_exact(source, length, record.source_path)
                    if hashlib.sha256(data).digest() != manifest.digests[index]:
                        raise SourceChangedError(
                            f"chunk {index} digest mismatch; "
                            "source content does not match the manifest"
                        )
                    staging.seek(offset)
                    staging.write(data)
                    staging.flush()
                    os.fsync(staging.fileno())
                    confirmed = index + 1
                    self._store.set_confirmed_chunks(record.task_id, confirmed)
        return confirmed

    @staticmethod
    def _read_exact(source, length: int, source_path: str) -> bytes:
        parts = []
        remaining = length
        while remaining > 0:
            try:
                block = source.read(min(_READ_BLOCK, remaining))
            except OSError as exc:
                raise SourceUnavailableError(
                    f"cannot read source {source_path!r}: {exc}"
                ) from exc
            if not block:
                raise SourceUnavailableError(
                    f"source {source_path!r} ended early "
                    f"({remaining} bytes missing)"
                )
            parts.append(block)
            remaining -= len(block)
        return b"".join(parts)

    @staticmethod
    def _publish(record) -> None:
        """Atomically replace the target with the fully confirmed staging file."""
        staging = open(record.staging_path, "ab")
        with staging:
            staging.flush()
            os.fsync(staging.fileno())
        os.replace(record.staging_path, record.target_path)
        dir_fd = os.open(
            os.path.dirname(os.path.abspath(record.target_path)), os.O_RDONLY
        )
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    @staticmethod
    def _to_status(record) -> TransferStatus:
        manifest = record.manifest
        confirmed_bytes = sum(
            manifest.chunk_length(i) for i in range(record.confirmed_chunks)
        )
        return TransferStatus(
            task_id=record.task_id,
            confirmed_chunks=record.confirmed_chunks,
            total_chunks=manifest.chunk_count,
            confirmed_bytes=confirmed_bytes,
            total_bytes=manifest.total_size,
            complete=record.published,
        )
