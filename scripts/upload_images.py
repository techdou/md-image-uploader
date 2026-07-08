#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch-upload local images referenced by Markdown/HTML documents to an image
host (Cloudflare R2, Alibaba OSS, Tencent COS, Qiniu, MinIO, Backblaze B2)
and rewrite the local paths in the document to the hosted URLs.

Default behaviour
-----------------
- Reads the input file, finds every local image reference, uploads each to
  the configured provider, and writes ``<name>.uploaded.<ext>`` next to it.
- The original file is never modified unless ``--in-place`` is passed.
- A manifest (``.upload-manifest.json``) records each upload so re-runs skip
  files whose content has not changed — no duplicate uploads, no wasted quota.
- Credentials are read from ``~/.md-image-uploader.json`` or the matching
  environment variables. They are NEVER written to stdout or logs.

Designed for: publishing Markdown lectures/articles whose images live in a
local ``assets/`` folder, and migrating finished documents to a CDN-backed
图床 before posting to a blog, 公众号, or 知乎.

Core dependency: Python standard library + boto3 (for S3-compatible providers).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Ensure this script's own directory and the skill root (for providers/) are
# importable when the script is run directly from any working directory.
_SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_ROOT / "scripts"))
sys.path.insert(0, str(_SKILL_ROOT))

# Force UTF-8 stdout on Windows so progress prints do not crash on CJK paths.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from manifest import Manifest, file_hash, file_size  # noqa: E402
from providers import UploaderError, get_uploader  # noqa: E402
from replacer import apply_replacements  # noqa: E402
from scanner import DEFAULT_IMAGE_EXTS, ImageRef, resolve_local, scan_document  # noqa: E402

DEFAULT_CONFIG_PATH = Path.home() / ".md-image-uploader.json"


# ----------------------------------------------------------- result records

@dataclass
class FileResult:
    """Per-document outcome, serialized into the JSON report."""

    input: str
    output: str | None = None
    uploaded: int = 0
    reused: int = 0
    failed: int = 0
    skipped_remote: int = 0
    missing: int = 0
    details: list[dict] = field(default_factory=list)


@dataclass
class RunReport:
    """Aggregate outcome across all input documents."""

    started_at: str
    provider: str
    files: list[FileResult] = field(default_factory=list)

    def totals(self) -> dict[str, int]:
        agg = {"uploaded": 0, "reused": 0, "failed": 0, "skipped_remote": 0, "missing": 0}
        for fr in self.files:
            for k in agg:
                agg[k] += getattr(fr, k)
        return agg


# ----------------------------------------------------------- config loading

