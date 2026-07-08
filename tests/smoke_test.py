#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke tests for md-image-uploader.

Runs without network access and without real provider credentials by using a
fake uploader. Exercises: scanner (Markdown/HTML/CSS/reference-style/code-fence
masking), resolver (relative/absolute/remote filtering), manifest (dedup by
hash, hash-mismatch re-upload), replacer (offset correctness, partial failure),
and the end-to-end pipeline (file -> uploaded file with rewritten links).

Run:  python tests/smoke_test.py
Exits non-zero on the first failure.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make scripts/ and the skill root (for providers/) importable.
SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SKILL_ROOT))

import manifest as manifest_mod  # noqa: E402
import scanner  # noqa: E402
from manifest import Manifest  # noqa: E402
from providers import BaseUploader, UploaderError  # noqa: E402
from replacer import apply_replacements  # noqa: E402

# Tiny 1x1 PNG so resolve_local finds a real file on disk.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000101a5f645770000000049454e44ae426082"
)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}   {detail}")


def section(title: str) -> None:
    print(f"\n{title}")


# ----------------------------------------------------------- fake provider

class FakeUploader(BaseUploader):
    """Records uploads in-memory; returns deterministic URLs."""

    provider_id = "fake"

    def __init__(self, config=None):
        self.config = config or {}
        self.uploads: list[tuple[str, str]] = []

    def upload(self, local_path: str, remote_key: str) -> str:
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)
        self.uploads.append((local_path, remote_key))
        return f"https://cdn.fake/{remote_key}"


# ----------------------------------------------------------- tests

def test_markdown_inline() -> None:
    section("scanner: Markdown inline images")
    text = "See ![diagram](assets/diagram.png) and ![photo](./img/photo.jpg)."
    refs = scanner.scan_markdown(text)
    check("finds 2 inline images", len(refs) == 2, f"got {len(refs)}")
    if refs:
        check("first raw path", refs[0].raw == "assets/diagram.png", refs[0].raw)
        check("offset points at path", text[refs[0].start:refs[0].end] == "assets/diagram.png")


def test_markdown_reference_style() -> None:
    section("scanner: Markdown reference-style (end-to-end correctness)")
    text = (
        "Intro.\n\n"
        "![logo][logo-ref]\n\n"
        "[logo-ref]: assets/logo.png\n"
    )
    refs = scanner.scan_markdown(text)
    logo_refs = [r for r in refs if r.raw == "assets/logo.png"]
    check("resolves reference to url", len(logo_refs) == 1,
          str([(r.raw, r.syntax) for r in refs]))
    if logo_refs:
        r = logo_refs[0]
        check("reference syntax tagged", r.syntax == "md_reference")
        # The span must cover the WHOLE ![logo][logo-ref] usage so the
        # replacer can rewrite it to inline form. Off-by-one here breaks
        # the produced Markdown silently.
        covered = text[r.start:r.end]
        check("span covers whole usage", covered == "![logo][logo-ref]", repr(covered))

    # End-to-end: after replacement the doc must contain a valid inline
    # image ![logo](url), NOT a broken ![logo][url].
    url_map = {"assets/logo.png": "https://cdn.example.com/logo.png"}
    new_text, replaced, unchanged = apply_replacements(text, refs, url_map)
    check("replaced count", len(replaced) == 1)
    check("produces inline image", "![logo](https://cdn.example.com/logo.png)" in new_text)
    check("no broken ref form", "![logo][https" not in new_text)
    # The [logo-ref]: definition is now an orphan; check_links must still
    # catch it as residue (this is the CRITICAL regression guard).
    residue = scanner.find_local_path_residue(new_text)
    check("check_links catches orphan definition",
          any(r.raw == "assets/logo.png" for r in residue),
          str([r.raw for r in residue]))


