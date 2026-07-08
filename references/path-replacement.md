# Path Scanning and Replacement

How the scanner finds image references and how the replacer rewrites them
without clobbering the wrong text.

## What gets scanned

### Markdown

| Syntax | Example | Handled |
|---|---|---|
| Inline image | `![alt](path.png)` | ✓ |
| Inline with title | `![alt](path.png "Title")` | ✓ |
| Reference-style usage | `![alt][ref]` + `[ref]: path.png` | ✓ (rewrites the `[ref]` value) |
| Embedded HTML `<img>` | `<img src="path.png">` inside `.md` | ✓ |

### HTML

| Source | Example | Handled |
|---|---|---|
| `<img src>` | `<img src="assets/x.png">` | ✓ |
| `<source srcset>` | `srcset="a.png 1x, b.png 2x"` | ✓ (each URL separately) |
| `<image src>` (SVG) | `<image href="x.png">` | ✓ |
| CSS `url()` in `<style>` | `background: url(bg.png)` | ✓ |
| Inline `style="url()"` | `style="background:url(x.png)"` | ✓ (with bs4) |

## What is explicitly skipped

- **Remote URLs**: `http://`, `https://`, `data:`, `mailto:`, `#`, `blob:`, `//`.
  These are returned by the scanner (so they can be counted) but never uploaded.
- **Code fences**: anything inside ` ``` ` or `~~~` blocks is masked before
  scanning. An `![](path.png)` in a code example is never uploaded.
- **Inline code**: `` `![](path.png)` `` is masked the same way.
- **Non-image attributes**: `<script src="app.js">` is ignored because `.js` is
  not an image extension. Only image extensions are considered.

## Why offset-based replacement matters

Consider a document where the same filename appears twice:

```markdown
The ![chart](assets/chart.png) shows growth. See also assets/chart.png in the repo.
```

A naive `str.replace("assets/chart.png", url)` would rewrite **both** occurrences,
including the prose mention. The replacer uses `(start, end)` offsets captured
during scanning, so only the actual `![](...)` reference is rewritten. The bare
`assets/chart.png` in prose is left alone.

### Implementation

Replacements are sorted by `start` descending and spliced into the string from
the end. Processing from the end means earlier offsets never shift as later
chunks grow or shrink — each splice is independent.

## Partial failure safety

If an upload fails (network error, auth error), that image's local path is
preserved in the output document. Other images are still uploaded and rewritten.
The failed item is recorded in the report and (with `--strict`) causes a
non-zero exit.

## Relative path resolution

Paths are resolved **relative to the document's directory**, not the current
working directory:

```
/home/user/lectures/chapter01.md        references assets/x.png
  -> resolves to /home/user/lectures/assets/x.png
```

This matches Typora, Obsidian, and most static-site conventions. Root-relative
paths like `/assets/x.png` are treated as relative to the document directory
(the leading slash is stripped), which approximates a web root.
