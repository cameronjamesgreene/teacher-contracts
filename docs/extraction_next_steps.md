# Next steps: from one document to the corpus

Status: proposed, not executed. Measured evidence for the claims here is in
`docs/extraction_results.md`; how to run the pipeline is in
`docs/extraction_pipeline.md`.

## The problem with where we are

Manchester scores 0.895, and that number cannot carry the weight we want to put on it.

- **It is no longer a test set.** Four agent authors ran the scorer against it
  repeatedly while developing. The key is development data now, and 0.895 is
  optimistically biased by an unknown amount.
- **It is not a typical document.** 54 pages and 151k chars against a corpus median
  of 128 pages and 367k chars; 17 of 36 usable documents exceed 400k chars and the
  largest is 1.99M.
- **Its page-offset regime is unusual, and that inflated one of our wins.** Manchester's
  printed footers run 1 behind the PDF page in the body and 7 behind in appendices.
  Measured modal offsets elsewhere in the corpus include 0, 0, 1, 1, 10, 12, 18 and
  several incoherent. On a zero-offset document the baseline's footer-copying would have
  scored fine, so the 0.132 → 0.921 page delta is partly a Manchester artifact.
- **The key only covers questions where two systems disagreed**, so it oversamples hard
  questions and is structurally blind to errors both systems share.

## The measurement design

### Two tiers, and an honest name for each

**Tier 1 — evidence integrity. No ground truth needed, runs on all 36 documents.**
For every substantive answer, mechanically verify the quote is verbatim, contiguous,
and on the page reported. This is cheap and catches the failure modes that dominated
the incumbent (evidence 0.605, page 0.132).

It is **not** an accuracy metric and must never be reported as one. It cannot tell
whether the answer interprets the quote correctly, whether a better provision was
missed, or whether an absence claim is right. It is also **gameable by abstention**:
a pipeline that answers `not_discussed` everywhere scores 1.000. So Tier 1 is always
reported next to **answer coverage**, with abstentions in the denominator.

**Tier 2 — accuracy. Needs ground truth, runs on a probability sample.**

### The sampling design that makes Tier 2 affordable

Hand-labelling all 3,816 question-document pairs is out. A two-phase stratified
probability sample is not:

1. **Phase 1, free:** run the pipeline over all 36 documents and record cheap features
   for every pair — Tier 1 pass/fail, substantive vs absence, quote length, evidence
   span count, document type, text quality, page-offset regime, and whether the
   variants disagreed.
2. **Stratify** on those features and **oversample** the strata where errors
   concentrate: absence claims, Tier 1 failures, cross-variant disagreements, appendix
   citations, handbooks.
3. **Label ~200–400 pairs** by blinded review. Estimate corpus accuracy by
   inverse-probability (Horvitz–Thompson) weighting, *not* the raw accuracy of the
   oversampled set. Roughly 138 labels buys a ±5-point 95% interval at accuracy near
   0.90 under simple random sampling; clustering and per-subgroup reporting push it to
   200–400.
4. **Report two estimands separately:** micro-accuracy over all pairs, and
   macro-accuracy averaging the 36 per-document rates. They answer different questions
   and will differ.
5. **Cluster on documents, not pairs.** The effective sample size for any claim about
   contracts in general is 36, not 3,816. Bootstrap over documents for intervals.
6. **Pre-register the sample and freeze the pipeline before any label is revealed.**

### The threat we had not accounted for

**The reference standard is itself uncertain.** Each Manchester question was reviewed
by exactly one reviewer, so "accuracy" partly measures agreement with one
interpretation. We already have direct evidence of this: one gold row needed
correcting mid-run, and two apparent model failures turned out to be scorer strictness
rather than model error.

Mitigation: **double-code a subset blindly, adjudicate disagreements, and report
inter-annotator agreement** alongside accuracy. Without that number, a precise-looking
accuracy estimate rests on an unmeasured target.

### Comparisons need error bars

Run-to-run noise is ±0.05 at n=38 at temperature 0 (three identical sweep configs gave
0.658 / 0.684 / 0.737). Consequences:

- Single-run differences under ~0.05 are not signal. The ensemble's +0.053 over the
  best single variant does not currently clear that bar.
- Prefer **paired** comparisons: score two policies from the *same* model output. One
  unpaired A/B inside variant B initially suggested the opposite of the right answer.
- Budget ≥3 repeats on ≥3 documents before believing any pipeline ranking.

## Attempted and rejected: PydanticAI validators that repair instead of discard

**This was built and did not beat the current pipeline (0.632 against 0.842). Kept here
because the reasoning still holds and the failure mode is instructive.**

Today every variant validates grounding *after* the fact and, on failure, discards the
answer and writes `not_discussed`. That destroys probably-correct findings over
transcription slips — the incumbent nulled 20 answers this way.

A PydanticAI agent with an `output_validator` raising `ModelRetry` turns each of those
discards into a repair, with the validation error as feedback. **Measured, not
assumed:** a probe over the 38 scored questions scored 0.632 overall with
**evidence 1.000 and page 0.921**, and **10 of 38 answers required a repair retry and
all 10 succeeded**. Under the current design those 10 would have been thrown away.

The probe also found a **20x speedup**: `model_settings` with
`enable_thinking: False` gives 2.4s per question against roughly 20s with reasoning
enabled, at 58 requests for 38 questions. That reframes cost at corpus scale.

The proposed agent:

- `output_type` with **`evidence: list[str]`**, not one span. Variant A lost required
  tokens because the supporting figure sat in a second quote it had to discard.
- **Validators raise `ModelRetry`** on: non-verbatim quote, stitched quote, an absence
  claim made without at least two materially different searches, and a value question
  answered with no figure. The absence-verification stage that produced the single
  largest accuracy gain becomes a structural precondition rather than orchestration code.
- **`deps_type` dependency injection** for the document, which removes the hardcoded
  `DOCUMENT_ID` and `TEXT_PATH` that currently block running on anything but Manchester.
- **Bounded tools** (`search`, `read_section`) under `UsageLimits`. The earlier tool-loop
  failure was unboundedness, not tools as such.
- **Thinking off for extraction, on for adjudication.** Reserve reasoning for the few
  judgment-heavy calls (absence confirmation, variation merging) where it earns its cost.

## Cost

At Manchester's window density the whole usable corpus is ~1,342 sweep windows per
pass, so ~4,000 sweep calls for three passes. Per-question extraction is 3,816 pairs.
With thinking off at ~2.4s and modest parallelism this is hours, not days, and the
endpoint is free. The binding constraint is **human review for Tier 2**, which is
exactly what the sampling design minimises.

## Order of work

1. ~~Parameterise the document and index the corpus.~~ **Done.** `DocumentContext`
   carries the document, `corpus()` reads all 36 usable documents from the manifest, and
   all 36 are indexed with embeddings.
2. ~~Try a PydanticAI validator agent.~~ **Done and rejected**, see above.
3. **Make `grind_verify` document-aware.** It still pins Manchester in a few places and
   is the production extractor, so this is the blocking piece of work.
4. **Freeze and tag** before any held-out measurement.
5. **Run Tier 1 over all 36 documents**, reporting citation integrity next to answer
   coverage, per document.
6. **Draw the stratified Phase 2 sample**; blinded review with double-coding on a subset;
   report weighted accuracy with intervals and inter-annotator agreement.
7. Only then make any claim about corpus-level accuracy.