def test_remote_urls_skipped() -> None:
    section("scanner: returns all refs; caller classifies remote")
    text = (
        "![](https://example.com/a.png) "
        "![](http://foo.com/b.jpg) "
        "![](assets/local.png)"
    )
    refs = scanner.scan_markdown(text)
    # Scanner returns ALL refs; filtering is the pipeline's job.
    check("scanner returns 3 refs (no filtering)", len(refs) == 3, f"got {len(refs)}")
    raws = [r.raw for r in refs]
    check("remote https kept in list", "https://example.com/a.png" in raws)
    check("remote http kept in list", "http://foo.com/b.jpg" in raws)
    check("local kept in list", "assets/local.png" in raws)
    # The classifier helper is what the pipeline uses:
    local_only = [r for r in refs if not scanner.is_remote_or_special(r.raw)]
    check("classifier isolates 1 local", len(local_only) == 1, f"got {len(local_only)}")
    if local_only:
        check("local path is assets/local.png", local_only[0].raw == "assets/local.png")


def test_code_fence_masked() -> None:
    section("scanner: code fences are masked")
    text = (
        "```python\n"
        "![](assets/inside_code.png)\n"
        "```\n"
        "Inline code `![](assets/inline.png)` here.\n"
        "\n"
        "![](assets/outside.png)\n"
    )
    refs = scanner.scan_markdown(text)
    paths = [r.raw for r in refs]
    check("code-fence image skipped", "assets/inside_code.png" not in paths, str(paths))
    check("inline-code image skipped", "assets/inline.png" not in paths, str(paths))
    check("outside image kept", "assets/outside.png" in paths, str(paths))


def test_code_fence_longer_closing() -> None:
    section("scanner: 4-backtick fence not closed by 3 backticks")
    # CommonMark: a 4-backtick fence needs >=4 backticks to close.
    text = (
        "````\n"
        "![](assets/inside.png)\n"
        "```\n"
        "still inside the fence\n"
        "````\n"
        "![](assets/outside.png)\n"
    )
    refs = scanner.scan_markdown(text)
    paths = [r.raw for r in refs]
    check("3-backtick does not close 4-backtick fence",
          "assets/inside.png" not in paths, str(paths))
    check("outside image kept", "assets/outside.png" in paths, str(paths))


def test_alt_with_escaped_bracket() -> None:
    section("scanner: alt text with escaped ] bracket")
    # CommonMark allows backslash-escaped ] inside alt text.
    text = r"![Fig. 1 \[detail\]](assets/fig.png)"
    refs = scanner.scan_markdown(text)
    check("finds image despite escaped brackets", len(refs) == 1, f"got {len(refs)}")
    if refs:
        check("path correct", refs[0].raw == "assets/fig.png", refs[0].raw)


def test_path_with_spaces_angle_bracket() -> None:
    section("scanner: angle-bracket path with spaces")
    text = "![](</assets/my file.png>) and ![](assets/normal.png)"
    refs = scanner.scan_markdown(text)
    raws = [r.raw for r in refs]
    check("angle-bracket path found", "/assets/my file.png" in raws, str(raws))
    check("normal path still found", "assets/normal.png" in raws, str(raws))


def test_single_quote_title() -> None:
    section("scanner: single-quoted title")
    text = "![](assets/a.png 'a title')"
    refs = scanner.scan_markdown(text)
    check("image with single-quote title found", len(refs) == 1, f"got {len(refs)}")
    if refs:
        check("path correct", refs[0].raw == "assets/a.png", refs[0].raw)


def test_resolve_windows_backslash() -> None:
    section("resolver: Windows backslash path")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "assets").mkdir()
        (base / "assets" / "x.png").write_bytes(PNG_BYTES)
        resolved = scanner.resolve_local("assets\\x.png", base)
        check("backslash path resolves", resolved is not None, str(resolved))


def test_manifest_corruption_warns() -> None:
    section("manifest: corrupt file warns to stderr")
    import contextlib
    import io as _io
    with tempfile.TemporaryDirectory() as td:
        mpath = Path(td) / "m.json"
        mpath.write_text("{not valid", encoding="utf-8")
        err_buf = _io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            m = Manifest.load(mpath)
        err_out = err_buf.getvalue()
        check("load does not crash", m.entries == {})
        check("warning printed to stderr", "Warning" in err_out and "manifest" in err_out,
              repr(err_out[:80]))


