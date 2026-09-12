"""Report rendering - markdown and JSON."""

from __future__ import annotations

import json

from .reviewer import Report

BADGE = {"pass": "PASS", "review": "REVIEW", "block": "BLOCK"}


def to_json(report: Report, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent)


def to_markdown(report: Report, title: str = "Localization QA Report") -> str:
    c = report.counts
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Overall quality score: {report.score}/100**")
    lines.append("")
    lines.append(f"- Direction: `{report.source_lang}` -> `{report.target_lang}`")
    lines.append(f"- Segments reviewed: **{len(report.segments)}**")
    lines.append(f"- Verdict: **{c['pass']} pass / {c['review']} review / {c['block']} block**")
    lines.append(f"- Reviewer engines: {', '.join(sorted({e for s in report.segments for e in s.engines}))}")
    lines.append("")

    if c["block"] or c["review"]:
        lines.append("## Segments needing attention")
        lines.append("")
        lines.append("| Segment | Score | Status | Issues |")
        lines.append("|---|---|---|---|")
        for s in sorted(report.segments, key=lambda x: x.score):
            if s.status == "pass":
                continue
            kinds = ", ".join(sorted({str(i.get("kind")) for i in s.issues})) or "-"
            lines.append(f"| `{s.id}` | {s.score} | {BADGE[s.status]} | {kinds} |")
        lines.append("")

    for s in sorted(report.segments, key=lambda x: x.score):
        if s.status == "pass":
            continue
        lines.append(f"### `{s.id}` - {BADGE[s.status]} ({s.score}/100)")
        lines.append("")
        lines.append(f"- **Source:** {s.source}")
        lines.append(f"- **Target:** {s.target}")
        metrics = []
        if s.accuracy is not None:
            metrics.append(f"accuracy {s.accuracy}/10")
        if s.naturalness is not None:
            metrics.append(f"naturalness {s.naturalness}/10")
        if s.register_ok is not None:
            metrics.append(f"register {'ok' if s.register_ok else 'off'}")
        if metrics:
            lines.append(f"- **Model metrics:** {', '.join(metrics)}")
        if s.model_error:
            lines.append(f"- **Model error:** {s.model_error}")
        lines.append("")
        for issue in s.issues:
            eng = issue.get("engine", "?")
            lines.append(
                f"  - **{str(issue.get('severity', '?')).upper()}** "
                f"[{issue.get('kind', '?')}/{eng}] {issue.get('detail', '')}"
            )
        if s.suggested_target:
            lines.append("")
            lines.append(f"  - Suggested rewrite: {s.suggested_target}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Deterministic checks (terminology, source leakage, omissions, formatting) are "
        "authoritative and reproducible. Model findings are labelled with their engine "
        "and are advisory."
    )
    lines.append("")
    return "\n".join(lines)
