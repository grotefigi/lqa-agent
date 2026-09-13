"""Command line interface.

  python -m lqa review --input segs.json --glossary glossary.csv --format md
"""

from __future__ import annotations

import argparse
import json
import sys

from .glossary import load_glossary
from .importers import load_segments, ImportError_
from .providers import get_provider, ProviderError
from .report import to_json, to_markdown
from .reviewer import Segment, review_document


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lqa", description="Localization QA agent")
    p.add_argument("--version", action="version", version="lqa 0.1.0")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("review", help="review translated segments against a glossary")
    r.add_argument("--input", required=True,
                   help="segments to review: .tmx, .xlf/.xliff or .json "
                        "(format is auto-detected)")
    r.add_argument("--glossary", help="CSV/TSV glossary: source,target[,note]")
    r.add_argument("--source-lang", default="ro")
    r.add_argument("--target-lang", default="en")
    r.add_argument("--format", choices=["md", "json"], default="md")
    r.add_argument("--output", help="write to this file instead of stdout")
    r.add_argument("--no-model", action="store_true",
                   help="deterministic checks only - no model calls")
    r.add_argument("--provider", choices=["nebius", "heuristic"],
                   help="force a provider (default: nebius if NEBIUS_API_KEY is set)")
    r.add_argument("--fail-under", type=float, default=None,
                   help="exit code 1 if the overall score is below this")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "review":
        try:
            segments = load_segments(args.input, args.source_lang, args.target_lang)
        except ImportError_ as exc:
            print(f"error: could not read input: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"error: could not read input: {exc}", file=sys.stderr)
            return 2

        glossary = {}
        if args.glossary:
            try:
                with open(args.glossary, "r", encoding="utf-8") as fh:
                    glossary = load_glossary(fh.read())
            except Exception as exc:
                print(f"error: could not read glossary: {exc}", file=sys.stderr)
                return 2

        try:
            provider = get_provider(args.provider)
        except ProviderError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        report = review_document(
            provider, segments, glossary,
            source_lang=args.source_lang, target_lang=args.target_lang,
            use_model=not args.no_model,
        )
        rendered = to_json(report) if args.format == "json" else to_markdown(report)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(rendered)
            print(f"wrote {args.output}  (score {report.score}/100, {report.counts})")
        else:
            print(rendered)

        if args.fail_under is not None and report.score < args.fail_under:
            return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
