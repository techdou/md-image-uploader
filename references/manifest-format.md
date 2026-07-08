# Manifest Format

The `.upload-manifest.json` file records every successful upload so re-runs
skip unchanged files. This is what makes the skill idempotent — without it,
every run would re-upload every image, wasting quota and creating duplicates.

## Location

By default, one manifest per document directory:

```
lectures/
├── chapter01.md
├── chapter01.uploaded.md
└── .upload-manifest.json    <- shared by all docs in this directory
```

Pass `--manifest path/to/shared.json` to use a single manifest across
non-adjacent documents.

## Schema

```json
{
  "<absolute-local-path>": {
    "url": "https://cdn.example.com/2026/07/a1b2c3d4.png",
    "hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "size": 12345,
    "uploaded_at": "2026-07-09T01:30:00"
  }
}
```

| Field | Type | Meaning |
|---|---|---|
| key | string | Absolute path to the local file. Stable across runs in the same project. |
| `url` | string | The hosted URL returned by the provider. Reused on cache hit. |
| `hash` | string | MD5 hex of the file's contents. Used to detect edits. |
| `size` | int | File size in bytes (for reporting). |
| `uploaded_at` | string | ISO-8601 timestamp of the upload. |

## Dedup logic

Before uploading a file, the pipeline:

1. Computes the file's current MD5.
2. Looks up the absolute path in the manifest.
3. **Hit (hash matches)**: reuses the stored URL. No upload. Counted as `reused`.
4. **Stale (hash differs)**: the file was edited locally. Re-uploads and overwrites the entry.
5. **Miss (path absent)**: fresh upload. Adds a new entry.

This means renaming a file locally creates a new manifest entry (the old one
becomes orphaned but harmless). Editing a file in place triggers a re-upload
because the hash no longer matches.

## Object key naming

Uploaded objects are stored under:

```
YYYY/MM/<hash-first-8-chars>.<ext>
```

Example: `2026/07/a1b2c3d4.png`. The hash prefix means identical content
naturally deduplicates on the bucket (same key) even across different local
filenames.

## Safety

- The manifest is written atomically (temp file + rename), so a crash mid-write
  cannot corrupt it.
- A corrupt or unparseable manifest is treated as empty (dedup is lost, but the
  run proceeds) rather than crashing.
- Deleting the manifest is safe — it only means future runs re-upload.
- The manifest contains no secrets (URLs and hashes only).
