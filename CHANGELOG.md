# Changelog

All notable changes to this skill are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-07-09

### Added
- Core `upload_images.py`: scan Markdown/HTML for local image references,
  upload to a 图床, rewrite paths to hosted URLs.
- Provider adapters for Cloudflare R2, Alibaba OSS, Tencent COS, MinIO,
  Backblaze B2 (all S3-compatible via boto3) and Qiniu (dedicated SDK).
- `estimate_upload.py`: pre-flight scope check without credentials or upload.
- `check_links.py`: post-upload verification (residual local paths + optional
  URL reachability via HEAD).
- `config_provider.py`: interactive credential setup with restrictive file
  permissions.
- Manifest-based deduplication (`.upload-manifest.json`): unchanged files are
  never re-uploaded; content hash detects local edits.
- Code-fence and inline-code masking so `![](path)` in examples is never
  uploaded.
- Offset-based replacement so the same filename in prose and in an image tag
  are handled independently; partial failures preserve local paths.
- 61-assertion smoke suite across 20 test functions covering scanner,
  resolver, replacer, manifest, and end-to-end pipeline with a fake
  provider (no network needed).
- Full reference docs: providers, parameters, path replacement, manifest
  format, quality gate, troubleshooting.
