# Troubleshooting

Symptom → cause → fix, with copy-pasteable commands.

## "Provider setup failed: S3 provider config is missing required field(s)"

**Cause**: the config file does not have all required fields for the provider.

**Fix**: run the interactive configurator, or inspect what's configured.

```bash
python scripts/config_provider.py --provider r2
python scripts/config_provider.py --list   # shows provider names + buckets, NO secrets
```

To view/edit the raw config file, open `~/.md-image-uploader.json` in a local
editor — **do not** `cat` it into a terminal that an Agent is watching, as it
contains plaintext credentials.

## Uploads fail with "The authorization header is malformed" (R2)

**Cause**: wrong endpoint format, or `region` not set to `auto`.

**Fix**: confirm the endpoint is `https://<account-id>.r2.cloudflarestorage.com`
and `region` is `"auto"`. See `references/providers.md` → Cloudflare R2.

## Uploads fail with "PermanentRedirect" / "301"

**Cause**: `path_style` is false, but R2/MinIO require path-style addressing.

**Fix**: set `"path_style": true` in the provider config.

## "boto3 is required for S3-compatible providers"

**Cause**: boto3 is not installed.

**Fix**:

```bash
pip install boto3
```

## Images uploaded but URLs return 404

**Cause**: `public_url` is wrong or the bucket is not publicly readable.

**Fix**:
- R2: enable the `*.r2.dev` public URL on the bucket, or bind a custom domain
  and set `public_url` to it.
- OSS/COS: set `acl: public-read` or bind a CDN domain.
- Verify with `check_links.py --verify-urls`.

## A local image was not uploaded, but no error appeared

**Cause**: the reference is inside a code fence or inline code (intentionally
skipped), or the path does not point to a real file (reported as `missing`).

**Fix**: run with `--dry-run` to see what the scanner found. If the path is
inside a code block, that is expected behavior — move it outside the fence.

## Re-run re-uploaded everything (no dedup)

**Cause**: the manifest is missing, or `--no-skip-uploaded` was passed, or the
files were edited (hash mismatch).

**Fix**: check `.upload-manifest.json` exists beside the document. If files
genuinely changed, re-uploading is correct.

## The same image was uploaded twice

**Cause**: it appears at two different local paths (e.g. copied to two folders).
The manifest dedups by path+hash, not by content alone.

**Fix**: this is expected unless you share a manifest. Use
`--manifest shared.json` across documents if you want content-level dedup.

## Markdown reference-style link `[id]: url` not rewritten

**Cause**: the definition line is indented or malformed beyond what the regex
expects.

**Fix**: ensure definitions are at the start of a line (no leading spaces) and
use the exact syntax `[id]: url`. Inline `![](path)` syntax is more reliable.

## Windows: path with backslashes not resolved

**Cause**: the document uses `assets\foo.png` with backslashes.

**Fix**: the resolver normalizes backslashes to forward slashes internally, but
Markdown conventionally uses `/`. Prefer forward slashes in documents.
