"""Replacer: surgically rewrite image paths in a document using offsets.

Why offset-based and not str.replace()
--------------------------------------
A single image path can appear multiple times in a document (a figure reused
in prose, a caption). ``str.replace`` would rewrite all of them at once, but
that is wrong when only some occurrences were successfully uploaded: failed
uploads must keep their local path so the user can retry.

We sort all replacements by start offset descending and splice each one in.
Descending order means earlier offsets stay valid as later (already-processed)
tail of the string grows or shrinks. This is O(n) and deterministic.
"""

from __future__ import annotations

from dataclasses import replace as dataclass_replace

from scanner import ImageRef


def apply_replacements(
    text: str,
    refs: list[ImageRef],
    url_map: dict[str, str],
) -> tuple[str, list[ImageRef], list[ImageRef]]:
    """Rewrite *text*, replacing each ref's raw path with its hosted URL.

    Args:
        text: Original document text.
        refs: ImageRefs found by the scanner (carry (start, end) offsets).
        url_map: Mapping from the ref's raw path -> hosted URL. Refs whose
            raw path is not in this map (upload failed or was skipped) are
            left untouched.

    Returns:
        (new_text, replaced, unchanged):
            *new_text* is the rewritten document;
            *replaced* holds refs whose path was swapped for a URL;
            *unchanged* holds refs that were left as-is.

    Notes:
        - Offsets in *refs* are trusted from the scan pass; we do not rescan.
        - When a path appears multiple times, each occurrence is handled
          independently based on its own offset, so partial replacement is
          safe.
        - Reference-style images (``md_reference``) are rewritten to inline
          form ``![alt](url)`` covering the whole original ``![alt][id]``
          span, because the [id] slot cannot legally hold a URL.
    """
    pending: list[tuple[int, int, str]] = []  # (start, end, new_text)
    replaced: list[ImageRef] = []
    unchanged: list[ImageRef] = []

    for ref in refs:
        url = url_map.get(ref.raw) or url_map.get(ref.clean_path)
        if not url:
            unchanged.append(ref)
            continue

        if ref.syntax == "md_reference":
            # Rebuild as inline image: ![alt](url). This replaces the entire
            # ![alt][id] usage and leaves the [id]: definition as a harmless
            # orphan (it still points at a local path, but no usage references
            # it anymore). Escaping ] inside alt is not needed for the URL.
            new_text = f"![{ref.alt}]({url})"
        else:
            # Default: swap the path/URL in place.
            new_text = url
        pending.append((ref.start, ref.end, new_text))
        replaced.append(dataclass_replace(ref, raw=url))

    # Sort descending by start so splicing the tail never shifts offsets we
    # still need to splice in the head.
    pending.sort(key=lambda t: t[0], reverse=True)

    buf = text
    for start, end, new in pending:
        buf = buf[:start] + new + buf[end:]

    return buf, replaced, unchanged
