#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify a document after upload: no local image paths remain, URLs resolve.

Two checks:
1. Scan for residual local image references (anything that is not a remote
   URL). A clean uploaded document should have zero.
2. Optionally HEAD each hosted URL to confirm it returns 2xx/3xx. Requires
   network access; skipped by default (pass --verify-urls to enable).

Exit code: 0 if clean, 1 if residual local refs or URL failures (with --strict).

Usage:
    python check_links.py lecture.uploaded.md
    python check_links.py lecture.uploaded.md --verify-urls --strict
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scanner import find_local_path_residue, is_remote_or_special, resolve_local  # noqa: E402


def check_document(path: Path, verify_urls: bool) -> dict:
    """Inspect one document. Returns a report dict.

    Uses find_local_path_residue (not scan_document) so that orphaned
    ``[id]: local-path`` reference definitions are also caught — those would
    otherwise hide a failed/incomplete reference-style rewrite.
    """
    text = path.read_text(encoding="utf-8")
    base_dir = path.parent
    refs = find_local_path_residue(text)

    residuals: list[str] = []
    urls: list[str] = []
    for ref in refs:
        if is_remote_or_special(ref.raw):
            urls.append(ref.raw)
            continue
        # A non-remote ref in an "uploaded" doc means a local path leaked
        # through (either a usage site the upload missed, or an orphaned
        # reference definition). Either way it must be reported.
        resolved = resolve_local(ref.raw, base_dir)
        if resolved is not None:
            residuals.append(ref.raw)
        else:
            # Unresolved local-looking path (missing file) is still suspicious
            # in a doc that was supposed to be fully uploaded.
            residuals.append(ref.raw)

    url_status: dict[str, str] = {}
    if verify_urls:
        for u in urls:
            url_status[u] = _head(u)

    return {
        "file": str(path),
        "residual_local": residuals,
        "hosted_urls": urls,
        "url_status": url_status,
    }


def _head(url: str, timeout: int = 10) -> str:
    """HEAD a URL, return 'ok' / 'HTTP {code}' / an error string."""
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "md-image-uploader-check/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            code = resp.status
            return "ok" if 200 <= code < 400 else f"HTTP {code}"
    except URLError as exc:
        return f"error: {exc.reason}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"error: {exc}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verify an uploaded document has no local image paths.")
    p.add_argument("target", help="Document (or directory) to check.")
    p.add_argument("--verify-urls", action="store_true",
                   help="HEAD each hosted URL to confirm it is reachable (needs network).")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if any residual local path or failed URL is found.")
    args = p.parse_args(argv)

    target = Path(args.target).resolve()
    docs: list[Path] = []
    if target.is_file():
        docs = [target]
    elif target.is_dir():
        for ext in ("*.md", "*.markdown", "*.htm", "*.html"):
            docs.extend(sorted(target.rglob(ext)))
    else:
        print(f"Not found: {target}", file=sys.stderr)
        return 2

    overall_clean = True
    for d in docs:
        report = check_document(d, args.verify_urls)
        residuals = report["residual_local"]
        clean = len(residuals) == 0
        if not clean:
            overall_clean = False
        tag = "✓ clean" if clean else "✗ has local paths"
        print(f"{tag}  {d.name}")
        for r in residuals:
            print(f"    residual: {r}")
        if args.verify_urls:
            bad = [(u, s) for u, s in report["url_status"].items() if s != "ok"]
            if bad:
                overall_clean = False
                for u, s in bad:
                    print(f"    URL fail: {s}  {u}")

    return (1 if args.strict else 0) if not overall_clean else 0


if __name__ == "__main__":
    sys.exit(main())
