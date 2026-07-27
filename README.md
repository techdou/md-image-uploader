# md-image-uploader | Markdown 图床上传

[English](#english) | [中文](#中文)

---

<a id="中文"></a>
## 中文

Agent Skill，批量上传 Markdown/HTML 文档中的本地图片到图床（Cloudflare R2、阿里云 OSS、腾讯云 COS、七牛、MinIO、Backblaze B2），并将文档内的本地路径改写为 CDN URL。

### 触发场景

- 准备发博客/公众号/知乎前，把本地配图上线
- 讲义配图外链化、修复文档中失效的本地图片链接
- `replace ![alt](./assets/x.png) with hosted URLs`
- 批量上传图片到图床

支持去重清单、dry-run 预览、跳过代码块、原地或副本输出。

下方英文为完整文档。

---

<a id="english"></a>
## English

<div align="center">

**Batch-upload local images in Markdown/HTML to an image host and rewrite the links — an Anthropic Agent Skill.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Tests: 61 passing](https://img.shields.io/badge/tests-61%20passing-brightgreen.svg)](#testing)

</div>

---

## Why this exists

When an AI agent (Claude, Codex, ZCode, etc.) writes a lecture, article, or
blog post for you, the images usually land in a local `assets/` folder as
relative paths (`![diagram](assets/diagram.png)`). Before publishing to a
blog, 公众号, or 知乎, those images need to move to a 图床 and the document's
links need to point at the hosted URLs.

Doing this by hand for every image is tedious and error-prone. This skill
automates the whole loop: **scan → upload → rewrite → verify**.

```
your-doc.md (assets/foo.png)  ──►  your-doc.uploaded.md (https://cdn.../foo.png)
```

## What it does

- 🔍 **Scans** Markdown and HTML for local image references
  - `![](assets/x.png)`, reference-style `![alt][id]`, `<img src>`, `srcset`, CSS `url()`
  - Skips code fences and inline code so examples are never uploaded
- ☁️ **Uploads** to Cloudflare R2, Alibaba OSS, Tencent COS, Qiniu, MinIO, or Backblaze B2
- ✏️ **Rewrites** the document's local paths to hosted URLs (offset-precise, non-destructive)
- ♻️ **Deduplicates** via a content-hash manifest — re-runs skip unchanged images
- ✅ **Verifies** no local paths leaked through

## Quick start

```bash
# 1. Configure your image host (interactive, secrets hidden)
python scripts/config_provider.py --provider r2

# 2. Preview what would be uploaded (no credentials needed)
python scripts/estimate_upload.py path/to/lecture.md

# 3. Upload and rewrite (writes lecture.uploaded.md, original untouched)
python scripts/upload_images.py path/to/lecture.md --provider r2

# 4. Verify the result is clean
python scripts/check_links.py path/to/lecture.uploaded.md
```

## Install as an Agent Skill

This is an [Anthropic Agent Skill](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills).
Drop the folder into your skills directory:

```bash
# Claude Code / ZCode
cp -r md-image-uploader ~/.claude/skills/
# or the shared location
cp -r md-image-uploader ~/.agents/skills/
```

Then tell your agent something like *"upload this lecture's images to R2
before I publish it"* and it will route to this skill automatically.

## Supported providers

| Provider | `--provider` | SDK | Free tier |
|---|---|---|---|
| **Cloudflare R2** | `r2` | boto3 | 10 GB storage, zero egress, no credit card |
| Alibaba OSS | `oss` | boto3 | Trial credits |
| Tencent COS | `cos` | boto3 | Trial credits |
| MinIO (self-hosted) | `minio` | boto3 | Your server |
| Backblaze B2 | `b2` | boto3 | 10 GB storage |
| Qiniu (七牛) | `qiniu` | qiniu | 10 GB storage |

All S3-compatible providers share one adapter; only `endpoint`, `region`, and
`public_url` differ.

## Design principles

| Principle | How |
|---|---|
| **Non-destructive** | Writes `.uploaded.md` by default; original is never touched |
| **Idempotent** | Manifest dedup means safe re-runs, no duplicate uploads |
| **Credential-safe** | Secrets read from config/env, never echoed to chat |
| **Partial-failure safe** | One bad image doesn't abort the batch |
| **Code-fence aware** | `![](path)` inside examples is never uploaded |

## Testing

```bash
python tests/smoke_test.py
```

**61 assertions across 20 test functions**, no network or real credentials
required (uses an in-memory fake uploader). Covers scanner edge cases
(reference-style, angle-bracket paths, escaped brackets, code-fence masking),
replacer offset correctness, manifest dedup, and three end-to-end scenarios.

This skill has passed **two independent code reviews** (CRITICAL/HIGH/MEDIUM/LOW
graded) with all findings resolved.

## Project structure

```
md-image-uploader/
├── SKILL.md              # Agent entry point (routing + execution contract)
├── scripts/
│   ├── upload_images.py  # Core: scan → upload → rewrite
│   ├── estimate_upload.py
│   ├── check_links.py
│   ├── config_provider.py
│   ├── scanner.py        # Markdown/HTML reference scanner
│   ├── replacer.py       # Offset-precise path rewriting
│   └── manifest.py       # Content-hash dedup
├── providers/            # Image host adapters (S3, Qiniu)
├── references/           # Deep-dive docs (providers, params, troubleshooting)
├── examples/             # Runnable sample document + images
└── tests/                # Smoke test suite
```

## License

[MIT](LICENSE)
