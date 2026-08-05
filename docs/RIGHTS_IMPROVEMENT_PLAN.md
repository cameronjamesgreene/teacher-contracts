# Why rights_score scores 29% strict, and what to do about it

## First: the number is an adversarial lower bound, not a random sample

The v11 auditor was **instructed** to over-sample rule-vs-model disagreements and failed
quote checks. It did:

| | corpus (8,273 clauses) | audited sample (50) |
|---|---|---|
| `quote_verified = False` | 0.2% | **24%** |
| `statement_type_match = False` | 19.4% | heavily over-sampled |

So 29% strict describes *the population of suspicious clauses*, not the corpus. The corpus
rate is better — but it is also unknown, because we have never drawn a random sample. **Both
numbers should be measured before anything is claimed.** That is item 0 below.

## Second: the audit's own diagnosis is partly wrong, and fixing the wrong thing is the risk

The audit named `voice` the top defect (19 of 35 non-CORRECT). Checked against the corpus,
that ranking does not survive:

- **Voice is mostly consistent.** The constructions it flagged are genuine passives and are
  tagged passive 88–97% of the time (`be made` 90%, `be granted` 97%, `be paid` 94%). There
  is ~10% noise, not incoherence.
- **Predicative adjectives mislabeled as passive are 169 of 3,564 passive tags — 5%**, not
  the dominant class.
- **Most importantly, voice barely propagates.** It is read in exactly two places in
  `rights_score.py`: to look for a `by <agent>` phrase when resolving `acting_party`, and as
  a re-verify trigger. **It does not feed `classify_statement_type` at all.** A voice error
  therefore usually changes nothing in the published score.

The audit over-weighted voice because its sample was adversarial and because voice errors
are easy to *see*. What actually moves the score is admissibility and bucket assignment.

## What actually determines a rights score

```
quote            -> admissibility (an unverifiable quote is an invented data point)
statement_type   -> which of the four buckets the clause lands in
acting/protected -> whose bucket it is
modal            -> how much weight it carries
voice            -> only by-agent resolution + a re-verify trigger
```

Ranked by (impact on the published score) × (measured error rate):

| # | Defect | Measured scale | Score impact |
|---|---|---|---|
| 1 | **Quote not verbatim** | **300 / 8,273 = 3.6%** corpus-wide | Fatal — fabricated evidence |
| 2 | **`quote_verified` can't detect it** | True on 8,255/8,273; caught 10 of 300 | Fatal — hides #1 |
| 3 | **statement_type vs model disagreement** | 16.1% after the polarity fix (was 19.4%) | High — wrong bucket |
| 4 | **protected_party forced binary** | `other` used 15 times in 8,273; 699 quotes name students/parents/public | High — wrong beneficiary |
| 5 | **null modal** | 1,106 / 8,273 = 13% | Medium — weight defaults |
| 6 | **null topic** | 249 / 8,273 = 3% | Low — reporting only |
| 7 | **voice** | ~10% noise; 5% adjective/participle confusion | **Low** — barely propagates |

---

## The plan

### 0. Measure the real rate first (half a day, gates everything)
Draw a **random** 100-clause sample stratified by document, audit it the same way, and
report strict/acceptable with document-clustered CIs. Without this we cannot tell a fix from
noise, and the 6.4% run-to-run flip rate already bounds what is detectable. Add a second
**random** 100 for quote fidelity specifically, since that is the headline claim.

### 1. Make quote verification actually work (highest value, ~1 day)
`quote_present()` accepts a quote when ≥60% of its 4-word shingles appear *anywhere* in the
document. That is deliberately lenient — it was written to tolerate PDF line-break noise —
and it is why a cross-passage splice passes: both halves exist, just not together.

Replace the single boolean with a graded verdict:
- `exact` — normalized contiguous substring match
- `contiguous_fuzzy` — matches one span allowing whitespace/hyphenation/OCR joins
- `spliced` — the halves match, but in **different, non-adjacent** spans → the current
  failure mode, currently reported as verified
- `absent` — no match

Only `exact`/`contiguous_fuzzy` should count as verified and enter `aggregate()`. Implement
by locating the longest matching span and requiring the remainder to be adjacent to it,
rather than counting shingles globally. Then re-verify all 8,273 clauses offline (free, no
API) and report the new distribution against the auditor's 300.

### 2. Stop emitting unusable clauses (half a day)
- 20 quotes under 25 characters (`"If you h"`), 17 containing a literal `...`, 20 containing
  bracketed insertions. Reject at extraction: a clause whose quote is elided or bracketed is
  by definition not verbatim.
- 3 rows carry an empty quote but a full feature set. Drop them.
- Policy footers ("Revised: December 10, 1990") are being coded as clauses — add a
  non-provision filter.

### 3. Fix the protected_party binary (~1 day)
`other` is used 15 times in 8,273 rows, yet 699 quotes name students, parents or the public.
The extraction prompt forces a worker/management choice. Add `student`, `public`, `third_party`
as first-class values and route them to an `unassigned` bucket. This also fixes the
undocumented leak where such clauses add to `total_weight` but no bucket, so the four shares
sum to ~0.91 rather than 1.0 — decide and **document** which behaviour is intended.

### 4. Use the disagreement signal that already exists (~1 day)
`statement_type_match` is False on 16.1% of clauses and nobody reads it. The polarity
inversion sat there for months with 378 rows flagged. Two changes:
- Publish disagreement in the summary CSV as a per-document quality metric.
- Route disagreements to the existing `_reverify_ambiguous_clauses` pass, which currently
  triggers on a narrower condition. Adjudicate with the quote in hand.

### 5. Fill null modals (~half a day)
1,106 clauses have no modal, so `modal_strength_for` falls back to `NON_MODAL_WEIGHT` (0.85)
or 0.0 depending on verb category — a large, silent weighting decision. Extract the governing
verb phrase explicitly and log when the fallback fires.

### 6. Voice — last, and cheaply (~half a day)
Do **not** rewrite the prompt for this. Add a deterministic post-check: if the token after
`be`/`been`/`is`/`are` is a known predicative adjective (`responsible`, `eligible`,
`available`, `subject`, `entitled`), force `voice=active`. That covers the measured 5% at
near-zero cost and risk. Revisit only if item 0 shows voice mattering more than this analysis
suggests.

### Explicitly NOT in this plan
- Raising `RIGHTS_CHUNK_SIZE` further (3,000 → 12,000 is already unvalidated against clause
  recall; it needs measuring before another step).
- Re-running the corpus. Items 1, 2 and 6 are **offline** re-scorings of existing output and
  cost no API calls; only 3, 4 and 5 need a re-run.

## Sequencing

```
0  measure random baseline        (gates everything)
1  graded quote verification      offline re-score, no API
2  reject unusable clauses        offline
6  voice post-check               offline
--- re-run required below ---
3  protected_party vocabulary
4  disagreement -> re-verify
5  modal extraction
0' re-measure, paired McNemar vs the item-0 baseline
```

Items 1, 2 and 6 can be scored against the existing 8,273 clauses today, which means the
first three fixes can be evaluated before spending a single API call.
