"""Localization QA agent - translation quality review for Romanian <-> English.

Deterministic checks are authoritative; an LLM (NVIDIA open models served on
Nebius Token Factory) adds the judgement calls a regex cannot make.
"""

from .glossary import GlossaryEntry, load_glossary, check_glossary, required_targets
from .providers import Provider, ProviderError, NebiusProvider, HeuristicProvider, get_provider
from .reviewer import Segment, SegmentResult, Report, review_segment, review_document
from .report import to_markdown, to_json

__version__ = "0.1.0"

__all__ = [
    "GlossaryEntry", "load_glossary", "check_glossary", "required_targets",
    "Provider", "ProviderError", "NebiusProvider", "HeuristicProvider", "get_provider",
    "Segment", "SegmentResult", "Report", "review_segment", "review_document",
    "to_markdown", "to_json", "__version__",
]
