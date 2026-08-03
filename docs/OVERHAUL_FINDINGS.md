# Overhaul findings — measured, August 2026

Everything here is a measurement against the live endpoint or the gold set, not an estimate.
Reproduce with `scripts/evaluate.py`, `scripts/corpus.py`, and the telemetry in
`cache/runs.sqlite`.

## 1. The endpoint was never the bottleneck

| | assumed | measured |
|---|---|---|
| context window | 32,000 | **131,072** (`/v1/models` → `max_model_len`) |
| output cap | — | 32,768 (`x-som-policy-output-cap`) |
| chars per token | 3.0 | **5.6** (210,000 chars → 37,336 `prompt_tokens`) |
| usable input | ~72,900 chars ≈ 13k tokens | ~448,000 chars |
| concurrency | "freezes at ~8" | **~44 admitted**, then queued, then clean 429s |
| throughput | 6.4 calls/min achieved | ~2,000 small / ~315 large req/min available |

The pipeline was using about a tenth of the context window it had, and roughly 2% of the
endpoint's throughput. Every expensive structure in the old design — 45k-char chunking, 23
sub-batches × sections, uncapped recovery/reconciliation re-asks, 3,000-char rights chunks —
existed to work around a limit that was a constant in a file rather than a property of the
service.

**Reasoning tokens are billed against `max_tokens`.** Same 150k-char prompt: **13.9s with
thinking on, 1.4s with it off**; a trivial prompt spends 228 completion tokens thinking and 6
answering. This is also the top cause of the `finish_reason == "length"` retries — and the
old client retried with the *same* budget, so it re-truncated deterministically.

**429s are clean and fast, not hangs.** The operational note describing a freeze at 8
concurrent chunks does not reproduce under the current scheduler (`phase1-rr-v1`). But
`x-som-global-in-flight` is shared across all SOM tenants, so 44 is the service ceiling, not
our allowance; the governor targets 14 and yields under global pressure.

## 2. The reported "~85%" is real, but it is accuracy, and accuracy is the wrong metric

Scoring the audited run against its own audit reproduces it exactly:

```
baseline (the Jun 26 audited run), 347 gold cells, 4 documents
  answer_accuracy       0.850
  recall_substantive    0.765      false negatives 50
  precision_substantive 1.000      false positives  0
```

Accuracy is dominated by easy true-negatives. The defect is entirely recall: **95% of errors
are `not_discussed` on a provision that is present, and there are zero fabricated values.**

Note also that `output/audit_report.xlsx` (Jun 29) predates the code (Jul 26). DCPS
`pay_salary_schedule_001`, which the audit calls a bug "confirmed STILL PRESENT", is `"yes"`
with valid evidence in a cache file written Jul 1. Any accuracy claim made against that
workbook without re-running is measuring a system that no longer exists.

## 3. Whole-document reading and keyword retrieval fail on DISJOINT sets

This is the load-bearing result. On four documented false negatives:

| view | score |
|---|---|
| whole document, reasoning off | 2/4 |
| whole document, reasoning **on** | 3/4 |
| SQLite FTS5 BM25 top-k | 2–3/4, **a different subset** |
| union + never-silent escalation | **4/4**, all quote-verified |

Houston is the clearest case: 1.06M chars (113k tokens). The whole-document view returned
`not_discussed`; BM25 returned `"Appendix A-1 – Teacher Salary Schedule - 2005 – 2006"`
verbatim from a 15k-token retrieval. That is lost-in-the-middle, and more context makes it
worse, not better. Conversely on Palm Beach the whole-document view found step increments
that BM25's top-k missed, because the answer needed synthesis across distant sections.

**This is why the fix is a union of diverse views rather than a bigger context or a better
retriever.** It is also why the decision rule is an OR gated on quote verification rather
than a majority vote: with a 95%-false-negative / 0%-fabrication error profile the loss is
asymmetric, and a majority of `not_discussed` would outvote one correct quoted answer.

⚠️ The system prompt was adjusted after seeing these four cases, so they are now a training
set, not a test set.

