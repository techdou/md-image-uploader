"""Abstract base for image hosting providers.

A provider knows only one thing: how to push a local file to a remote bucket
and hand back a publicly reachable URL. Naming (remote_key) is decided by the
caller — providers never invent names. This keeps the dedup/hash policy in a
single place instead of being scattered across adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class UploaderError(RuntimeError):
    """Raised when a provider cannot complete an upload.

    The pipeline catches this per-file so one failure does not abort a batch.
    """


class BaseUploader(ABC):
    """Contract every image host adapter must satisfy."""

    #: Short identifier used in config and CLI --provider, e.g. "r2", "oss".
    provider_id: str = "base"

    @abstractmethod
    def upload(self, local_path: str, remote_key: str) -> str:
        """Upload *local_path* under *remote_key* and return its public URL.

        Args:
            local_path: Absolute path to a real local file.
            remote_key: Object key with no leading slash, e.g.
                ``2026/07/ab12cd34.png``. Always provided by the caller.

        Returns:
            The fully qualified URL a browser can fetch (after applying any
            custom domain / CDN prefix the provider is configured with).

        Raises:
            UploaderError: On any auth, network, or server failure.
            FileNotFoundError: If *local_path* does not exist.
        """
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release any underlying client/session. Override if needed."""


def get_uploader(provider_config: dict[str, Any]) -> BaseUploader:
    """Factory: pick the right adapter from a provider config block.

    A config block looks like::

        {"type": "s3", "endpoint": "...", "access_key_id": "...", ...}
        {"type": "qiniu", "access_key": "...", "secret_key": "...", ...}

    This indirection means the pipeline works against ``BaseUploader`` and
    never imports boto3 or qiniu directly — they stay optional.
    """
    ptype = (provider_config.get("type") or "").lower()
    if ptype in ("s3", "r2", "oss", "cos", "minio", "b2"):
        # Defer the import so boto3 is only required when actually used.
        from .s3_compat import S3Uploader

        return S3Uploader(provider_config)
    if ptype == "qiniu":
        from .qiniu_adapter import QiniuUploader

        return QiniuUploader(provider_config)
    raise UploaderError(
        f"Unknown provider type {ptype!r}. Expected one of: "
        "s3, r2, oss, cos, minio, b2, qiniu."
    )
