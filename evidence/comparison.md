# Head-to-head on the identical task (5 segments, same glossary, same prompt)

| Model | Score | Verdict | Model findings |
|---|---|---|---|
| `nvidia/Nemotron-3-Ultra-550b-a55b` | **66.6** | 1 pass / 1 review / 3 block | **9** |
| `meta-llama/Llama-3.3-70B-Instruct` | 71.1 | 1 pass / 0 review / 4 block | 5 |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 72.7 | 1 pass / 0 review / 4 block | 5 |

## Per-segment

| seg | Ultra-550b | Llama-70B | Nano-30B |
|---|---|---|---|
| seg-001 (clean) | nat 10 / acc 10 | nat 9 / acc 10 | nat 9 / acc 10 |
| seg-002 (glossary) | nat 9 / acc 8 / terminology | nat 8 / acc 8 / terminology | nat 8 / acc 7 / terminology |
| seg-003 (Romanian leaked) | nat 1 / acc 1 / untranslated, accuracy, fluency, terminology | nat 2 / acc 6 / untranslated | nat 2 / acc 3 / untranslated |
| seg-004 (omission) | nat 7 / acc 3 / omission, **register** | nat 6 / acc 6 / omission | nat 3 / acc 2 / omission |
| seg-005 (typo) | nat 7 / acc 8 / fluency, formatting | nat 8 / acc 8 / accuracy, formatting | nat 4 / acc 5 / accuracy, formatting |

## What the numbers say

**Deepest review: Ultra-550b.** 9 findings vs 5 for both others, and the only model of the
three to catch the **register** violation on seg-004 — both Llama and Nano returned
`register_ok = true` there. It also decomposed the badly-broken seg-003 into four separate
findings (untranslated, accuracy, fluency, terminology) rather than one.

**Most calibrated accuracy judgement: Ultra-550b.** seg-004's target drops the instruction to
check the card's expiry date entirely. Ultra scored accuracy 3/10, Nano 2/10 — both defensible.
Llama scored it 6/10, which is too generous for a segment that lost half its content.

**Sharpest classification: Ultra-550b.** On seg-005 the target is *accurate* but malformed
(`the the`, missing bracket). Llama and Nano both labelled it `accuracy`; Ultra correctly
called it `fluency` + `formatting`.

**Honest counterpoint — Nano-30B is remarkable for its size.** At roughly a tenth of the
active parameters it still caught the terminology violation, the omission and the leakage.
For a cheap first-pass CI gate it is defensible. What it misses is nuance, and on seg-005 its
accuracy/naturalness scores (5/4) were noticeably harsher than the text warrants.

**Cost/latency caveat:** this comparison measures output quality on one sample, not cost or
throughput. A production setup would likely run Nano as a cheap gate and Ultra as the final
review — which the pluggable provider design already supports.