## 4. The union works on recall and costs precision — quantified

Full 4-document, 106-question run against the same 347 gold cells:

| | baseline | two-view | change |
|---|---|---|---|
| **recall_substantive** | 0.765 | **0.962** | **+0.197** |
| false negatives | 50 | **8** | −42 |
| precision_substantive | 1.000 | 0.837 | **−0.163** |
| false positives | 0 | 40 | +40 |
| answer_accuracy | 0.850 | 0.726 | −0.124 |
| quote_verified_rate | 0.000 | 0.984 | — |

**On the 52 cells where the human auditor independently supplied the correct answer (the
baseline's known errors), two-view fixes 31 — 59.6%.**

### The comparison is confounded, and it matters in both directions

A paired McNemar over all 347 cells says the baseline is significantly better. That verdict
is an artifact: **all 74 cells where only the baseline is correct have `tier='from_answer'`,
meaning the gold answer IS the baseline's own answer.** All 31 cells where only two-view is
correct have `tier='from_note'`, i.e. independent ground truth. The gold set cannot fairly
compare the run it was derived from against any other run.

That said, the 40 false positives are a real finding and should not be explained away: **37
of them carry quotes that DO verify against the source.** The model is locating genuine text
and over-reading it as a provision — e.g. coding `conduct_lesson_plans_009` as `yes` on a
passage that describes lesson-plan format, where the auditor judged the topic not discussed.
Requiring a verified quote before single-view adoption recovers only 3 of the 40
(precision 0.837 → 0.846), so ungrounded quoting is not the mechanism.

The most likely cause is the `INCORPORATION BY REFERENCE COUNTS` paragraph added to the
system prompt on the strength of four cases. **A/B that paragraph next**; it is a two-line
change and the single highest-value open experiment.

## 5. Throughput, measured on the HPC against the worst case

Benchmark run on the **three largest documents in the corpus**, full 106-question codebook:

```
dallas_independent_school_district   1,986,997 chars   274.0s
los_angeles_unified_school_district  1,569,260 chars   394.1s
cleveland_metropolitan_school_dist   1,073,717 chars   259.6s
                                     TOTAL 927.6s = 5.15 min/document
```

| | baseline | now |
|---|---|---|
| wall-clock per document | 66.3 min (995 min / 15 docs) | **5.15 min** |
| model calls per document | ~425 | **61** |
| error rate | 10-restart budget needed | 3 of 182 calls (1.6%) |
| rate-limit events | supervisor kill/pause/restart × 26 | **0** |
| peak in-flight | 15 processes, mostly idle-waiting | 10 (cap 14) |

**~13x faster on the hardest documents in the corpus**, and the baseline's 66.3 min was an
average over a mixed set, so the like-for-like gain on typical documents is larger. The gain
comes from 7x fewer calls and from keeping the concurrency budget actually saturated, not
from raising it — peak in-flight stayed at 10 against a cap of 14.

One long tail worth noting: `max_latency = 215s` on a single call. Worth investigating
before scaling, since it sits under a 900s read timeout.

## 6. What is not yet measured

- **The determinism floor.** `temperature`/`seed` are still unset. Identical configurations
  produced different answers across repeated runs during development (Palm Beach flipped
  between `yes` and `not_discussed` on three separate runs). Until the run-to-run flip rate
  is quantified, any A/B smaller than that floor is noise. This is the next thing to run.
- **Salary and rights** changes are unit-tested but not yet scored against grid-level gold.
- **Prefix caching** is unconfirmed: the endpoint does not return
  `usage.prompt_tokens_details.cached_tokens`, so the document-first prompt reordering could
  not be verified as effective. It is harmless either way.

## 6. Sizing note for anyone re-tuning

At 8 questions per batch with reasoning on, a coding call spends ~4,900 reasoning + ~5,900
answer tokens. A 6,000-token budget truncated 34 of 144 calls, and each truncation costs a
full re-generation. `max_tokens` is only a cap — unused headroom is free — so under-budgeting
is far more expensive than over-budgeting.
