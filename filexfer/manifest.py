"""可信内容清单与任务身份。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MiB


@dataclass(frozen=True)
class Manifest:
    """登记时由调用方提供的可信内容清单。

    total_size: 文件总长度（字节）。
    chunk_hashes: 按 chunk_size 顺序分块后各块的 SHA-256（十六进制小写），
                  末块按实际长度计算。
    """

    total_size: int
    chunk_hashes: tuple[str, ...]

    def task_id(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
        """任务身份，仅由清单内容决定。"""
        h = hashlib.sha256()
        h.update(b"filexfer-task-v1\0")
        h.update(str(chunk_size).encode("ascii"))
        h.update(b"\0")
        h.update(str(self.total_size).encode("ascii"))
        for digest in self.chunk_hashes:
            h.update(b"\0")
            h.update(digest.encode("ascii"))
        return h.hexdigest()
