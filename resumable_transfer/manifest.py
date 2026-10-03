"""Trusted content manifest types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

CHUNK_SIZE = 64 * 1024 * 1024  # 64 MiB


@dataclass(frozen=True)
class Manifest:
    """Trusted description of the content to deliver.

    ``digests`` holds the SHA-256 of each consecutive 64 MiB chunk; the last
    chunk is hashed over its actual (possibly shorter) length.
    """

    total_size: int
    digests: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if self.total_size < 0:
            raise ValueError("total_size must be non-negative")
        expected_chunks = (self.total_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        if self.total_size == 0:
            expected_chunks = 0
        if len(self.digests) != expected_chunks:
            raise ValueError(
                f"manifest has {len(self.digests)} chunk digests, "
                f"expected {expected_chunks} for size {self.total_size}"
            )
        for digest in self.digests:
            if len(digest) != 32:
                raise ValueError("each digest must be 32 bytes (SHA-256)")

    @property
    def chunk_count(self) -> int:
        return len(self.digests)

    def chunk_length(self, index: int) -> int:
        """Actual byte length of chunk ``index`` (last chunk may be short)."""
        if index < 0 or index >= self.chunk_count:
            raise IndexError(index)
        if index == self.chunk_count - 1:
            remainder = self.total_size - CHUNK_SIZE * index
            return remainder
        return CHUNK_SIZE

    def identity(self) -> bytes:
        """Stable digest binding a task to this exact manifest."""
        hasher = hashlib.sha256()
        hasher.update(b"resumable-transfer-manifest-v1\0")
        hasher.update(self.total_size.to_bytes(8, "big"))
        for digest in self.digests:
            hasher.update(digest)
        return hasher.digest()

    @classmethod
    def from_digests(cls, total_size: int, digests: Sequence[bytes]) -> "Manifest":
        return cls(total_size=total_size, digests=tuple(digests))
