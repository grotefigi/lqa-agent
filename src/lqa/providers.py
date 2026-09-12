"""LLM providers.

Primary path: Nebius Token Factory, an OpenAI-compatible endpoint serving
NVIDIA open-source models on Nebius GPU infrastructure (the hackathon's
required stack).

Fallback path: a deterministic offline provider so the pipeline, the CLI and
the test suite all run with zero credits and zero network. This matters -
a submission that only works with a funded API key is not demonstrable.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .glossary import normalize

NEBIUS_BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1")
NEBIUS_MODEL = os.environ.get("NEBIUS_MODEL", "meta-llama/Llama-3.3-70B-Instruct")


class ProviderError(RuntimeError):
    pass


class Provider:
    name = "base"

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class NebiusProvider(Provider):
    """Nebius Token Factory chat-completions client (OpenAI-compatible)."""

    name = "nebius"

    def __init__(self, api_key: str, model: str = NEBIUS_MODEL, base_url: str = NEBIUS_BASE_URL,
                 timeout: int = 90):
        if not api_key:
            raise ProviderError("NEBIUS_API_KEY is empty")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise ProviderError(f"nebius HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # network, DNS, timeout
            raise ProviderError(f"nebius request failed: {type(exc).__name__}: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected nebius response shape: {str(body)[:300]}") from exc


# --- offline heuristics -----------------------------------------------------
# These run when there is no API key, and they are also used to *verify* the
# LLM's claims: a model that says "terminology OK" while a glossary term is
# missing is wrong, and the deterministic checker catches it.

FUNCTION_WORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
}

# Romanian function words that must NOT survive into an English target.
# Deliberately excludes tokens that are also real English words ("care", "la",
# "de") to avoid flagging legitimate English output as leakage.
RO_LEAKS = {
    "si", "sau", "este", "sunt", "pentru", "acest", "aceasta",
    "aceste", "acestia", "cu", "din", "prin", "fara", "catre",
    "noastre", "nostru", "noastra", "dumneavoastra", "va",
    "puteti", "rugam", "echipa", "contactati", "multumim", "dvs",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-zĂÂÎȘȚăâîșțÄÖÜäöüß'-]+", text or "")


def heuristic_review(source: str, target: str, source_lang: str, target_lang: str,
                     must_terms: list[str]) -> dict:
    """Deterministic quality signals, usable with no model at all."""
    issues: list[dict] = []
    src_t = _tokens(source)
    tgt_t = _tokens(target)

    # 1. untranslated source-language leakage into the target
    if target_lang.lower().startswith("en") and source_lang.lower().startswith("ro"):
        leaked = sorted({normalize(t) for t in tgt_t if normalize(t) in RO_LEAKS})
        if leaked:
            issues.append({
                "kind": "untranslated",
                "severity": "high",
                "detail": "Romanian function words left in the English target: " + ", ".join(leaked),
            })

    # 2. length ratio - a target wildly off the source length is usually a drop
    if src_t and tgt_t:
        ratio = len(tgt_t) / len(src_t)
        if ratio < 0.55:
            issues.append({
                "kind": "omission",
                "severity": "high",
                "detail": f"target is only {ratio:.0%} of source length - probable dropped content",
            })
        elif ratio > 2.2:
            issues.append({
                "kind": "overtranslation",
                "severity": "medium",
                "detail": f"target is {ratio:.0%} of source length - probable padding",
            })

    # 3. empty / whitespace target
    if not target.strip():
        issues.append({"kind": "empty", "severity": "high", "detail": "target segment is empty"})

    # 4. glossary terms that were required but are absent
    low = target.lower()
    for term in must_terms:
        if term and term.lower() not in low:
            issues.append({
                "kind": "terminology",
                "severity": "high",
                "expected": term,
                "detail": f"required glossary term missing from target: {term!r}",
            })

    # 5. doubled words ("the the") - classic MT artefact. Function words are
    # NOT excluded here: "the the" is the single most common instance of it.
    for a, b in zip(tgt_t, tgt_t[1:]):
        if a.lower() == b.lower():
            issues.append({
                "kind": "fluency",
                "severity": "low",
                "detail": f"duplicated word {a!r}",
            })
            break

    # 6. unbalanced brackets / stray markup
    for open_c, close_c in (("(", ")"), ("[", "]"), ("{", "}")):
        if target.count(open_c) != target.count(close_c):
            issues.append({
                "kind": "formatting",
                "severity": "medium",
                "detail": f"unbalanced {open_c}{close_c} in target",
            })

    return {"issues": issues, "engine": "heuristic"}


class HeuristicProvider(Provider):
    """Offline stand-in. Emits the same JSON contract as the LLM path."""

    name = "heuristic"

    def complete(self, system: str, user: str) -> str:
        payload = json.loads(user)
        result = heuristic_review(
            payload.get("source", ""),
            payload.get("target", ""),
            payload.get("source_lang", "ro"),
            payload.get("target_lang", "en"),
            payload.get("must_terms", []),
        )
        return json.dumps(result)


def get_provider(prefer: str | None = None) -> Provider:
    """Nebius when a key is present, otherwise the offline provider."""
    prefer = (prefer or os.environ.get("LQA_PROVIDER") or "").lower()
    if prefer == "heuristic":
        return HeuristicProvider()
    key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if prefer == "nebius" and not key:
        raise ProviderError("LQA_PROVIDER=nebius but NEBIUS_API_KEY is not set")
    if key:
        return NebiusProvider(key)
    return HeuristicProvider()