def load_provider_config(provider: str, config_path: Path | None) -> dict:
    """Resolve provider config from file or environment.

    Order: explicit --config file > default ~/.md-image-uploader.json.
    Inside the file, the block under ``providers[provider]`` is returned.
    If the file is missing, fall back to ``<PROVIDER>_`` env vars (handled
    inside S3Uploader/QiniuUploader, so we return a minimal block here).
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SystemExit(f"Could not read config {path}: {exc}")
        providers = data.get("providers", {})
        if provider not in providers:
            raise SystemExit(
                f"Provider {provider!r} not found in {path}. "
                f"Available: {', '.join(providers) or '(none)'}."
            )
        cfg = dict(providers[provider])
        cfg.setdefault("name", provider)
        # For S3 family, set type if the user only wrote an alias.
        if "type" not in cfg:
            cfg["type"] = provider
        return cfg

    # No config file: let the adapter pull env vars.
    return {"type": provider, "name": provider}


# ----------------------------------------------------------- key naming

def build_remote_key(local_path: str, hash_hex: str) -> str:
    """Construct the object key: ``YYYY/MM/<hash12>.<ext>``.

    Using a content hash means identical images dedup naturally on the bucket
    side (same key), and the year/month prefix keeps listings tidy. We take
    12 hex chars (48 bits) of the MD5 — collision space is in the hundreds of
    thousands before birthday-paradox risk becomes non-negligible, which is
    ample for a personal image library.
    """
    now = _dt.datetime.now()
    _, ext = os.path.splitext(local_path)
    return f"{now:%Y/%m}/{hash_hex[:12]}{ext.lower()}"


# ----------------------------------------------------------- core per-file

def process_document(
    doc_path: Path,
    uploader,
    manifest: Manifest,
    args: argparse.Namespace,
) -> FileResult:
    """Scan, upload, and rewrite a single document. Never raises on per-image
    failure — those are recorded in the result for batch resilience.
    """
    text = doc_path.read_text(encoding="utf-8")
    base_dir = doc_path.parent
    ext_filter = parse_filter(args.include_ext)

    refs = scan_document(text, doc_type="auto")
    result = FileResult(input=str(doc_path))

    url_map: dict[str, str] = {}
    missing: list[str] = []

    for ref in refs:
        # Filter by extension if the user constrained it.
        if ext_filter:
            _, e = os.path.splitext(ref.clean_path)
            if e.lower() not in ext_filter:
                continue

        # Resolve to an absolute local file.
        resolved = resolve_local(ref.raw, base_dir)
        if resolved is None:
            # Could be a remote URL we should skip, or a missing local file.
            from scanner import is_remote_or_special

            if is_remote_or_special(ref.raw):
                result.skipped_remote += 1
                result.details.append({"raw": ref.raw, "status": "remote"})
            else:
                result.missing += 1
                result.details.append({"raw": ref.raw, "status": "missing"})
                missing.append(ref.raw)
            continue

        # Dry run: report only, no upload, no rewrite.
        if args.dry_run:
            size = file_size(str(resolved))
            result.uploaded += 1  # counted as "would upload"
            result.details.append(
                {
                    "raw": ref.raw,
                    "resolved": str(resolved),
                    "bytes": size,
                    "status": "dry_run",
                }
            )
            continue

        h = file_hash(str(resolved))
        size = file_size(str(resolved))

        # Dedup via manifest.
        if args.skip_uploaded:
            cached = manifest.lookup(str(resolved), h)
            if cached:
                url_map[ref.raw] = cached
                result.reused += 1
                result.details.append(
                    {"raw": ref.raw, "resolved": str(resolved), "url": cached, "status": "reused"}
                )
                continue

        # Upload with retry.
        key = build_remote_key(str(resolved), h)
        url, status = upload_with_retry(uploader, str(resolved), key, retries=args.retries)
        if url is None:
            result.failed += 1
            result.details.append(
                {
                    "raw": ref.raw,
                    "resolved": str(resolved),
                    "error": status,
                    "status": "failed",
                }
            )
            continue

        manifest.record(str(resolved), url, h, size)
        url_map[ref.raw] = url
        result.uploaded += 1
        result.details.append(
            {"raw": ref.raw, "resolved": str(resolved), "url": url, "status": "uploaded"}
        )

    # Rewrite (skip in dry-run).
    if args.dry_run:
        result.output = None
        return result

    new_text, replaced, unchanged = apply_replacements(text, refs, url_map)
    out_path = doc_path if args.in_place else sibling_uploaded(doc_path)
    out_path.write_text(new_text, encoding="utf-8")
    result.output = str(out_path)
    return result


def upload_with_retry(uploader, local_path: str, key: str, retries: int):
    """Call uploader.upload with exponential backoff.

    Returns (url, None) on success or (None, error_message) after all retries.
    """
    last_err = ""
    for attempt in range(max(1, retries)):
        try:
            url = uploader.upload(local_path, key)
            return url, None
        except FileNotFoundError as exc:
            # No point retrying a vanished file.
            return None, f"file not found: {exc}"
        except UploaderError as exc:
            last_err = str(exc)
            if attempt < retries - 1:
                time.sleep(0.5 * (2 ** attempt))
        except Exception as exc:  # pragma: no cover - defensive
            last_err = f"unexpected: {exc}"
            if attempt < retries - 1:
                time.sleep(0.5 * (2 ** attempt))
    return None, last_err


# ----------------------------------------------------------- helpers

def sibling_uploaded(path: Path) -> Path:
    """``lecture.md`` -> ``lecture.uploaded.md``; ``notes.html`` -> ``notes.uploaded.html``."""
    return path.with_name(f"{path.stem}.uploaded{path.suffix}")


def iter_documents(target: Path) -> list[Path]:
    """Expand a file or directory into a list of .md/.html files."""
    if target.is_file():
        return [target]
    if target.is_dir():
        out: list[Path] = []
        for ext in ("*.md", "*.markdown", "*.htm", "*.html"):
            out.extend(sorted(target.rglob(ext)))
        return out
    raise SystemExit(f"Target not found: {target}")


def parse_filter(raw: str | None) -> set[str]:
    if not raw:
        return set()
    values: set[str] = set()
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        values.add(item if item.startswith(".") else f".{item}")
    return values


def print_human_report(report: RunReport, dry_run: bool) -> None:
    verb = "would upload" if dry_run else "uploaded"
    print(f"\n{'=' * 60}")
    print(f"Provider: {report.provider}   |   mode: {'DRY RUN' if dry_run else 'live'}")
    print(f"{'=' * 60}")
    for fr in report.files:
        rel = os.path.relpath(fr.input)
        out = os.path.relpath(fr.output) if fr.output else "(not written)"
        print(f"\n📄 {rel}")
        print(f"   -> {out}")
        print(f"   {verb}: {fr.uploaded}   reused: {fr.reused}   failed: {fr.failed}   "
              f"missing: {fr.missing}   remote(skipped): {fr.skipped_remote}")
        for d in fr.details:
            if d.get("status") == "failed":
                print(f"   ❌ {d.get('raw')}: {d.get('error')}")
            elif d.get("status") == "missing":
                print(f"   ⚠️  missing: {d.get('raw')}")
    totals = report.totals()
    print(f"\n{'—' * 60}")
    print(f"TOTAL  {verb}: {totals['uploaded']}   reused: {totals['reused']}   "
          f"failed: {totals['failed']}   missing: {totals['missing']}")


# ----------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="upload_images.py",
        description="Batch-upload local images in Markdown/HTML to an image host and rewrite links.",
    )
    p.add_argument("target", help="Path to a .md/.html file or a directory to scan recursively.")
    p.add_argument("--provider", default="r2",
                   help="Image host key in the config file (default: r2). "
                        "S3-compatible: r2, oss, cos, minio, b2. Qiniu: qiniu.")
    p.add_argument("--config", default=None,
                   help=f"Config JSON path (default: {DEFAULT_CONFIG_PATH}).")
    p.add_argument("--in-place", action="store_true",
                   help="Modify the input file directly. Default: write <name>.uploaded.<ext>.")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan and report only; upload nothing, write nothing.")
    p.add_argument("--manifest", default=None,
                   help="Manifest path (default: .upload-manifest.json beside the doc).")
    p.add_argument("--skip-uploaded", action=argparse.BooleanOptionalAction, default=True,
                   help="Reuse URLs from the manifest when the file is unchanged (default: on).")
    p.add_argument("--include-ext", default=None,
                   help="Comma-separated extensions to upload, e.g. .png,.jpg. Default: all image types.")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if any upload fails (default: exit 0 unless fatal).")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Emit a machine-readable JSON report to stdout instead of human text.")
    p.add_argument("--retries", type=int, default=3,
                   help="Upload attempts per file on transient failure (default: 3).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"Target not found: {target}", file=sys.stderr)
        return 2

    docs = iter_documents(target)
    if not docs:
        print(f"No .md/.html files found under {target}", file=sys.stderr)
        return 2

    # Dry run needs no credentials and no uploader.
    uploader = None
    if not args.dry_run:
        provider_cfg = load_provider_config(args.provider, Path(args.config) if args.config else None)
        try:
            uploader = get_uploader(provider_cfg)
        except UploaderError as exc:
            print(f"Provider setup failed: {exc}", file=sys.stderr)
            return 2

    report = RunReport(started_at=time.strftime("%Y-%m-%dT%H:%M:%S"), provider=args.provider)

    for doc in docs:
        mpath = Path(args.manifest) if args.manifest else doc.parent / ".upload-manifest.json"
        manifest = Manifest.load(mpath)
        try:
            fr = process_document(doc, uploader, manifest, args)
        except Exception as exc:  # pragma: no cover - defensive per-doc guard
            fr = FileResult(input=str(doc), output=None, failed=1)
            fr.details.append({"status": "fatal", "error": str(exc)})
        report.files.append(fr)
        # Persist manifest per doc so a crash mid-batch keeps prior progress.
        if not args.dry_run:
            manifest.save()

    if args.as_json:
        print(json.dumps(
            {"started_at": report.started_at, "provider": report.provider,
             "totals": report.totals(),
             "files": [asdict(fr) for fr in report.files]},
            ensure_ascii=False, indent=2,
        ))
    else:
        print_human_report(report, dry_run=args.dry_run)

    totals = report.totals()
    if args.strict and totals["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
