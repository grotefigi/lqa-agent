"""The review pipeline.

Design rule: the model is an *advisor*, never the verdict.
Deterministic checks (glossary, leakage, length, balance) always run and are
authoritative, because they are reproducible and auditable. The model adds the
judgement calls a regex cannot make - naturalness, tone, register - and its
output is merged in, clearly labelled with which engine found what.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

from .glossary import GlossaryEntry, check_glossary, required_targets
from .providers import Provider, ProviderError, heuristic_review

SEVERITY_WEIGHT = {"high": 12.0, "medium": 6.0, "low": 2.5}
KIND_WEIGHT = {
    "untranslated": 1.4,
    "terminology": 1.35,
    "omission": 1.3,
    "empty": 1.5,
    "accuracy": 1.2,
    "fluency": 0.9,
    "formatting": 0.8,
    "overtranslation": 0.8,
}

SYSTEM_PROMPT = (
    "You are a senior localization reviewer for Romanian to English and "
    "English to Romanian commercial translation. You are terse, specific and "
    "you never invent problems to look useful. You reply with JSON only.\n"
    "Schema: {\"issues\": [{\"kind\": one of "
    "[accuracy, fluency, terminology, register, formatting, omission, untranslated], "
    "\"severity\": one of [high, medium, low], \"detail\": string}], "
    "\"naturalness\": 0-10, \"accuracy\": 0-10, \"register_ok\": boolean, "
    "\"suggested_target\": string}"
)


@dataclass
class Segment:
    id: str
    source: str
    target: str
    note: str = ""


@dataclass
class SegmentResult:
    id: str
    source: str
    target: str
    score: float
    issues: list[dict] = field(default_factory=list)
    engines: list[str] = field(default_factory=list)
    naturalness: float | None = None
    accuracy: float | None = None
    register_ok: bool | None = None
    suggested_target: str = ""
    model_error: str = ""

    @property
    def status(self) -> str:
        if any(i.get("severity") == "high" for i in self.issues):
            return "block"
        if self.issues:
            return "review"
        return "pass"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status
        return d


@dataclass
class Report:
    segments: list[SegmentResult]
    provider: str
    source_lang: str
    target_lang: str

    @property
    def score(self) -> float:
        if not self.segments:
            return 100.0
        return round(sum(s.score for s in self.segments) / len(self.segments), 1)

    @property
    def counts(self) -> dict:
        out = {"pass": 0, "review": 0, "block": 0}
        for s in self.segments:
            out[s.status] += 1
        return out

    def worst(self, n: int = 5) -> list[SegmentResult]:
        return sorted(self.segments, key=lambda s: s.score)[:n]

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "score": self.score,
            "counts": self.counts,
            "segments": [s.to_dict() for s in self.segments],
        }


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _parse_model_json(raw: str) -> dict:
    if not raw:
        return {}
    m = _JSON_BLOCK.search(raw)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # tolerate trailing commas, a common small-model artefact
        cleaned = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


def score_from_issues(issues: list[dict]) -> float:
    """100 minus weighted penalties, floored at 0."""
    penalty = 0.0
    for issue in issues:
        if issue.get("engine") == "model" and issue.get("_deduped"):
            continue
        sev = SEVERITY_WEIGHT.get(str(issue.get("severity", "low")).lower(), 2.5)
        kind = KIND_WEIGHT.get(str(issue.get("kind", "")).lower(), 1.0)
        penalty += sev * kind
    return max(0.0, round(100.0 - penalty, 1))


def _dedupe(issues: list[dict]) -> list[dict]:
    """Collapse duplicate findings, preferring the deterministic engine.

    Terminology is special-cased: the same missing glossary term is reported by
    the authoritative checker and again by whatever model/heuristic layer ran,
    with different wording. Keying on the expected term merges them instead of
    charging the penalty twice.
    """
    seen: dict[tuple, dict] = {}
    for issue in issues:
        kind = str(issue.get("kind", "")).lower()
        if kind == "terminology":
            key = (kind, str(issue.get("expected") or issue.get("term") or "").lower())
        else:
            key = (kind, re.sub(r"\s+", " ", str(issue.get("detail", "")).lower())[:80])
        if key in seen:
            if seen[key].get("engine") == "model" and issue.get("engine") == "heuristic":
                seen[key] = issue
            continue
        seen[key] = issue
    return list(seen.values())


def review_segment(provider: Provider, seg: Segment, glossary: dict[str, GlossaryEntry],
                   source_lang: str = "ro", target_lang: str = "en",
                   use_model: bool = True) -> SegmentResult:
    must_terms = required_targets(glossary, seg.source)
    engines: list[str] = []

    # --- authoritative, deterministic layer -------------------------------
    deterministic = check_glossary(glossary, seg.source, seg.target)
    for issue in deterministic:
        issue["engine"] = "heuristic"
    det_extra = heuristic_review(seg.source, seg.target, source_lang, target_lang, must_terms)["issues"]
    for issue in det_extra:
        issue["engine"] = "heuristic"
    engines.append("heuristic")

    issues = deterministic + det_extra
    naturalness = accuracy = None
    register_ok = None
    suggested = ""
    model_error = ""

    # --- advisory model layer ---------------------------------------------
    if use_model:
        payload = json.dumps({
            "source_lang": source_lang,
            "target_lang": target_lang,
            "source": seg.source,
            "target": seg.target,
            "must_terms": must_terms,
            "note": seg.note,
        }, ensure_ascii=False)
        try:
            raw = provider.complete(SYSTEM_PROMPT, payload)
            parsed = _parse_model_json(raw)
            if parsed:
                engines.append(provider.name)
                for issue in parsed.get("issues", []) or []:
                    if not isinstance(issue, dict) or not issue.get("detail"):
                        continue
                    issue["engine"] = "model"
                    issues.append(issue)
                naturalness = parsed.get("naturalness")
                accuracy = parsed.get("accuracy")
                register_ok = parsed.get("register_ok")
                suggested = str(parsed.get("suggested_target") or "")
            else:
                engines.append(f"{provider.name}:unparsed")
        except ProviderError as exc:
            model_error = str(exc)
            engines.append(f"{provider.name}:error")

    issues = _dedupe(issues)
    return SegmentResult(
        id=seg.id,
        source=seg.source,
        target=seg.target,
        score=score_from_issues(issues),
        issues=issues,
        engines=engines,
        naturalness=naturalness,
        accuracy=accuracy,
        register_ok=register_ok,
        suggested_target=suggested,
        model_error=model_error,
    )


def review_document(provider: Provider, segments: list[Segment],
                    glossary: dict[str, GlossaryEntry],
                    source_lang: str = "ro", target_lang: str = "en",
                    use_model: bool = True) -> Report:
    results = [
        review_segment(provider, seg, glossary, source_lang, target_lang, use_model)
        for seg in segments
    ]
    return Report(
        segments=results,
        provider=provider.name if use_model else "heuristic-only",
        source_lang=source_lang,
        target_lang=target_lang,
    )
