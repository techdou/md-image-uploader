---
name: md-image-uploader
description: Batch-upload local images referenced in Markdown/HTML files to an image host (Cloudflare R2, Alibaba OSS, Tencent COS, Qiniu, MinIO, Backblaze B2) and rewrite the local paths in the document to hosted CDN URLs. Use whenever the user wants to migrate a document's local image assets to a 图床 before publishing — 准备发博客/公众号/知乎、讲义配图上线、Markdown 图片外链化、replace ![alt](./assets/x.png) with hosted URLs、批量上传图片到图床、or fix broken local image links in a finished document. Even if they don't say "upload", trigger when the goal is making a doc's images loadable online without local files. Supports deduplication via manifest, dry-run preview, code-fence skipping, and in-place or copy output modes.
compatibility: Requires Python 3.10+. boto3 is required for S3-compatible providers (R2/OSS/COS/MinIO/B2). Optional: qiniu (for Qiniu), beautifulsoup4 (for robust HTML parsing). Provider credentials are read from a config file or environment variables, never hardcoded.
---

# Markdown Image Uploader

Use this skill when the user has a **finished Markdown or HTML document whose images live in a local `assets/` folder** and wants those images pushed to an image host (图床) with the document's links rewritten to the hosted URLs.

Do **not** use it for: turning local images into Base64 inline data (that is `html-asset-toolkit`'s job), compressing or converting image formats, uploading single ad-hoc images from the clipboard (use PicGo for that), or running a long-lived web gallery (use Cloudreve/EasyImages).

## Agent routing

Trigger this skill when the user asks to:

- Upload a Markdown/HTML document's local images to R2 / OSS / COS / 七牛 / 图床 / CDN.
- Migrate `![alt](./assets/x.png)` references to hosted URLs before publishing.
- 批量上传讲义/公众号文章/博客配图到图床并替换链接.
- Fix a document whose images do not load because they point at local paths.
- Estimate how many local images a document references and their total size (pre-flight).

Avoid this skill for: Base64 inlining (→ `html-asset-toolkit`), image generation/editing (→ `article-illustration-generator`), single-image ad-hoc uploads via GUI (→ PicGo).

## Core decision rule

| User intent | Correct action |
|---|---|
| Publish a finished doc with local images | Upload + rewrite. Default to `.uploaded.md` output. |
| Unsure how many images / how big | Run `estimate_upload.py` first (no credentials needed). |
| Want to preview without spending quota | `upload_images.py --dry-run` (scans, reports, uploads nothing). |
| Already uploaded, verifying | `check_links.py` on the `.uploaded.md` (no credentials needed). |
| Re-running on the same doc | Default `--skip-uploaded` reuses URLs from manifest; changed images re-upload. |
| Same path reused across many docs | Manifest is keyed per-document by default; pass `--manifest` to share one. |

## Provider support

| Provider | `--provider` | type | Notes |
|---|---|---|---|
| Cloudflare R2 | `r2` | s3 | `region: auto`, `path_style: true`, endpoint `https://<account-id>.r2.cloudflarestorage.com`. **No credit card required for free tier.** |
| Alibaba OSS | `oss` | s3 | Region-specific endpoint, e.g. `https://oss-cn-hangzhou.aliyuncs.com`. |
| Tencent COS | `cos` | s3 | Endpoint `https://cos.<region>.myqcloud.com`. |
| MinIO (self-hosted) | `minio` | s3 | `path_style: true`; endpoint is your server URL. |
| Backblaze B2 | `b2` | s3 | Endpoint `https://s3.<region>.backblazeb2.com`. |
| Qiniu (七牛) | `qiniu` | qiniu | Needs `qiniu` SDK; requires a bound domain. |

All S3-family providers share one boto3-based adapter; only `endpoint`, `region`, and `public_url` differ. See `references/providers.md` for per-provider credential setup.

## Output convention

Unless `--in-place` is passed, the rewritten document is written beside the input with `.uploaded` inserted before the extension:

```text
lectures/chapter01.md   ->  lectures/chapter01.uploaded.md
notes/index.html        ->  notes/index.uploaded.html
```

The original file is never touched. A manifest named `.upload-manifest.json` is written in the same directory to enable deduplication on subsequent runs.

## Preferred workflows

> **Recommended**: always run `--dry-run` first on a new document to confirm the scanner finds the expected images and to catch missing files before spending upload quota.

### A. Single document (most common)

```bash
# 1. Preview (no upload, no credentials)
python scripts/upload_images.py path/to/lecture.md --dry-run

# 2. Upload to R2, writing lecture.uploaded.md
python scripts/upload_images.py path/to/lecture.md --provider r2

# 3. Verify no local paths leaked through
python scripts/check_links.py path/to/lecture.uploaded.md
```

### B. Whole directory (batch)

```bash
python scripts/upload_images.py path/to/docs/ --provider r2
```

Recursively processes every `.md`/`.html` file. Each gets its own `.uploaded.*` output and shares a per-directory manifest.

### C. Estimate before uploading (no credentials needed)

```bash
python scripts/estimate_upload.py path/to/lecture.md
python scripts/estimate_upload.py path/to/docs/ --json
```

Reports image count, total size, and any missing files. Use when you want to confirm scope before touching the bucket.

### D. Configure provider credentials (first-time setup)

```bash
python scripts/config_provider.py --provider r2
```

Interactively builds `~/.md-image-uploader.json`. Secrets are entered with `getpass` (no echo) and the file is restricted to the current user (`chmod 0600` on POSIX, `icacls /inheritance:r` on Windows). List existing providers with `--list`.

## Agent execution contract

1. **Always dry-run first** on a document the user has not uploaded before. Report the image count and total size, then ask whether to proceed (unless the user already said to upload).
2. **Credentials never go in chat.** Read them from `~/.md-image-uploader.json` or environment variables. If the config is missing, point the user to `config_provider.py` — do not ask them to paste keys into the conversation.
3. **Default to non-destructive output** (`.uploaded.md`). Only use `--in-place` when the user explicitly asks to modify the original.
4. **Report failures, do not hide them.** If any image fails to upload, the script continues the batch but records the failure. Surface failed items to the user; the affected local paths are preserved in the output.
5. **Run `check_links.py`** after upload as a quality gate. A clean upload has zero residual local paths.
6. **Never print credentials, full URLs containing tokens, or the manifest's raw contents** into chat. Summarize counts instead.
7. **Respect code fences.** The scanner masks ```` ``` ```` blocks and inline `` ` `` code; an `![](path)` inside example code is never uploaded. Do not try to "fix" this by forcing those paths.
8. **Manifest is per-document by default.** If the user wants one shared manifest across a project, pass `--manifest path/to/shared.json`.
9. **Missing local files are warnings, not errors.** A reference whose path does not exist on disk is reported as `missing` and left untouched; it does not block the rest of the batch.
10. **Use `--strict` for CI/gated delivery** so a non-zero exit signals a failed upload that needs attention.

## Scripts

### Upload (core)

```bash
python scripts/upload_images.py <file_or_dir>
python scripts/upload_images.py lecture.md --provider r2
python scripts/upload_images.py lecture.md --dry-run
python scripts/upload_images.py docs/ --provider oss --include-ext .png,.jpg
python scripts/upload_images.py lecture.md --in-place
python scripts/upload_images.py lecture.md --no-skip-uploaded   # force re-upload
python scripts/upload_images.py lecture.md --json               # machine report
```

Useful flags: `--dry-run`, `--in-place`, `--strict`, `--json`, `--manifest <path>`, `--include-ext .png,.jpg`, `--retries 3`, `--config <path>`.

### Estimate (no credentials, no upload)

```bash
python scripts/estimate_upload.py lecture.md
python scripts/estimate_upload.py docs/ --json
```

### Check links (post-upload verification)

```bash
python scripts/check_links.py lecture.uploaded.md
python scripts/check_links.py lecture.uploaded.md --verify-urls --strict
```

### Configure provider

```bash
python scripts/config_provider.py --provider r2
python scripts/config_provider.py --list
```

## Read when needed

- `references/providers.md` — per-provider credential setup, endpoint formats, and R2-specific quirks (no credit card, `region: auto`, `path_style`).
- `references/parameters.md` — full CLI parameter reference for all four scripts.
- `references/path-replacement.md` — how Markdown/HTML/CSS references are scanned and rewritten, including code-fence masking and offset-based replacement.
- `references/manifest-format.md` — the `.upload-manifest.json` schema and dedup-by-hash logic.
- `references/quality-gate.md` — delivery checklist before handing off an uploaded document.
- `references/troubleshooting.md` — auth failures, missing files, partial uploads, R2 endpoint mistakes.

## Quality gate

Before handing off an uploaded document:

1. Confirm `--dry-run` reported the expected image count.
2. Confirm the `.uploaded.md` (or in-place file) was written.
3. Run `check_links.py` and confirm **zero residual local paths**.
4. Confirm the manifest (`.upload-manifest.json`) was written beside the doc.
5. Spot-check one hosted URL in a browser if practical.
6. If any upload failed, report which images and that their local paths were preserved.

## Robustness rules for agents

- For a brand-new document, always `--dry-run` before the real upload.
- If the user has no config file, walk them through `config_provider.py` rather than asking for keys in chat.
- Prefer the default `.uploaded.md` output; switch to `--in-place` only on explicit request.
- Treat a non-zero `--strict` exit as a real failure to investigate, not a warning to ignore.
- Do not delete or rewrite the manifest yourself; the script manages it.
- When batching a directory, summarize per-file counts in the final message rather than dumping every detail.

## Feature reference

| Feature | Script | When to use |
|---|---|---|
| Upload + rewrite | `upload_images.py` | Push local images to a 图床 and update the doc |
| Dry-run preview | `upload_images.py --dry-run` | See what would upload without spending quota |
| Dedup / skip unchanged | `upload_images.py` (default) | Re-running on an edited doc; unchanged images reuse cached URLs |
| Force re-upload | `upload_images.py --no-skip-uploaded` | Bucket was wiped, or you want fresh URLs |
| Size estimate | `estimate_upload.py` | Pre-flight scope check, no credentials needed |
| Link verification | `check_links.py` | Confirm an uploaded doc has no residual local paths |
| URL reachability | `check_links.py --verify-urls` | HEAD each hosted URL (needs network) |
| Credential setup | `config_provider.py` | First-time provider configuration |
