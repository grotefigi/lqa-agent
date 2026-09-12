"""Terminology / glossary handling.

A translation can be fluent and still be wrong: the client's glossary term was
ignored. That is the single most expensive class of localization bug because it
is invisible to a reader who does not know the brand.

Matching Romanian is not a substring problem. Romanian inflects heavily:
the glossary term "cont curent" must still be detected inside "soldul
contului curent". Naive substring matching silently misses most real hits.
This module therefore does diacritic-folded, suffix-aware token matching.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass

# Romanian inflectional endings. A target/source token matches a glossary token
# when it is that token plus one of these endings - which is deliberately
# narrower than "startswith", so glossary "cont" does NOT match "contact".
RO_SUFFIXES = (
    "urilor", "urile", "ului", "ilor", "iilor", "ele", "ile", "uri", "ate",
    "ii", "ul", "ea", "ei", "lor", "le", "lui", "a", "e", "i", "o", "u",
    "ă", "â", "î", "ș", "ț", "s", "t",
)
_SUFFIXES = tuple(sorted(set(RO_SUFFIXES), key=len, reverse=True))

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def strip_diacritics(text: str) -> str:
    """â/î/ș/ț/ă -> a/i/s/t/a, so matching survives inconsistent input."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    return strip_diacritics(text or "").lower()


def tokens(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def _token_matches(glossary_token: str, text_token: str) -> bool:
    if glossary_token == text_token:
        return True
    # only allow the *text* side to be inflected: glossary "cont" ~ "contului"
    if len(glossary_token) < 3:
        return False
    if text_token.startswith(glossary_token):
        if text_token[len(glossary_token):] in _SUFFIXES:
            return True
    return False


def term_present(term: str, text: str, case_sensitive: bool = False) -> bool:
    """Is `term` present in `text`, tolerating Romanian inflection?"""
    if not term or not text:
        return False
    if case_sensitive:
        return term in text
    wanted = tokens(term)
    if not wanted:
        return False
    have = tokens(text)
    if not have:
        return False
    used: set[int] = set()
    for want in wanted:
        for i, got in enumerate(have):
            if i in used:
                continue
            if _token_matches(want, got):
                used.add(i)
                break
        else:
            return False
    return True


@dataclass
class GlossaryEntry:
    source: str
    target: str
    note: str = ""
    case_sensitive: bool = False


def load_glossary(text: str) -> dict[str, GlossaryEntry]:
    """Parse a glossary from CSV or TSV.

    Accepted header: source,target[,note][,case_sensitive]
    The header row is optional.
    """
    text = (text or "").strip()
    if not text:
        return {}

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","

    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        return {}

    header = [c.strip().lower() for c in rows[0]]
    has_header = bool({"source", "term", "src"} & set(header))
    idx: dict[str, int] = {}
    if has_header:
        idx = {name: i for i, name in enumerate(header)}
        body = rows[1:]
    else:
        body = rows

    def cell(row: list[str], *names: str) -> str:
        for name in names:
            if name in idx and idx[name] < len(row):
                return row[idx[name]].strip()
        return ""

    out: dict[str, GlossaryEntry] = {}
    for row in body:
        if not row or not any(c.strip() for c in row):
            continue
        if has_header:
            src = cell(row, "source", "term", "src")
            tgt = cell(row, "target", "translation", "dst")
            note = cell(row, "note", "notes", "comment")
            cs = cell(row, "case_sensitive", "casesensitive").lower() in {"1", "true", "yes"}
        else:
            src = row[0].strip()
            tgt = row[1].strip() if len(row) > 1 else ""
            note = row[2].strip() if len(row) > 2 else ""
            cs = False
        if not src:
            continue
        out[src] = GlossaryEntry(source=src, target=tgt, note=note, case_sensitive=cs)
    return out


def required_targets(glossary: dict[str, GlossaryEntry], source_text: str) -> list[str]:
    """Which target terms must appear, given what is present in the source.

    Only terms whose SOURCE form occurs in the source segment are required -
    demanding every glossary term in every segment would produce nonsense.
    """
    required: list[str] = []
    for entry in glossary.values():
        if not entry.target:
            continue
        if term_present(entry.source, source_text, entry.case_sensitive):
            required.append(entry.target)
    return required


def check_glossary(glossary: dict[str, GlossaryEntry], source_text: str,
                   target_text: str) -> list[dict]:
    """Terminology violations as report-ready dicts."""
    violations: list[dict] = []
    for entry in glossary.values():
        if not entry.target:
            continue
        if not term_present(entry.source, source_text, entry.case_sensitive):
            continue
        if term_present(entry.target, target_text, entry.case_sensitive):
            continue
        violations.append({
            "kind": "terminology",
            "severity": "high",
            "term": entry.source,
            "expected": entry.target,
            "note": entry.note,
            "detail": (
                f"source term {entry.source!r} requires {entry.target!r} in the target, "
                f"but it is missing"
            ),
        })
    return violations