def test_html_img_src() -> None:
    section("scanner: HTML <img src>")
    text = '<img src="assets/banner.png" alt="banner"> <img src="https://x.com/y.png">'
    refs = scanner.scan_html(text)
    local = [r for r in refs if r.raw == "assets/banner.png"]
    check("finds local src", len(local) == 1, str([r.raw for r in refs]))
    if local:
        span_ok = text[local[0].start:local[0].end] == "assets/banner.png"
        check("html_attr offset correct", span_ok)


def test_srcset_multiple() -> None:
    section("scanner: srcset with multiple URLs")
    text = '<img srcset="assets/hi.png 2x, assets/lo.png 1x">'
    refs = scanner.scan_html(text)
    raws = {r.raw for r in refs}
    check("both srcset URLs found", "assets/hi.png" in raws and "assets/lo.png" in raws,
          str(raws))


def test_css_url() -> None:
    section("scanner: CSS url()")
    text = '<style>.hero{background:url(assets/bg.png)}</style>'
    refs = scanner.scan_html(text)
    check("css_url found", any(r.raw == "assets/bg.png" for r in refs),
          str([r.raw for r in refs]))


def test_resolve_local() -> None:
    section("resolver: relative path resolution")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "assets").mkdir()
        p = base / "assets" / "x.png"
        p.write_bytes(PNG_BYTES)
        resolved = scanner.resolve_local("assets/x.png", base)
        check("resolves existing file", resolved == p.resolve(), str(resolved))
        check("returns None for missing", scanner.resolve_local("nope.png", base) is None)
        check("returns None for http", scanner.resolve_local("https://a.com/x.png", base) is None)


def test_replacer_offsets() -> None:
    section("replacer: offset correctness")
    text = "A ![x](a.png) B ![y](b.png) C"
    refs = scanner.scan_markdown(text)
    url_map = {"a.png": "https://cdn/1.png", "b.png": "https://cdn/2.png"}
    new_text, replaced, unchanged = apply_replacements(text, refs, url_map)
    check("both replaced", len(replaced) == 2, str(len(replaced)))
    check("none unchanged", len(unchanged) == 0)
    check("text contains new urls", "https://cdn/1.png" in new_text and "https://cdn/2.png" in new_text)


def test_replacer_partial_failure() -> None:
    section("replacer: partial failure keeps local path")
    text = "![x](a.png) ![y](b.png)"
    refs = scanner.scan_markdown(text)
    # Only a.png has a URL; b.png failed and must stay local.
    url_map = {"a.png": "https://cdn/1.png"}
    new_text, replaced, unchanged = apply_replacements(text, refs, url_map)
    check("one replaced", len(replaced) == 1)
    check("one unchanged", len(unchanged) == 1)
    check("b.png still local", "b.png" in new_text)
    check("a.png is now url", "https://cdn/1.png" in new_text and "a.png" not in new_text)


def test_manifest_dedup() -> None:
    section("manifest: dedup by hash")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "img.png"
        p.write_bytes(PNG_BYTES)
        h = manifest_mod.file_hash(str(p))
        size = manifest_mod.file_size(str(p))
        mpath = Path(td) / ".upload-manifest.json"
        m = Manifest.load(mpath)
        # First lookup: nothing.
        check("fresh lookup returns None", m.lookup(str(p), h) is None)
        m.record(str(p), "https://cdn/x.png", h, size)
        # Second lookup: hit.
        check("second lookup returns url", m.lookup(str(p), h) == "https://cdn/x.png")
        # Hash mismatch: re-upload needed.
        check("hash mismatch returns None", m.lookup(str(p), "deadbeef") is None)
        m.save()
        # Reload from disk.
        m2 = Manifest.load(mpath)
        check("persisted to disk", m2.lookup(str(p), h) == "https://cdn/x.png")



