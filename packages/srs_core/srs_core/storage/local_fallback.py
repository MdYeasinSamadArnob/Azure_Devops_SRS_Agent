"""Local-disk mirror of every object written to MinIO.

Not a replacement for object storage — it exists purely so a download can
still succeed when MinIO is unreachable. Workers write here best-effort
alongside every MinIO upload; the API falls back to reading from here only
when it detects MinIO is actually unreachable (a connection-level failure),
never as a substitute for a genuinely missing object.
"""

from __future__ import annotations

from pathlib import Path


class LocalFallbackStore:
    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)

    def _path_for(self, bucket: str, object_key: str) -> Path:
        if ".." in object_key.split("/"):
            raise ValueError(f"unsafe object_key: {object_key!r}")
        return self._base_dir / bucket / object_key

    def write(self, bucket: str, object_key: str, data: bytes) -> None:
        path = self._path_for(bucket, object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, bucket: str, object_key: str) -> bytes:
        return self._path_for(bucket, object_key).read_bytes()

    def exists(self, bucket: str, object_key: str) -> bool:
        return self._path_for(bucket, object_key).is_file()
