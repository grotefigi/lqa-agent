# LQA — Localization QA Agent

**Romanian ⇄ English translation quality review.** Drop in your source and translated
segments plus a client glossary, get back a scored, per-segment QA report that tells you
exactly what is wrong and why.

Built for the **Nebius x NVIDIA Global AI Hackathon** — an AI system on open,
independent infrastructure: NVIDIA open-source models served through
**Nebius Token Factory**.

---

## The problem this actually solves

Machine translation made translation *cheap* and localization *risky*. A segment can read
perfectly and still be commercially wrong, because it ignored the client's glossary. That
class of bug is invisible to any reviewer who does not know the brand — which is exactly
why it survives to production.

Existing QA tools fail on Romanian for a specific, boring reason: **Romanian inflects.**
The glossary says `cont curent`; the source says `soldul contului curent`. Substring
matching reports "no issues" while the client's required term is silently missing.

This agent handles inflection explicitly with diacritic-folded, suffix-aware token
matching — so `cont curent` is still detected inside `contului curent`, while `cont`
correctly does **not** match `contact`.

## Design principle: the model advises, it does not judge

| Layer | Role | Authority |
|---|---|---|
| Deterministic checks — glossary, source leakage, omissions, formatting, duplicated words | Reproducible, auditable, runs with no network and no API key | **Authoritative** |
| NVIDIA open model via Nebius Token Factory — naturalness, register, accuracy, rewrite suggestions | Judgement calls a regex cannot make | **Advisory**, labelled with its engine |

Every finding in the report is tagged with the engine that produced it. A model that
claims "terminology OK" while a glossary term is missing does not get to win — the
deterministic checker is the verdict.

This also means the tool is **fully demonstrable with zero API credits** (the offline
heuristic provider implements the same JSON contract), and gets sharper when funded.

## Architecture

```
src/lqa/
  glossary.py   CSV/TSV glossaries; diacritic folding; Romanian suffix-aware matching
  providers.py  Nebius Token Factory client (OpenAI-compatible) + offline provider
  reviewer.py   the pipeline: deterministic pass, model pass, dedupe, scoring
  report.py     markdown + JSON rendering
  cli.py        `lqa review`
```

Scoring is a weighted penalty model: `100 − Σ(severity_weight × kind_weight)`, floored at
zero, so a dropped paragraph costs far more than a duplicated word. Terminology
violations are deduplicated by expected term, so the same missing glossary entry is
charged once rather than once per engine.

## Quick start

No dependencies beyond the Python standard library.

```bash
# tests (25 tests, no network, no API key)
python -m unittest discover -s tests

# review, offline
PYTHONPATH=src python -m lqa review \
    --input examples/sample.json \
    --glossary examples/glossary.csv \
    --format md --output examples/report.md

# review with NVIDIA open models on Nebius
export NEBIUS_API_KEY=...            # Nebius Token Factory key
export NEBIUS_MODEL=meta-llama/Llama-3.3-70B-Instruct
PYTHONPATH=src python -m lqa review --input examples/sample.json \
    --glossary examples/glossary.csv --format json

# usable as a CI gate
python -m lqa review --input segs.json --glossary g.csv --fail-under 95   # exits 1 below 95
```

### Input format

```json
[
  {"id": "seg-001", "source": "Vă rugăm să vă autentificați.", "target": "Please sign in to continue."}
]
```

### Glossary format

```csv
source,target,note
cont curent,current account,Banking - never use "checking account"
notificare push,push notification,Product UI string
```

## Verified output

On the bundled 5-segment sample (1 clean, 4 with planted defects), offline provider:

```
score 85.6/100   ->   1 pass / 1 review / 3 block

seg-001  pass   100.0  -
seg-002  block   83.8  terminology      (cont curent -> 'current account' missing)
seg-003  block   83.2  untranslated     (Romanian left in the English target)
seg-004  block   68.2  terminology, omission
seg-005  review  93.0  fluency, formatting
```

`seg-002` is the interesting one: the target is fluent, natural English, and wrong.
The source says `contului curent` (inflected), the glossary demands `current account`,
the target says `checking account`. Nothing but terminology-aware review catches that.

## Live Token Factory results (real, not illustrative)

Run against **`nvidia/Nemotron-3-Ultra-550b-a55b`** on **Nebius Token Factory**, same
5-segment sample as above. Raw output in `evidence/nemotron-3-ultra-live-run.json`.

```
score 66.6/100   ->   1 pass / 1 review / 3 block      (deterministic-only: 85.6/100)

seg-001  pass   100.0  naturalness 10  accuracy 10
seg-002  block   67.6  naturalness  9  accuracy  8   terminology
seg-003  block   33.1  naturalness  1  accuracy  1   untranslated, accuracy, fluency, terminology
seg-004  block   46.6  naturalness  7  accuracy  3   terminology, omission, register
seg-005  review  85.9  naturalness  7  accuracy  8   fluency, formatting
```

**The model earns its place on `seg-004`.** The deterministic layer found the omission and the
missing glossary term. Nemotron additionally flagged a **register violation**:

> `register` — Source uses formal polite register (`vă rugăm`), target is informal imperative.

That is a real localization defect, it is invisible to any regex, and it is exactly the class of
judgement that makes a translation read as foreign to a native speaker. No amount of
deterministic checking finds it.

It also produced correct rewrites where the deterministic layer could only complain:

| segment | suggested rewrite |
|---|---|
| seg-002 | `Your current account balance is available in the app.` |
| seg-003 | `For more information, please contact our support team.` |
| seg-004 | `If you encounter problems making the payment, please check the card's expiry date and try again.` |
| seg-005 | `Go to the settings (Settings > Account) to enable the push notification.` |

Note the score *drops* from 85.6 to 66.6 when the model is enabled. That is the point: the
deterministic layer alone is too permissive, because it can only see what it was told to look for.

## Status

Working: 25/25 tests green; CLI runs end to end; markdown and JSON reports; CI gate;
inflection handling; dedupe; offline and Nebius paths.

Not yet built: web UI, TMX/XLIFF import, segment-level diff view, automated rewrite application.
