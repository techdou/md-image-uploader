"""S3-compatible uploader — covers Cloudflare R2, Alibaba OSS, Tencent COS,
MinIO, Backblaze B2, and any service that speaks the S3 API.

boto3 is imported lazily so the rest of the skill (scanning, dry-run,
replacement) works on a machine with no SDK installed.
"""

from __future__ import annotations

import os
from typing import Any

from .base import BaseUploader, UploaderError


class S3Uploader(BaseUploader):
    """One adapter for every S3-compatible host.

    The differences between R2/OSS/COS/MinIO/B2 boil down to three config
    values, so a single class handles them all:

    - ``endpoint``: the S3 API hostname (e.g. ``<id>.r2.cloudflarestorage.com``)
    - ``region``: R2 and B2 accept ``auto``; OSS/COS need a real region.
    - ``public_url``: the CDN/custom domain prepended to the object key to form
      the returned URL. Falls back to the endpoint itself when omitted.

    Attributes are read once in ``__init__`` so a misconfiguration fails fast
    before the first byte is uploaded, not midway through a batch.
    """

    provider_id = "s3"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        # Credentials are never logged. Read them up front so a missing value
        # surfaces as a clear UploaderError before boto3 is even touched.
        self.access_key_id = config.get("access_key_id") or _env(
            config, "ACCESS_KEY_ID"
        )
        self.secret_access_key = config.get("secret_access_key") or _env(
            config, "SECRET_ACCESS_KEY"
        )
        self.bucket = config.get("bucket") or _env(config, "BUCKET")
        self.endpoint = config.get("endpoint") or _env(config, "ENDPOINT")
        # R2 and B2 ignore region but still want a value; ``auto`` is the
        # documented sentinel for R2.
        self.region = config.get("region") or "auto"
        # public_url is the URL a browser hits — the CDN domain bound to the
        # bucket. Without it we fall back to the endpoint (works for public
        # buckets, but R2 requires the r2.dev subdomain or a custom domain).
        self.public_url = (
            config.get("public_url") or config.get("custom_url") or _env(config, "PUBLIC_URL")
        )
        # path-style addressing is required by R2 and MinIO; OSS/COS prefer it
        # too when a custom endpoint is used.
        self.path_style = bool(config.get("path_style", True))
        # Optional ACL; R2 ignores it (uses bucket-level policy), but OSS/COS
        # may want ``public-read``.
        self.acl = config.get("acl")
        self._client = None  # lazy boto3 client

        missing = [
            name
            for name, val in [
                ("access_key_id", self.access_key_id),
                ("secret_access_key", self.secret_access_key),
                ("bucket", self.bucket),
                ("endpoint", self.endpoint),
            ]
            if not val
        ]
        if missing:
            raise UploaderError(
                "S3 provider config is missing required field(s): "
                + ", ".join(missing)
                + ". Fill them in the config file or the matching env vars."
            )

    # ------------------------------------------------------------------ client

    def _ensure_client(self):  # pragma: no cover - needs boto3 + network
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
            from botocore.client import Config  # type: ignore
        except ImportError as exc:  # pragma: no cover - env dependent
            raise UploaderError(
                "boto3 is required for S3-compatible providers. "
                "Install it with: pip install boto3"
            ) from exc

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=Config(s3={"addressing_style": "path" if self.path_style else "auto"}),
        )
        return self._client

    # ------------------------------------------------------------------- upload

    def upload(self, local_path: str, remote_key: str) -> str:  # pragma: no cover
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)

        client = self._ensure_client()
        extra: dict[str, Any] = {}
        if self.acl:
            extra["ACL"] = self.acl
        try:
            client.upload_file(local_path, self.bucket, remote_key, ExtraArgs=extra)
        except Exception as exc:  # boto3 raises many subclasses; collapse to one
            raise UploaderError(
                f"S3 upload failed for {os.path.basename(local_path)} -> {remote_key}: {exc}"
            ) from exc

        return self._url_for(remote_key)

    def _url_for(self, remote_key: str) -> str:
        """Build the public URL for an object key.

        Preference order: explicit public_url/custom domain > endpoint.
        Keys are joined with a single slash; leading slashes on public_url are
        stripped so ``https://cdn.x.com/`` + ``a/b.png`` stays clean.
        """
        base = (self.public_url or self.endpoint or "").rstrip("/")
        return f"{base}/{remote_key.lstrip('/')}"


def _env(config: dict[str, Any], suffix: str) -> str | None:
    """Look up an env var using the provider's name as a prefix.

    For a config ``{"name": "r2"}`` the key ``access_key_id`` maps to
    ``R2_ACCESS_KEY_ID``. Uppercase provider name + field name.
    """
    name = (config.get("name") or "").upper()
    if not name:
        return None
    return os.environ.get(f"{name}_{suffix}")
