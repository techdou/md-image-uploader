#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactively build or edit ~/.md-image-uploader.json.

Walks the user through adding a provider (R2 by default) and writes a config
file the uploader reads. Credentials are written with restrictive permissions
on POSIX. Never prints the secret values back after entry.

Usage:
    python config_provider.py                    # add/edit the default profile
    python config_provider.py --provider oss     # add an OSS profile
    python config_provider.py --list             # show provider names only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_PATH = Path.home() / ".md-image-uploader.json"

# Each provider's required fields and a human prompt. Values are read with
# getpass when the field name contains "secret" or "key" (second tuple element).
PROVIDER_FIELDS = {
    "r2": [
        ("access_key_id", "R2 Access Key ID (from dashboard > Manage R2 API Tokens): ", False),
        ("secret_access_key", "R2 Secret Access Key: ", True),
        ("bucket", "Bucket name: ", False),
        ("endpoint", "S3 endpoint (https://<account-id>.r2.cloudflarestorage.com): ", False),
        ("public_url", "Public URL prefix (https://cdn.example.com or *.r2.dev): ", False),
    ],
    "oss": [
        ("access_key_id", "OSS AccessKey ID: ", False),
        ("secret_access_key", "OSS AccessKey Secret: ", True),
        ("bucket", "Bucket name: ", False),
        ("endpoint", "Endpoint (https://oss-cn-hangzhou.aliyuncs.com): ", False),
        ("public_url", "Public URL prefix (bound CDN domain): ", False),
    ],
    "cos": [
        ("access_key_id", "COS SecretId: ", False),
        ("secret_access_key", "COS SecretKey: ", True),
        ("bucket", "Bucket name (e.g. mybucket-1250000000): ", False),
        ("endpoint", "Endpoint (https://cos.ap-guangzhou.myqcloud.com): ", False),
        ("public_url", "Public URL prefix: ", False),
    ],
    "qiniu": [
        ("access_key", "Qiniu Access Key: ", False),
        ("secret_key", "Qiniu Secret Key: ", True),
        ("bucket", "Bucket name: ", False),
        ("domain", "Bound domain (https://cdn.example.com): ", False),
    ],
    "minio": [
        ("access_key_id", "MinIO access key: ", False),
        ("secret_access_key", "MinIO secret key: ", True),
        ("bucket", "Bucket name: ", False),
        ("endpoint", "Endpoint (http://localhost:9000): ", False),
        ("public_url", "Public URL prefix: ", False),
    ],
    "b2": [
        ("access_key_id", "B2 keyID: ", False),
        ("secret_access_key", "B2 applicationKey: ", True),
        ("bucket", "Bucket name: ", False),
        ("endpoint", "Endpoint (https://s3.<region>.backblazeb2.com): ", False),
        ("public_url", "Public URL prefix: ", False),
    ],
}


def load_existing(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save(config: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    # Restrict file permissions so other users cannot read credentials.
    _restrict_perms(path)


def _restrict_perms(path: Path) -> None:
    """Make the config file readable only by the current user.

    On POSIX this is a single chmod(0600). On Windows, os.chmod is effectively
    a no-op for access control (NTFS uses ACLs, not mode bits), so we shell
    out to icacls to remove inheritance and grant access only to the current
    user. If icacls is unavailable we warn rather than silently leaving the
    file world-readable.
    """
    if os.name == "nt":
        import subprocess

        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        try:
            # /inheritance:r removes inherited ACEs; /grant:r replaces any
            # explicit ACE for this user with full control for them alone.
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(
                f"Warning: could not restrict permissions on {path} via icacls "
                f"({exc}). The file contains secrets — store it in a protected "
                f"directory or restrict access manually.",
                file=sys.stderr,
            )
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def prompt_fields(provider: str) -> dict:
    """Ask the user for each required field. Secrets use getpass (no echo)."""
    import getpass

    fields = PROVIDER_FIELDS.get(provider)
    if not fields:
        raise SystemExit(f"Unknown provider {provider!r}. Known: {list(PROVIDER_FIELDS)}")
    block: dict = {}
    # S3 family gets type=s3 so the factory routes correctly.
    block["type"] = "qiniu" if provider == "qiniu" else "s3"
    for name, prompt, is_secret in fields:
        if is_secret:
            val = getpass.getpass(prompt)
        else:
            val = input(prompt).strip()
        if not val:
            print(f"  (left {name} empty — you can fill it in {DEFAULT_PATH} later)")
        block[name] = val
    return block


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build or edit the uploader config file.")
    p.add_argument("--provider", default="r2", choices=list(PROVIDER_FIELDS),
                   help="Which provider to add/edit (default: r2).")
    p.add_argument("--config", default=str(DEFAULT_PATH),
                   help=f"Config path (default: {DEFAULT_PATH}).")
    p.add_argument("--list", action="store_true", help="List configured providers and exit.")
    args = p.parse_args(argv)

    path = Path(args.config)
    config = load_existing(path)

    if args.list:
        providers = config.get("providers", {})
        if not providers:
            print(f"No providers configured in {path}")
        else:
            print(f"Providers in {path}:")
            for name, block in providers.items():
                ptype = block.get("type", "?")
                bucket = block.get("bucket", "?")
                print(f"  {name}  (type={ptype}, bucket={bucket})")
        return 0

    print(f"Configuring provider {args.provider!r} in {path}")
    print("Secrets will not be echoed. Press Enter to keep an existing value.\n")

    providers = config.setdefault("providers", {})
    existing = providers.get(args.provider, {})
    if existing:
        print(f"(Found existing {args.provider} block. Leave a field blank to keep it.)")

    block = prompt_fields(args.provider)
    # Preserve any existing field the user left blank on this run.
    for k, v in existing.items():
        block.setdefault(k, v)

    providers[args.provider] = block
    if "default" not in config:
        config["default"] = args.provider

    save(config, path)
    print(f"\n✓ Saved to {path}")
    print(f"  Permissions restricted to current user "
          f"({'icacls' if os.name == 'nt' else 'chmod 0600'}).")
    print(f"  Test with: python scripts/upload_images.py <doc.md> --provider {args.provider} --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
