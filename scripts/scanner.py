"""Shared scanning utilities: path resolution, Markdown parsing, HTML parsing.

This module is the "read-only" half of the skill — it locates local image
references inside a document but never uploads or modifies anything. Both the
main uploader and the estimator/checker depend on it so the definition of
"what counts as a local image reference" lives in exactly one place.

Design notes
------------
- We deliberately avoid depending on a Markdown AST library. Markdown's image
  syntax is simple enough that a well-crafted regex + a code-fence guard is
  more robust than wrestling with differing CommonMark parser quirks, and it
  keeps the skill dependency-light.
- For HTML we try BeautifulSoup if installed (handles malformed HTML, attribute
  order, case), otherwise fall back to a hand-rolled regex scanner. The output
  dataclass is identical either way so callers do not care.
- Every match carries absolute (start, end) offsets into the source text. The
  replacer uses these offsets for surgical slice-replacement, which is the
  only way to avoid str.replace() clobbering the same path mentioned in prose.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

# --------------------------------------------------------------------- types

#: Extensions we treat as uploadable images by default. Anything else found in
#: an <img src> is left alone (it may be a non-image asset handled elsewhere).
DEFAULT_IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".bmp", ".ico", ".avif",
}

#: URL schemes that mean "already remote, leave it alone". Anything not
#: starting with these is considered a candidate local path.
REMOTE_PREFIXES = (
    "http://", "https://", "data:", "mailto:", "tel:", "#",
    "javascript:", "blob:", "ftp://", "//",
)


@dataclass
class ImageRef:
    """One image reference found in a document.

    Attributes:
        raw: The path string as written in the document (may be relative).
        start/end: Character offsets into the source string, used by the
            replacer for surgical slice-replacement.
        syntax: How the reference was written — ``markdown``, ``html_attr``,
            ``html_srcset``, ``css_url``, or ``md_reference``. Mainly for
            reporting; replacement uses start/end only.
        alt: Alt text if available (Markdown ``![alt]()``, HTML ``alt``).
        replacement: If set, the replacer writes *this exact string* into the
            [start, end) span instead of just the URL. Used by reference-style
            images where the whole ``![alt][id]`` must become ``![alt](url)``.
            When empty, the replacer falls back to the URL from url_map.
    """

    raw: str
    start: int
    end: int
    syntax: str
    alt: str = ""
    replacement: str = ""

    @property
    def clean_path(self) -> str:
        """The URL-decoded path with query/fragment stripped."""
        return strip_query_fragment(self.raw)


# ----------------------------------------------------------- path utilities

def is_remote_or_special(url: str) -> bool:
    """True if *url* already points elsewhere (http, data, anchor, etc.).

    We also treat ``${`` and ``{{`` as non-local so templated placeholders are
    never mistaken for files. Empty strings are "special" (skip).
    """
    value = url.strip()
    if not value:
        return True
    if value.lower().startswith(REMOTE_PREFIXES):
        return True
    if "${" in value or "{{" in value:
        return True
    return False


def strip_query_fragment(url: str) -> str:
    """Drop ``?query`` and ``#fragment`` from a local path.

    For ``file:`` or schemeless paths we unquote percent-escapes so a Markdown
    link like ``assets/a%20b.png`` resolves to the real file ``a b.png``.
    Remote URLs are returned untouched (they are not our concern).
    """
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in ("file", ""):
        return url
    return unquote(parsed.path)


def resolve_local(url: str, base_dir: Path) -> Path | None:
    """Resolve a candidate local path against *base_dir*.

    ``base_dir`` is the directory of the document the reference came from.
    Relative paths (``./x.png``, ``../x.png``, ``assets/x.png``) and
    root-relative paths (``/assets/x.png``) are tried under base_dir. Returns
    the resolved absolute Path if a real file exists, else None.
    """
    if is_remote_or_special(url):
        return None
    clean = strip_query_fragment(url).strip().replace("\\", "/")
    if not clean:
        return None

    # Strip a single leading slash from "/assets/x.png": in a document context
    # it means "relative to the doc root", which we approximate as base_dir.
    # (We deliberately do NOT treat it as a filesystem-absolute path.)
    if clean.startswith("/") and not clean.startswith("//"):
        clean = clean.lstrip("/")

    candidates: list[Path] = []
    p = Path(clean)
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(base_dir / p)

    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def parse_ext_list(raw: str | None) -> set[str]:
    """Parse a ``--include-ext .png,.jpg`` argument into a set of ``.png``."""
    values: set[str] = set()
    if not raw:
        return set()
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        values.add(item if item.startswith(".") else f".{item}")
    return values


# ----------------------------------------------------------- markdown scanner

#: Alt text that allows backslash-escaped closing bracket: alt = "Fig. 1 \[x\]".
#: Matches any char that is not ']' or '\', OR a '\' followed by any char.
_ALT = r"(?:[^\]\\]|\\.)*"

#: Inline image: ![alt](url) or ![alt](url "title") or ![alt](<url with space>)
#: Supports angle-bracket URLs (CommonMark) for paths containing spaces.
#: title may use single or double quotes.
_MD_INLINE_IMG = re.compile(
    r"!\[(?P<alt>" + _ALT + r")\]\(\s*"
    r"(?:<(?P<url_angle>[^>]*)>|(?P<url>[^)\s\"']+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)

#: Reference definition: [id]: url "optional title"
#: url may be angle-bracketed; title may use single or double quotes.
_MD_REF_DEF = re.compile(
    r"^\s*\[(?P<id>" + _ALT + r")\]:\s*"
    r"(?:<(?P<url_angle>[^>]*)>|(?P<url>\S+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*$",
    re.MULTILINE,
)

#: Reference-style image usage: ![alt][id]
_MD_REF_USAGE = re.compile(r"!\[(?P<alt>" + _ALT + r")\]\[(?P<id>" + _ALT + r")\]")

#: HTML <img ...> tag. We capture the whole opening tag so start/end span it.
_HTML_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

#: Generic src/href attribute capture (for <img>, <source>, <image>).
_ATTR_RE = re.compile(
    r"""\b(?:src|srcset|href|data)\s*=\s*(?P<q>["'])(?P<val>[^"']+)(?P=q)""",
    re.IGNORECASE,
)

#: CSS url(...) inside <style> blocks or inline style="".
_CSS_URL_RE = re.compile(
    r"""url\(\s*(?P<q>["']?)(?P<val>[^)"']+)(?P=q)\s*\)""",
    re.IGNORECASE,
)


def scan_markdown(text: str) -> list[ImageRef]:
    """Find every image reference in a Markdown document, local or remote.

    The scanner does NOT filter out remote URLs — it returns all references
    it can syntactically recognize. The caller decides what to do with each
    one (upload, skip, report). This keeps scanning concerns separate from
    upload policy and lets the pipeline count "skipped remote" accurately.

    Handles three syntaxes, all returning offset-anchored ImageRef objects:

    1. Inline: ``![alt](path)``
    2. Reference: ``![alt][id]`` resolved against a ``[id]: url`` definition.
       We rewrite *usage* matches (with the alt) so the offsets point at the
       ``![alt][id]`` site the user sees, not the definition line.
    3. Raw HTML ``<img>`` tags embedded in the Markdown.

    Code fences (``` and ~~~) and inline code (`...`) are masked out first so
    an ``![](path)`` that appears inside example code is never uploaded.
    """
    refs: list[ImageRef] = []
    masked = _mask_code_blocks(text)

    # 1. Inline images: ![alt](url) or ![alt](<url with space>)
    for m in _MD_INLINE_IMG.finditer(masked):
        # url_angle wins when present (angle-bracket form); else bare url.
        if m.group("url_angle") is not None:
            url = m.group("url_angle")
            start, end = m.start("url_angle"), m.end("url_angle")
        else:
            url = m.group("url")
            start, end = m.start("url"), m.end("url")
        refs.append(
            ImageRef(raw=url, start=start, end=end, syntax="markdown", alt=m.group("alt"))
        )

    # 2. Reference-style: build id->url map, then locate usages.
    ref_defs: dict[str, str] = {}
    for m in _MD_REF_DEF.finditer(text):  # defs read from raw text (safe)
        url = m.group("url_angle") if m.group("url_angle") is not None else m.group("url")
        ref_defs[m.group("id").strip().lower()] = url

    for m in _MD_REF_USAGE.finditer(masked):
        rid = m.group("id").strip().lower()
        url = ref_defs.get(rid)
        if not url:
            continue
        # Replace the WHOLE ![alt][id] usage with ![alt](url). Keeping only
        # the [id] span would leave a broken ![alt][<url>] that no CommonMark
        # renderer resolves, and the orphan [id]: definition would still
        # point at the local path. Rewriting to inline form fixes both.
        #
        # The replacement text is finalized in the replacer once we know the
        # hosted URL; here we just anchor the span on the full match and tag
        # the syntax so the replacer knows to rebuild the image tag.
        refs.append(
            ImageRef(
                raw=url,
                start=m.start(0),
                end=m.end(0),
                syntax="md_reference",
                alt=m.group("alt"),
            )
        )

    # 3. Embedded HTML <img> tags
    refs.extend(_scan_html_tags(masked))

    return refs


# ----------------------------------------------------------- html scanner

def scan_html(text: str) -> list[ImageRef]:
    """Find image references in an HTML document, local or remote.

    Like ``scan_markdown``, this returns ALL syntactically recognized
    references and leaves the local-vs-remote decision to the caller. Covers
    ``<img src>``, ``<source srcset>``, ``<image src>`` (SVG), and ``url()``
    inside ``<style>`` blocks or inline ``style=""``.

    Uses BeautifulSoup if available for robust tag/attribute parsing; falls
    back to regex. Both paths emit identical ImageRef objects anchored to
    offsets in the original text.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore

        return _scan_html_bs4(text, BeautifulSoup)
    except ImportError:
        return _scan_html_regex(text)


def _scan_html_bs4(text: str, BeautifulSoup) -> list[ImageRef]:  # pragma: no cover
    """BeautifulSoup-based scanner. Only used when bs4 is installed.

    bs4 gives tag objects but not reliable source offsets, so we re-locate
    each found value with a bounded search to get true offsets. This is more
    robust than regex for malformed HTML at the cost of a second pass.
    """
    refs: list[ImageRef] = []
    soup = BeautifulSoup(text, "html.parser")

    # <img>, <source>, <image> with src
    for tag in soup.find_all(["img", "source", "image"]):
        src = tag.get("src")
        if src and _looks_like_image(src):
            span = _find_value_span(text, src)
            if span:
                refs.append(ImageRef(src, span[0], span[1], "html_attr", tag.get("alt", "")))

        # srcset: "a.png 1x, b.png 2x"
        srcset = tag.get("srcset")
        if srcset:
            for candidate in _parse_srcset(srcset):
                if _looks_like_image(candidate):
                    span = _find_value_span(text, candidate)
                    if span:
                        refs.append(ImageRef(candidate, span[0], span[1], "html_srcset"))

    # CSS url() inside <style> blocks
    for style in soup.find_all("style"):
        if style.string:
            refs.extend(_scan_css_urls(style.string, text))

    # Inline style="background: url(...)"
    for tag in soup.find_all(style=True):
        refs.extend(_scan_css_urls(tag["style"], text))

    return refs


def _scan_html_regex(text: str) -> list[ImageRef]:
    """Pure-regex fallback. Handles the common cases well.

    We scan for attribute values that look like image paths. Because regex
    can't fully parse HTML, this is best-effort: well-formed documents and
    Typora exports parse cleanly; adversarial HTML should use bs4.

    Remote URLs are intentionally NOT filtered here — the caller classifies
    each ref. We only skip values that do not look like images (no image
    extension), since ``src="app.js"`` or ``href="#top"`` are not our concern.
    """
    refs: list[ImageRef] = []

    # src/href/data attributes on any tag
    for m in _ATTR_RE.finditer(text):
        val = m.group("val")
        if not _looks_like_image(val):
            continue
        refs.append(
            ImageRef(val, m.start("val"), m.end("val"), "html_attr")
        )

    # srcset (one attribute may contain several URLs)
    for m in re.finditer(r"srcset\s*=\s*[\"']([^\"']+)[\"']", text, re.IGNORECASE):
        raw_srcset = m.group(1)
        for candidate in _parse_srcset(raw_srcset):
            span = _find_value_span(text, candidate, search_from=m.start())
            if span:
                refs.append(ImageRef(candidate, span[0], span[1], "html_srcset"))

    # CSS url() anywhere
    refs.extend(_scan_css_urls(text, text))

    return refs


def _scan_html_tags(text: str) -> list[ImageRef]:
    """Scan embedded <img> tags inside Markdown text.

    Markdown documents often contain raw HTML. We reuse the regex HTML scanner
    but only emit src-style matches (srcset inside Markdown is rare).
    """
    refs: list[ImageRef] = []
    for m in _HTML_IMG_TAG.finditer(text):
        tag_text = m.group(0)
        tag_start = m.start()
        # Look for src= inside this tag
        am = _ATTR_RE.search(tag_text)
        if not am:
            continue
        val = am.group("val")
        if not _looks_like_image(val):
            continue
        # Translate the attribute offset back to full-text coordinates.
        refs.append(
            ImageRef(
                val,
                tag_start + am.start("val"),
                tag_start + am.end("val"),
                "html_attr",
            )
        )
    return refs


def _scan_css_urls(css_text: str, full_text: str) -> list[ImageRef]:
    """Find ``url(...)`` references inside CSS text.

    *css_text* is a slice of *full_text*. We locate matches within the slice
    then map offsets back to the full document so the replacer can cut them
    out precisely.

    Only values that look like image files are emitted; ``url(font.woff2)``
    or ``url(https://fonts...)`` are ignored. The caller still gets to decide
    local vs remote for actual image URLs.
    """
    refs: list[ImageRef] = []
    offset = full_text.find(css_text)
    base = offset if offset >= 0 else 0
    for m in _CSS_URL_RE.finditer(css_text):
        val = m.group("val")
        if not _looks_like_image(val):
            continue
        refs.append(
            ImageRef(
                val,
                base + m.start("val"),
                base + m.end("val"),
                "css_url",
            )
        )
    return refs


# ----------------------------------------------------------- helpers

def _mask_code_blocks(text: str) -> str:
    """Replace fenced (```/~~~) and inline (`) code with equal-length spaces.

    Offsets of non-code content are preserved because the masked string has
    exactly the same length as the original. This is the simplest way to make
    regex scanning "skip" code without juggling offset bookkeeping.
    """
    result = list(text)

    # Fenced blocks: ``` or ~~~ until the matching fence. A closing fence
    # must be at least as long as the opening fence (CommonMark rule).
    fence = re.compile(r"^([ \t]*)(```+|~~~+)", re.MULTILINE)
    pos = 0
    while True:
        m = fence.search(text, pos)
        if not m:
            break
        start = m.start()
        fence_char = m.group(2)[0]
        min_len = len(m.group(2))
        # Closing fence: same char, at least as many repetitions.
        close_pat = re.compile(
            r"^[ \t]*" + re.escape(fence_char) + r"{" + str(min_len) + r",}",
            re.MULTILINE,
        )
        cm = close_pat.search(text, m.end())
        end = cm.end() if cm else len(text)
        for i in range(start, end):
            if text[i] != "\n":
                result[i] = " "
        pos = end

    # Inline code spans: `...` (not ``), single line, no newlines inside.
    masked = "".join(result)
    masked = re.sub(
        r"`([^`\n]+)`",
        lambda m: "`" + " " * len(m.group(1)) + "`",
        masked,
    )
    return masked


def _parse_srcset(srcset: str) -> list[str]:
    """Extract URLs from a srcset string: ``"a.png 1x, b.png 2x"`` -> [a.png, b.png]."""
    urls: list[str] = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        # Each entry is "URL descriptor" or just "URL".
        url = part.split()[0] if part.split() else ""
        if url:
            urls.append(url)
    return urls


def _looks_like_image(path: str) -> bool:
    """Heuristic: does this path end in an image extension?"""
    clean = strip_query_fragment(path).lower()
    _, ext = os.path.splitext(clean)
    return ext in DEFAULT_IMAGE_EXTS


def _find_value_span(
    text: str, value: str, search_from: int = 0
) -> tuple[int, int] | None:
    """Locate the first occurrence of *value* at/after *search_from*.

    Used by the bs4 scanner to recover offsets that bs4 does not expose.
    Returns None if not found (shouldn't happen for values bs4 just gave us).
    """
    idx = text.find(value, search_from)
    if idx < 0:
        idx = text.find(value)
    if idx < 0:
        return None
    return idx, idx + len(value)


# ----------------------------------------------------------- dispatch

def scan_document(text: str, doc_type: str = "auto") -> list[ImageRef]:
    """Scan a document, dispatching on type.

    Args:
        text: The raw document content.
        doc_type: ``"markdown"``, ``"html"``, or ``"auto"`` (infer from a
            leading ``<!DOCTYPE`` or ``<html``). For Markdown we also run the
            HTML tag scanner since Markdown allows embedded HTML.

    Returns:
        All ImageRefs found. If the same file is referenced twice at different
        spans, both are kept because each span needs its own replacement.
    """
    if doc_type == "auto":
        stripped = text.lstrip()[:200].lower()
        if stripped.startswith("<!doctype") or stripped.startswith("<html"):
            doc_type = "html"
        else:
            doc_type = "markdown"

    if doc_type == "html":
        refs = scan_html(text)
    else:
        refs = scan_markdown(text)
    return refs


def find_local_path_residue(text: str) -> list[ImageRef]:
    """Find ANY local-looking image path still in the document.

    This is stricter than scan_document and is meant for post-upload
    verification (check_links). It additionally scans:

    - ``[id]: local-path`` reference *definition* lines, which scan_markdown
      intentionally skips (definitions are resolved into usages, not uploaded
      directly). After a reference-style rewrite the definition becomes an
      orphan but still contains a local path — this function catches it.

    Returns refs with ``syntax="residue"`` for anything local that remains.
    """
    residue: list[ImageRef] = []

    # First: everything the normal scanner finds. Filter to local-only.
    for ref in scan_document(text, doc_type="auto"):
        if not is_remote_or_special(ref.raw):
            residue.append(ref)

    # Second: reference definition lines [id]: <path> that point at local
    # files. These are invisible to scan_markdown (used only to build the
    # id map). After an upload they may linger as orphans.
    masked = _mask_code_blocks(text)
    for m in _MD_REF_DEF.finditer(masked):
        url = m.group("url_angle") if m.group("url_angle") is not None else m.group("url")
        if is_remote_or_special(url):
            continue
        gname = "url_angle" if m.group("url_angle") is not None else "url"
        residue.append(
            ImageRef(
                raw=url,
                start=m.start(gname),
                end=m.end(gname),
                syntax="residue",
            )
        )

    # Deduplicate by (raw, start): the usage site and the definition line of
    # the same reference-style image can both surface the same path. They are
    # at different spans, so only exact span overlaps (which never legitimately
    # happen) get collapsed. Without this, check_links on a NOT-yet-uploaded
    # reference-style doc would list the same path twice.
    seen: set[tuple[str, int]] = set()
    deduped: list[ImageRef] = []
    for ref in residue:
        key = (ref.raw, ref.start)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped
