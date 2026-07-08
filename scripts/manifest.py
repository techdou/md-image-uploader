"""Manifest: persistent record of uploaded files, keyed by content hash.

Purpose
-------
Without a manifest, every run re-uploads every image — wasting bandwidth,
creating duplicate objects in the bucket, and slowing the publish step.
The manifest maps ``<absolute path>`` to ``{url, hash, size, uploaded_at}``.
Before uploading, we check the manifest:

- If the path is present **and** the current file's hash matches → reuse the
  stored URL. The file content is identical, so the hosted image is too.
- If the path is present but the hash differs → the user edited the image
  locally; re-upload and overwrite the manifest entry.
- If the path is absent → fresh upload.

The manifest is JSON and lives next to the document by default
(``.upload-manifest.json``). It is safe to delete; doing so only means future
runs will re-upload.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ManifestEntry:
    """One uploaded file's record."""

    url: str
    hash: str  # md5 hex of file contents
    size: int  # bytes
    uploaded_at: str  # ISO-8601-ish timestamp


@dataclass
class Manifest:
    """In-memory manifest with load/save and dedup queries.

    The on-disk format is a flat JSON object keyed by absolute path::

        {
          "/abs/path/a.png": {
            "url": "https://cdn.x.com/2026/07/ab12.png",
            "hash": "...",
            "size": 12345,
            "uploaded_at": "2026-07-09T..."
          }
        }

    We key by absolute path (stable across runs in the same project) but
    dedup by content hash (so renaming a file does not cause a re-upload).
    """

    path: Path
    entries: dict[str, ManifestEntry] = field(default_factory=dict)

    # ---------------------------------------------------------------- load/save

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        """Read the manifest file, or return an empty one if it does not exist.

        A corrupt manifest is treated as empty with a warning rather than
        crashing the run — losing dedup is preferable to losing the upload.
        """
        m = cls(path=path)
        if not path.is_file():
            return m
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # A corrupt manifest means dedup is lost; warn loudly so the user
            # knows the next run may re-upload everything.
            import sys
            print(
                f"Warning: manifest at {path} is unreadable ({exc}); "
                f"starting fresh. Deduplication is disabled until a valid "
                f"manifest is written.",
                file=sys.stderr,
            )
            return m
        for k, v in data.items():
            try:
                m.entries[k] = ManifestEntry(
                    url=v["url"],
                    hash=v["hash"],
                    size=int(v["size"]),
                    uploaded_at=v["uploaded_at"],
                )
            except (KeyError, TypeError, ValueError):
                continue  # skip malformed entries
        return m

    def save(self) -> None:
        """Atomically write the manifest as pretty JSON.

        Writes to a temp file then renames, so a crash mid-write cannot leave
        a half-written manifest that would fail to parse next run.
        """
        payload: dict[str, Any] = {
            k: asdict(v) for k, v in sorted(self.entries.items())
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- queries

    def lookup(self, local_path: str, current_hash: str) -> str | None:
        """Return a reusable URL if the file is unchanged, else None.

        "Unchanged" means the path is known AND the stored hash equals
        *current_hash*. A hash mismatch (file edited locally) invalidates
        the cached URL and forces a re-upload.
        """
        entry = self.entries.get(local_path)
        if entry is None:
            return None
        if entry.hash != current_hash:
            return None
        return entry.url

    def url_exists(self, url: str) -> str | None:
        """Reverse lookup: which local path produced *url*?

        Used to skip re-uploading when the same content was already pushed
        under a different local filename. Returns the path or None.
        """
        for lp, entry in self.entries.items():
            if entry.url == url:
                return lp
        return None

    def record(self, local_path: str, url: str, file_hash: str, size: int) -> None:
        """Add or overwrite an entry."""
        self.entries[local_path] = ManifestEntry(
            url=url,
            hash=file_hash,
            size=size,
            uploaded_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )


# ----------------------------------------------------------- file hashing

def file_hash(local_path: str, algorithm: str = "md5") -> str:
    """Hash a file's contents, streaming to avoid loading large files into RAM.

    MD5 is used by default because image dedup is not a security context —
    speed and a short hash (for the remote key) matter more than collision
    resistance. Switch to sha256 with the *algorithm* arg if you need it.
    """
    h = hashlib.new(algorithm)
    with open(local_path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_size(local_path: str) -> int:
    """Return file size in bytes, or 0 if the path does not exist."""
    try:
        return os.path.getsize(local_path)
    except OSError:
        return 0
