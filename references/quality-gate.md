# Quality Gate

Checklist to run before handing off an uploaded document. Following this
prevents the most common failure modes: stale local paths in the "uploaded"
file, silently failed uploads, or broken hosted URLs.

## Pre-upload

- [ ] Ran `upload_images.py --dry-run` and confirmed the expected image count.
- [ ] No `missing` files reported (every local reference resolves to a real file).
- [ ] Total size is reasonable for the provider's quota (R2: 10 GB free).

## Post-upload

- [ ] `.uploaded.md` (or in-place file) was written.
- [ ] `check_links.py` reports **zero residual local paths**.
- [ ] `.upload-manifest.json` was written beside the document.
- [ ] Report shows `failed: 0`. If `failed > 0`, the affected images kept their
      local paths — surface them to the user.

## Optional (when network is available)

- [ ] `check_links.py --verify-urls` returns all-`ok` for hosted URLs.
- [ ] Opened one hosted URL in a browser and confirmed the image renders.

## Delivery message template

When handing off, summarize rather than dumping details:

> Uploaded 12 images to R2 (reused 3 from manifest, 0 failed).
> Output: `lecture.uploaded.md`.
> Manifest: `.upload-manifest.json` (next run will skip unchanged images).
> Verified: 0 residual local paths.

Do **not** paste full URLs, manifest contents, or any credentials into chat.
