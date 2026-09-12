# Devpost submission text — Nebius x NVIDIA Global AI Hackathon

*Ready to paste into the Devpost submission form. Only the repo URL and video need adding.*

---

## Title
**LQA — Localization QA Agent**

## Tagline
Terminology-aware translation review for Romanian ⇄ English, on NVIDIA open models served by Nebius Token Factory.

## Inspiration
Machine translation made translation cheap and localization risky. A translated segment can
read perfectly and still be commercially wrong — because it ignored the client's glossary.
That class of bug is invisible to any reviewer who does not know the brand, which is exactly
why it survives into production and why it gets expensive later.

I hit this problem for real: working in Romanian ⇄ English, the failure is never "the grammar
is broken". It is `checking account` where the client's brand term is `current account` —
fluent, natural, and wrong.

## What it does
You feed it source segments, their translations, and the client glossary. It returns a
scored, per-segment QA report naming exactly what is wrong and which engine found it.

It catches: glossary/terminology violations, untranslated source-language leakage, probable
omissions, unbalanced brackets and stray markup, duplicated words, and — from the model —
naturalness, register and accuracy judgements plus suggested rewrites.

## How I built it
Two layers, deliberately separated:

1. **Deterministic layer (authoritative).** Glossary enforcement, source leakage, omission
   detection, formatting, duplicated words. Reproducible, auditable, no network, no API key.
2. **Model layer (advisory).** NVIDIA open-source models served through Nebius Token Factory,
   returning structured JSON with naturalness/accuracy scores and rewrites. Labelled with its
   engine in every report line.

The model advises; it does not judge. A model claiming "terminology OK" while a glossary term
is missing does not get to win.

### The part that took the work: Romanian inflects
The glossary term is `cont curent`. The source says `soldul contului curent`. Naive substring
matching reports "no issues" while the client's required term is silently missing — so the
tool is worse than useless, it is confidently wrong.

I implemented diacritic-folded, suffix-aware token matching: `cont curent` matches
`contului curent`, while `cont` correctly does **not** match `contact`. That distinction is
what makes it usable rather than noisy.

## Challenges
- **Inflection vs. false positives.** Prefix matching catches `contului` and wrongly catches
  `contact`. Solved with an explicit Romanian suffix table instead of `startswith`.
- **Double-charging findings.** Both layers independently flagged the same missing glossary
  term, so the score was penalised twice. Terminology is now deduplicated by expected term,
  and there is a regression test pinning it.
- **Demonstrability without credits.** A submission that only runs when funded is not
  demonstrable. The offline provider implements the identical JSON contract, so the whole
  pipeline and test suite run with no key — and sharpen when one is present.

## Accomplishments
- 25/25 tests green, stdlib only, zero third-party dependencies
- End-to-end CLI with a markdown/JSON report and a CI gate (`--fail-under`, meaningful exit codes)
- Verified on planted defects: catches the inflected glossary violation, the fluent-but-wrong
  brand term, Romanian leakage, an omission, and a duplicated word
- Doubles as a real production tool for actual paid translation work

## What I learned
That the valuable half of an AI system is often the half without the model in it. The
deterministic checker is what makes the output trustworthy; the model is what makes it
insightful. Shipping only the model would have produced a demo that is confidently wrong
in exactly the cases that cost clients money.

## What's next
Web UI, XLIFF/TMX import for real CAT-tool workflows, segment-level diff view, and applying
suggested rewrites automatically.

## Built with
python · nebius-token-factory · nvidia-open-models · llama · mcp