def test_end_to_end() -> None:
    section("END-TO-END: file -> uploaded.md via FakeUploader")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "assets").mkdir()
        for name in ("a.png", "b.png"):
            (base / "assets" / name).write_bytes(PNG_BYTES)
        md = base / "lecture.md"
        md.write_text(
            "# Title\n\n![a](assets/a.png)\n\n![b](assets/b.png)\n\n"
            "![remote](https://x.com/remote.png)\n",
            encoding="utf-8",
        )

        # Import the main module functions directly.
        sys.path.insert(0, str(SCRIPTS_DIR))
        import upload_images as ui  # noqa: E402

        fake = FakeUploader()
        mpath = base / ".upload-manifest.json"
        manifest = Manifest.load(mpath)

        args = ui.build_parser().parse_args(
            [str(md), "--provider", "fake", "--in-place", "--retries", "1"]
        )
        # Bypass config loading by monkey-patching get_uploader via process_document.
        fr = ui.process_document(md, fake, manifest, args)
        check("uploaded 2", fr.uploaded == 2, f"uploaded={fr.uploaded}")
        check("skipped 1 remote", fr.skipped_remote == 1, f"skipped_remote={fr.skipped_remote}")
        check("0 failed", fr.failed == 0)
        out = md.read_text(encoding="utf-8")
        check("local paths gone", "assets/a.png" not in out and "assets/b.png" not in out)
        check("hosted urls present", "https://cdn.fake/" in out)
        check("remote untouched", "https://x.com/remote.png" in out)


def test_end_to_end_dry_run() -> None:
    section("END-TO-END: dry-run uploads nothing")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "assets").mkdir()
        (base / "assets" / "a.png").write_bytes(PNG_BYTES)
        md = base / "lec.md"
        md.write_text("![](assets/a.png)", encoding="utf-8")

        import upload_images as ui  # noqa: E402
        fake = FakeUploader()
        manifest = Manifest.load(base / ".upload-manifest.json")
        args = ui.build_parser().parse_args([str(md), "--provider", "fake", "--dry-run"])
        fr = ui.process_document(md, fake, manifest, args)
        check("dry-run counts as would-upload", fr.uploaded == 1)
        check("fake uploader untouched", len(fake.uploads) == 0)
        check("no output written", fr.output is None)
        # Original file unchanged.
        check("original untouched", "assets/a.png" in md.read_text(encoding="utf-8"))


def test_end_to_end_manifest_reuse() -> None:
    section("END-TO-END: second run reuses manifest (no re-upload)")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "assets").mkdir()
        (base / "assets" / "a.png").write_bytes(PNG_BYTES)
        md = base / "lec.md"
        md.write_text("![](assets/a.png)", encoding="utf-8")

        import upload_images as ui  # noqa: E402
        fake = FakeUploader()
        mpath = base / ".upload-manifest.json"
        # NOT in-place: original .md keeps local paths across runs, so the
        # second run scans the same local path and can hit the manifest.
        args = ui.build_parser().parse_args(
            [str(md), "--provider", "fake", "--retries", "1"]
        )
        # Run 1: upload.
        m1 = Manifest.load(mpath)
        ui.process_document(md, fake, m1, args)
        m1.save()
        check("run 1 uploaded once", len(fake.uploads) == 1, f"{len(fake.uploads)}")
        # Run 2: same local file, manifest has it -> reuse, 0 new uploads.
        m2 = Manifest.load(mpath)
        fr2 = ui.process_document(md, fake, m2, args)
        check("run 2 reused, 0 new uploads", len(fake.uploads) == 1, f"{len(fake.uploads)}")
        check("run 2 reused counter", fr2.reused == 1, f"reused={fr2.reused}")


def main() -> int:
    print("=" * 60)
    print("md-image-uploader smoke tests")
    print("=" * 60)
    test_markdown_inline()
    test_markdown_reference_style()
    test_remote_urls_skipped()
    test_code_fence_masked()
    test_code_fence_longer_closing()
    test_alt_with_escaped_bracket()
    test_path_with_spaces_angle_bracket()
    test_single_quote_title()
    test_html_img_src()
    test_srcset_multiple()
    test_css_url()
    test_resolve_local()
    test_resolve_windows_backslash()
    test_replacer_offsets()
    test_replacer_partial_failure()
    test_manifest_dedup()
    test_manifest_corruption_warns()
    test_end_to_end()
    test_end_to_end_dry_run()
    test_end_to_end_manifest_reuse()

    print(f"\n{'=' * 60}")
    print(f"  PASS: {PASS}    FAIL: {FAIL}")
    print(f"{'=' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
