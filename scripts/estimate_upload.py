#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estimate how many local images a document references and their total size.

Does NOT upload anything and does NOT need credentials. Useful as a pre-flight
check before a real upload run, especially on a directory with many files.

Usage:
    python estimate_upload.py path/to/lecture.md
    python estimate_upload.py path/to/docs/ --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scanner import is_remote_or_special, resolve_local, scan_document  # noqa: E402


def estimate(path: Path) -> dict:
    """Return a summary dict for one document."""
    text = path.read_text(encoding="utf-8")
    base_dir = path.parent
    refs = scan_document(text, doc_type="auto")

    local_files: dict[str, int] = {}  # resolved path -> bytes
    remote = 0
    missing: list[str] = []

    for ref in refs:
        if is_remote_or_special(ref.raw):
            remote += 1
            continue
        resolved = resolve_local(ref.raw, base_dir)
        if resolved is None:
            missing.append(ref.raw)
            continue
        key = str(resolved)
        if key not in local_files:
            try:
                local_files[key] = os.path.getsize(resolved)
            except OSError:
                local_files[key] = 0

    total_bytes = sum(local_files.values())
    return {
        "file": str(path),
        "local_images": len(local_files),
        "remote_images": remote,
        "missing": missing,
        "total_size_bytes": total_bytes,
        "total_size_human": _human(total_bytes),
    }


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Estimate local image references without uploading.")
    p.add_argument("target", help="File or directory to scan.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Output JSON.")
    args = p.parse_args(argv)

    target = Path(args.target).resolve()
    if not target.exists():
        print(f"Not found: {target}", file=sys.stderr)
        return 2

    docs: list[Path] = []
    if target.is_file():
        docs = [target]
    else:
        for ext in ("*.md", "*.markdown", "*.htm", "*.html"):
            docs.extend(sorted(target.rglob(ext)))

    summaries = [estimate(d) for d in docs]
    if args.as_json:
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        return 0

    total_imgs = sum(s["local_images"] for s in summaries)
    total_bytes = sum(s["total_size_bytes"] for s in summaries)
    for s in summaries:
        print(f"\n📄 {os.path.relpath(s['file'])}")
        print(f"   {s['local_images']} local image(s), {s['remote_images']} remote, "
              f"{len(s['missing'])} missing")
        print(f"   size: {s['total_size_human']}")
        for m in s["missing"]:
            print(f"   ⚠️  missing: {m}")
    print(f"\n{'—' * 50}")
    print(f"TOTAL: {total_imgs} image(s), {_human(total_bytes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
