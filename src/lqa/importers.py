"""Import segments from the formats translation work actually arrives in.

LQA originally accepted one hand-rolled JSON shape. Real jobs arrive as:

  * **TMX**    - translation memory exchange, what a TM tool exports
  * **XLIFF**  - the OASIS standard CAT tools hand to translators (1.2 and 2.0)
  * **JSON**   - our own simple list, still supported

Standard library only. Namespaces in XLIFF are handled by matching on the
local tag name, because exporters vary wildly in prefixing and a strict
namespace match rejects otherwise valid files.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from .reviewer import Segment


class ImportError_(ValueError):
    """Raised when a file cannot be parsed as any supported format."""


def _local(tag: str) -> str:
    """Strip an XML namespace: '{urn:oasis:...}source' -> 'source'."""
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _text(elem) -> str:
    """All descendant text of an element, whitespace-normalised."""
    if elem is None:
        return ""
    return re.sub(r"\s+", " ", "".join(elem.itertext())).strip()


# --------------------------------------------------------------------------
# TMX
# --------------------------------------------------------------------------

def parse_tmx(text: str, source_lang: str = "ro", target_lang: str = "en") -> list[Segment]:
    """Parse a TMX translation memory into segments.

    A <tu> holds one <tuv> per language. We pick the tuv matching the requested
    languages, falling back to 'first tuv = source, second = target' when the
    language codes do not match, since real memories carry codes like
    'ro-RO', 'ROU' or 'en-GB'.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ImportError_(f"TMX is not well-formed XML: {exc}") from exc

    if _local(root.tag) != "tmx":
        raise ImportError_("not a TMX file (root element is not <tmx>)")

    def lang_match(code: str, want: str) -> bool:
        c = (code or "").lower()
        w = (want or "").lower()
        return bool(c) and (c == w or c.startswith(w + "-") or c.startswith(w))

    out: list[Segment] = []
    for n, tu in enumerate(root.iter(), start=1):
        if _local(tu.tag) != "tu":
            continue
        tuvs = [c for c in tu if _local(c.tag) == "tuv"]
        if not tuvs:
            continue

        def seg_of(tuv) -> str:
            for c in tuv:
                if _local(c.tag) == "seg":
                    return _text(c)
            return ""

        src = tgt = ""
        for tuv in tuvs:
            code = tuv.get("{http://www.w3.org/XML/1998/namespace}lang") or tuv.get("lang") or ""
            if lang_match(code, source_lang):
                src = src or seg_of(tuv)
            elif lang_match(code, target_lang):
                tgt = tgt or seg_of(tuv)

        if not src and not tgt and len(tuvs) >= 2:
            src, tgt = seg_of(tuvs[0]), seg_of(tuvs[1])

        if not src and not tgt:
            continue

        out.append(Segment(
            id=tu.get("tuid") or tu.get("id") or f"tu{n}",
            source=src,
            target=tgt,
            note=_text(tu.find("{*}note")) if tu.find("{*}note") is not None else "",
        ))
    return out


# --------------------------------------------------------------------------
# XLIFF
# --------------------------------------------------------------------------

def parse_xliff(text: str, source_lang: str = "ro", target_lang: str = "en") -> list[Segment]:
    """Parse XLIFF 1.2 or 2.0 into segments.

    1.2: <xliff><file><body><trans-unit id><source/><target/>
    2.0: <xliff><file><unit id><segment><source/><target/>
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ImportError_(f"XLIFF is not well-formed XML: {exc}") from exc

    if _local(root.tag) != "xliff":
        raise ImportError_("not an XLIFF file (root element is not <xliff>)")

    version = (root.get("version") or "").strip()

    out: list[Segment] = []
    # <trans-unit> (1.2) and <unit> (2.0) both carry id + source/target beneath
    for n, node in enumerate(root.iter(), start=1):
        local = _local(node.tag)
        if local not in ("trans-unit", "unit"):
            continue

        src_el = tgt_el = None
        for c in node.iter():
            lc = _local(c.tag)
            if lc == "source" and src_el is None:
                src_el = c
            elif lc == "target" and tgt_el is None:
                tgt_el = c

        src, tgt = _text(src_el), _text(tgt_el)
        if not src and not tgt:
            continue

        # XLIFF often carries <note> inside <unit>/<trans-unit>
        note_el = None
        for c in node.iter():
            if _local(c.tag) == "note":
                note_el = c
                break

        out.append(Segment(
            id=node.get("id") or node.get("resname") or f"u{n}",
            source=src,
            target=tgt,
            note=_text(note_el),
        ))

    if not out:
        raise ImportError_(
            f"XLIFF {version or '(unknown version)'} parsed but contained no "
            "<trans-unit>/<unit> elements with source or target text"
        )
    return out


# --------------------------------------------------------------------------
# JSON (the original format)
# --------------------------------------------------------------------------

def parse_json(text: str) -> list[Segment]:
    data = json.loads(text)
    if isinstance(data, dict):
        if "segments" not in data:
            raise ImportError_(
                "JSON object has no 'segments' key; expected a list of segments "
                "or {'segments': [...]}"
            )
        data = data["segments"]
    if not isinstance(data, list):
        raise ImportError_("JSON input must be a list of segments, or {'segments': [...]}")
    out: list[Segment] = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ImportError_(f"segment {i} is not an object")
        out.append(Segment(
            id=str(item.get("id", i)),
            source=str(item.get("source", "")),
            target=str(item.get("target", "")),
            note=str(item.get("note", "")),
        ))
    return out


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def detect_format(path: str, text: str) -> str:
    """Decide the format from the extension, then from the content."""
    low = (path or "").lower()
    if low.endswith(".tmx"):
        return "tmx"
    if low.endswith(".xlf") or low.endswith(".xliff"):
        return "xliff"
    if low.endswith(".json"):
        return "json"
    # extension unknown or missing - sniff the content
    head = text.lstrip()[:400].lower()
    if head.startswith("<?xml") or head.startswith("<tmx") or head.startswith("<xliff"):
        if "<tmx" in head:
            return "tmx"
        if "<xliff" in head:
            return "xliff"
        # raw XML without a declaration we recognise - look a little deeper
        if re.search(r"<\s*tmx[\s>]", text[:2000], re.I):
            return "tmx"
        if re.search(r"<\s*xliff[\s>]", text[:2000], re.I):
            return "xliff"
    if head.startswith("{") or head.startswith("["):
        return "json"
    raise ImportError_(
        "could not detect the input format; expected .tmx, .xlf/.xliff or .json "
        "(or XML/JSON content)"
    )


def load_segments(path: str, source_lang: str = "ro", target_lang: str = "en") -> list[Segment]:
    """Load segments from TMX, XLIFF or JSON, chosen automatically."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if not text.strip():
        raise ImportError_(f"input file is empty: {path}")

    fmt = detect_format(path, text)
    if fmt == "tmx":
        segs = parse_tmx(text, source_lang, target_lang)
    elif fmt == "xliff":
        segs = parse_xliff(text, source_lang, target_lang)
    else:
        segs = parse_json(text)

    if not segs:
        raise ImportError_(
            f"{fmt.upper()} file contained no translatable segments with text: {path}"
        )
    return segs
