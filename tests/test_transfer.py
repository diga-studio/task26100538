import hashlib
import os

import pytest

from resumable_transfer import (
    CHUNK_SIZE,
    Manifest,
    SourceChangedError,
    TransferEngine,
)


def make_manifest(data: bytes) -> Manifest:
    digests = tuple(
        hashlib.sha256(data[offset:offset + CHUNK_SIZE]).digest()
        for offset in range(0, len(data), CHUNK_SIZE)
    )
    return Manifest(total_size=len(data), digests=digests)


@pytest.fixture()
def workspace(tmp_path):
    return {
        "db": tmp_path / "state.db",
        "src": tmp_path / "source.bin",
        "dst": tmp_path / "delivered" / "image.bin",
    }


def test_resume_after_bad_source_version_keeps_confirmed_progress(workspace):
    # Content with a non-integral tail chunk: 1 full 64 MiB chunk + tail.
    tail = b"tail-bytes-" * 4097
    good = os.urandom(CHUNK_SIZE) + tail
    # Wrong version: identical first chunk, corrupted tail chunk.
    bad = good[:CHUNK_SIZE] + b"\x00" * len(tail)
    old_version = b"previous-delivered-version"

    workspace["dst"].parent.mkdir(parents=True)
    workspace["dst"].write_bytes(old_version)
    workspace["src"].write_bytes(bad)
    manifest = make_manifest(good)

    engine = TransferEngine(workspace["db"])
    task_id = engine.register(workspace["src"], workspace["dst"], manifest)

    # First run: chunk 0 verifies and is confirmed, tail chunk mismatches.
    with pytest.raises(SourceChangedError):
        engine.resume(task_id)
    engine.close()

    # Reopen the library: no manifest needed, confirmed progress retained.
    engine = TransferEngine(workspace["db"])
    status = engine.status(task_id)
    assert status.confirmed_chunks == 1
    assert status.confirmed_bytes == CHUNK_SIZE
    assert not status.complete
    # Old delivered version must be untouched before publish.
    assert workspace["dst"].read_bytes() == old_version

    # Source fixed to the correct content; resume completes the delivery.
    workspace["src"].write_bytes(good)
    status = engine.resume(task_id)
    assert status.complete
    assert status.confirmed_chunks == 2
    assert status.confirmed_bytes == len(good)
    assert workspace["dst"].read_bytes() == good
    engine.close()


def test_publish_after_source_removed(workspace):
    data = os.urandom(CHUNK_SIZE // 2 + 7)
    workspace["dst"].parent.mkdir(parents=True)
    workspace["src"].write_bytes(data)
    manifest = make_manifest(data)

    engine = TransferEngine(workspace["db"])
    task_id = engine.register(workspace["src"], workspace["dst"], manifest)

    # Simulate an interruption after all data is confirmed but before publish.
    original_publish = TransferEngine.__dict__["_publish"]

    def failing_publish(record):
        raise RuntimeError("simulated crash before publish")

    TransferEngine._publish = staticmethod(failing_publish)
    try:
        with pytest.raises(RuntimeError):
            engine.resume(task_id)
    finally:
        TransferEngine._publish = original_publish
    engine.close()

    # All data confirmed; source is moved away before the next run.
    engine = TransferEngine(workspace["db"])
    assert engine.status(task_id).confirmed_chunks == 1
    assert not engine.status(task_id).complete
    os.rename(workspace["src"], workspace["src"].with_suffix(".gone"))

    status = engine.resume(task_id)
    assert status.complete
    assert workspace["dst"].read_bytes() == data
    assert engine.status(task_id).complete
    engine.close()
