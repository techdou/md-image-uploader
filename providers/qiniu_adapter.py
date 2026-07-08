"""Qiniu uploader — kept as an optional adapter.

Qiniu's Python SDK (``qiniu``) is not S3-compatible, so it needs its own
adapter. It is imported lazily: the rest of the skill works without ``qiniu``
installed, and this module only loads when the user picks ``--provider qiniu``.

Testing note: this adapter is provided for completeness and is NOT covered by
the smoke test suite (it requires a real Qiniu account). The interface mirrors
S3Uploader so the pipeline treats both identically.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .base import BaseUploader, UploaderError


class QiniuUploader(BaseUploader):
    """Adapter for Qiniu Object Storage (七牛云).

    Two Qiniu-specific quirks handled here:

    1. Qiniu returns a *hash* on upload but the public URL is built from the
       bucket's bound domain + the key you supplied. We trust the caller's
       ``remote_key`` for the URL.
    2. Keys with non-ASCII chars must be URL-encoded for the link to work in
       browsers; ``_encode_key`` handles that.
    """

    provider_id = "qiniu"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.access_key = config.get("access_key") or os.environ.get("QINIU_ACCESS_KEY")
        self.secret_key = config.get("secret_key") or os.environ.get("QINIU_SECRET_KEY")
        self.bucket = config.get("bucket") or os.environ.get("QINIU_BUCKET")
        # The domain bound to the bucket, e.g. https://cdn.example.com
        self.domain = (
            config.get("domain")
            or config.get("public_url")
            or os.environ.get("QINIU_DOMAIN")
        )
        # Whether the bucket is public (no download token needed). Default True
        # for the image-hosting use case.
        self.is_public = bool(config.get("public", True))
        self._auth = None

        missing = [
            name
            for name, val in [
                ("access_key", self.access_key),
                ("secret_key", self.secret_key),
                ("bucket", self.bucket),
                ("domain", self.domain),
            ]
            if not val
        ]
        if missing:
            raise UploaderError(
                "Qiniu provider config is missing required field(s): "
                + ", ".join(missing)
                + ". Set them in the config file or QINIU_* env vars."
            )

    def _ensure_auth(self):  # pragma: no cover - needs qiniu
        if self._auth is not None:
            return self._auth
        try:
            from qiniu import Auth  # type: ignore
        except ImportError as exc:
            raise UploaderError(
                "qiniu SDK is required for the qiniu provider. "
                "Install it with: pip install qiniu"
            ) from exc
        self._auth = Auth(self.access_key, self.secret_key)
        return self._auth

    def upload(self, local_path: str, remote_key: str) -> str:  # pragma: no cover
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)

        auth = self._ensure_auth()
        try:
            from qiniu import put_file  # type: ignore
        except ImportError as exc:
            raise UploaderError("qiniu SDK not installed") from exc

        token = auth.upload_token(self.bucket, remote_key, 3600)
        # put_file returns (ret, info); ret contains the stored key/hash on ok.
        ret, info = put_file(token, remote_key, local_path)
        if info.status_code != 200:  # type: ignore[attr-defined]
            raise UploaderError(
                f"Qiniu upload failed ({info.status_code}): {info.text_body}"
            )

        return self._url_for(remote_key)

    def _url_for(self, remote_key: str) -> str:
        base = (self.domain or "").rstrip("/")
        return f"{base}/{self._encode_key(remote_key)}"

    @staticmethod
    def _encode_key(key: str) -> str:
        """URL-encode each path segment, preserving slashes.

        A key like ``2026/07/截图.png`` becomes ``2026/07/%E6%88%AA%E5%9B%BE.png``
        so it is safe to embed in Markdown/HTML.
        """
        from urllib.parse import quote

        return "/".join(quote(seg) for seg in key.split("/"))


# A trivial regex guard so future maintainers see which chars Qiniu keys
# disallow (the SDK rejects these). Kept here as documentation, not enforced.
_QINIU_BAD_CHARS = re.compile(r"[?#:]")
