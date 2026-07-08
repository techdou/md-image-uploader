"""Image hosting provider adapters.

All providers implement the same `upload(local_path, remote_key) -> url` contract
so the core pipeline is provider-agnostic. Import `get_uploader` to obtain the
right adapter from a config block.
"""

from __future__ import annotations

from .base import BaseUploader, UploaderError, get_uploader

__all__ = ["BaseUploader", "UploaderError", "get_uploader"]
