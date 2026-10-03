"""断点传输库自动化测试。"""

from __future__ import annotations

import hashlib
import os

import pytest

from filexfer import Manifest, SourceMismatchError, TransferLibrary

CHUNK = 256  # 测试用小分块，库默认 64 MiB


def _manifest_for(data: bytes, chunk_size: int = CHUNK) -> Manifest:
    hashes = tuple(
        hashlib.sha256(data[i : i + chunk_size]).hexdigest()
        for i in range(0, len(data), chunk_size)
    )
    return Manifest(total_size=len(data), chunk_hashes=hashes)


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def test_resume_after_wrong_source_version(tmp_path):
    """带非整块尾部的任务中途遇到错误源版本，源修复后继续。"""
    src = str(tmp_path / "src.bin")
    dst = str(tmp_path / "out" / "dst.bin")
    db = str(tmp_path / "state.db")

    rng = os.urandom
    # 2.5 个块：两个整块 + 非整块尾部。
    good = rng(CHUNK * 2 + 100)
    # 错误版本：首块相同，第二块不同，长度一致。
    bad = good[:CHUNK] + rng(CHUNK) + rng(100)
    old_version = b"old-delivered-content"

    _write(src, good)
    manifest = _manifest_for(good)

    lib = TransferLibrary(db)
    task_id = lib.register(src, dst, manifest, chunk_size=CHUNK)
    lib.close()

    # 登记后源被替换为错误版本；目标路径留有上一版成果。
    _write(src, bad)
    _write(dst, old_version)

    # 重新打开库，不再提供清单，直接继续执行。
    lib = TransferLibrary(db)
    with pytest.raises(SourceMismatchError):
        lib.run(task_id)

    # 首块已确认，进度保留；错误块未推进进度。
    status = lib.status(task_id)
    assert status.confirmed_bytes == CHUNK
    assert status.total_bytes == len(good)
    assert not status.completed
    # 发布前旧版内容不变。
    with open(dst, "rb") as f:
        assert f.read() == old_version
    lib.close()

    # 源修复后继续：此前确认的数据保留，不再重传首块。
    _write(src, good)
    lib = TransferLibrary(db)
    assert lib.status(task_id).confirmed_bytes == CHUNK
    lib.run(task_id)

    status = lib.status(task_id)
    assert status.completed
    assert status.confirmed_bytes == len(good)
    with open(dst, "rb") as f:
        assert f.read() == good
    # 暂存文件已随发布移除。
    leftovers = [p for p in os.listdir(os.path.dirname(dst)) if ".part" in p]
    assert leftovers == []
    lib.close()


def test_publish_after_source_removed(tmp_path, monkeypatch):
    """全部数据确认后移走源文件，仍能完成发布并报告完成。"""
    src = str(tmp_path / "src.bin")
    dst = str(tmp_path / "out" / "dst.bin")
    db = str(tmp_path / "state.db")

    data = os.urandom(CHUNK + 40)
    _write(src, data)
    manifest = _manifest_for(data)

    lib = TransferLibrary(db)
    task_id = lib.register(src, dst, manifest, chunk_size=CHUNK)

    # 首次发布失败：全部数据已确认，但目标尚未切换。
    real_replace = os.replace
    with monkeypatch.context() as m:
        m.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        with pytest.raises(OSError):
            lib.run(task_id)
    assert lib.status(task_id).confirmed_bytes == len(data)
    assert not lib.status(task_id).completed
    assert not os.path.exists(dst)
    lib.close()

    # 移走源文件后重开库，发布仍可进行并报告完成。
    os.rename(src, src + ".gone")
    lib = TransferLibrary(db)
    lib.run(task_id)
    status = lib.status(task_id)
    assert status.completed
    assert status.confirmed_bytes == len(data)
    with open(dst, "rb") as f:
        assert f.read() == data
    lib.close()
    assert real_replace is os.replace
