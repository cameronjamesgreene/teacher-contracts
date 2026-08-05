# Is this the right extraction strategy? A review before wider use

Written to be read by collaborators deciding whether to build on this. It reports what
broke when the pipeline was first run outside its development document, because that is
the information that should drive the decision.

## Short answer

The **architecture** is right, the evidence for its core choices is solid, and the defect
that out-of-sample testing exposed is now fixed and verified on three document types. The
**remaining strategic problem is absence handling**, which is more fundamental than it
first looked and is not yet solved.

Recommend: adopt the architecture, fix transcription and absence as set out below, and do
not quote corpus-level numbers until the sampling plan in `extraction_next_steps.md` has
run. One earlier claim in this document is retracted below; it was my measurement error,
and the retraction is kept visible rather than edited away.

## Three different things, easily confused

Collaborators should keep these apart, because only two of the three are quality signals.

| measure | what it means | is a low value a problem? |
| --- | --- | --- |
| **answer coverage** | share of the 106 questions answered substantively | **No.** Not every document contains every provision. A 4-page tentative agreement answering 14 of 106 is correct behaviour, not failure. |
| **citation integrity** | of answers given, share whose quote is verbatim, contiguous, and on the reported page | **Yes.** This should be ~1.000 by construction. Anything less means unciteable claims are being emitted. |
| **index coverage** | share of the document's text that exists in a retrievable passage | **In principle yes** — text in no passage can never be retrieved, so a provision there becomes a false `not_discussed`. **Measured, it is a non-issue here**: median 0.994, worst 0.975. See the retraction below. |

## What the first out-of-sample runs found

Verify was run over all 106 questions on documents deliberately unlike Manchester.

| document | type | pp | answered | integrity | note |
| --- | --- | --- | --- | --- | --- |
| Manchester | CBA | 54 | 71/106 | 1.000 | development document |
| Anoka–Hennepin | tentative agreement | 4 | 14/106 | **1.000** | generalises cleanly |
| DeKalb County | handbook | 33 | 58/106 | 0.672 → **1.000** | defect found and fixed, see below |

Anoka is the encouraging result: a 4-page tentative agreement from a different state,
with a legitimately low answer coverage of 14/106, and citation integrity of 1.000 with
zero flagged problems. The invariants hold off the development document.

## Defect 1: unciteable quotes were being emitted (fixed)

On DeKalb, **19 of 58 substantive answers carried a quote that does not appear anywhere
in the document.** The pipeline detected this — each record was internally flagged
`ungrounded` — but the old code kept the quote in the evidence field anyway, clearing
only the page. A reader of the output CSV would reasonably have treated those 19 quotes
as verified support, and they were not verifiable. (They are paraphrases of real clauses
rather than inventions; see Defect 2.)

This never fired once on Manchester, which is precisely why one development document is
not enough.

Fixed: an ungroundable quote is now dropped rather than emitted. The answer text is
retained with low confidence and an explicit flag, because the model did read something
and the topic is probably discussed, but nothing unverifiable is presented as evidence.
`scripts/audit_citations.py` now reports a `self_flagged_ungrounded` count per document
so this class of failure is visible at a glance rather than buried in notes.

## Retracted: "the passage index drops a fifth of the text"

An earlier version of this document claimed median index coverage of 0.83 with a worst
case of 0.58, and called it the highest-value open problem. **That was wrong, and it was
my measurement error.** I summed only the passages' `text` column, while section headings
are stored in a separate column and *are* both full-text indexed and included in the
embedded document. Comparing that partial sum against the full document text manufactured
a shortfall.

Measured properly — what share of substantive document lines (25+ characters, so page
numbers and running headers are excluded) is recoverable from the indexed passages:

| | value |
| --- | --- |
| median across all 36 documents | **0.994** |
| worst document | **0.975** |
| documents below 0.95 | **0** |

Index coverage is a non-issue. Nothing needs fixing here, and no collaborator should
spend time on it.

## Defect 2 restated, and fixed: the model paraphrases instead of transcribing

The DeKalb failure was not fabrication of substance. The topics are all present in the
handbook — the retirement figure `14.27` really is in the text — and the answers were
substantively reasonable. What failed was transcription: the model paraphrased the clause
rather than copying it.

Three repair tiers already existed and each recovered only a fraction, because they all
mitigate the same problem instead of removing it. The pipeline was asking the model to
reproduce document text, which is the one thing it is measurably bad at. Notably, the
existing re-ask prompt *already* stated plainly that `not_discussed` was correct when no
span supported the provision — and the model ignored that 19 times and paraphrased instead.

**Fix: stop asking it to copy.** The passages are split into numbered sentences, the model
returns sentence *numbers*, and the host slices the span out of the passage. Verbatim and
contiguous by construction, with no anchor floor or threshold to tune. Only consecutive
numbers within one passage are accepted, so a multi-sentence selection is still one
unbroken span.

| | before | after |
| --- | --- | --- |
| DeKalb answers with an unciteable quote | **19 of 58** | **0** |
| of those 19: now carry a verbatim quote | — | 17 |
| of those 19: honestly recoded to absence | — | 1 |
| Manchester overall on the answer key | 0.842 | **0.842** (no change) |

The tier never fired on Manchester, which is the desired behaviour: inert where it is not
needed, decisive where it is.

An empty selection is treated as a **finding rather than a failure**. "The topic is
discussed but this specific provision is not" is exactly the fine-grained absence the
codebook needs, and it is what a paraphrase papers over, so an empty selection recodes the
answer to `not_discussed` with an explicit note. That makes this fix part of the absence
strategy below, not just a citation fix.

## What is well established

- **The host must own the page number.** The previous extractor scored 0.132 on pages by
  copying the number printed on the page. Deriving it from the retrieved passage takes
  this to ~0.99 wherever integrity holds.
- **Lexical retrieval alone has a hard ceiling on appendix provisions.** BM25 never
  retrieves Appendix B's `Plus.22 Title I Supervisor` line even at depth 30; dense
  retrieval reaches it at depth 8. Interleaving the two beats either alone (P@8 0.944
  against 0.889), and reciprocal-rank fusion is worse than interleaving because it
  rewards agreement, which is the opposite of what makes the pair useful.
- **Absence must be re-queried before it is accepted.** This took discussion-status
  accuracy from 0.658 to 0.947, and every absence it overturned was an appendix or
  special-employee-group provision.
- **Retrieval needs no service.** Passages, the FTS5 index and the embeddings are one
  SQLite file; dense queries take ~19 ms.

## Cost, now measured rather than assumed

| | scaling | corpus total |
| --- | --- | --- |
| verify (per-question) | flat, ~213–269 calls per document regardless of length | ~9,100 calls |
| sweep (full-document) | with document length: 11 windows for Manchester, ~146 for Dallas | ~4,100 calls |

Two consequences that were not obvious beforehand:

- **Sweep is cheaper corpus-wide**, because it scales with total text rather than with
  question count. But it concentrates cost on the largest documents.
- **Verify's cost is driven by the absence rate**, not by length. Anoka, a 4-page
  document, took 18.5 minutes and 213 calls precisely because 92 of 106 questions hit the
  expensive absence-verification path. Documents that legitimately answer few questions
  are the *most* expensive per answer.

## Absence is the strategic problem, and topical retrieval cannot solve it

On many documents absence is the *majority* answer: 92 of 106 questions on a 4-page
tentative agreement. It is simultaneously the largest error class and the most expensive
thing to check, because every absence currently costs a re-query plus an adjudication.
Most common, most error-prone, most costly.

The obvious idea does not work, and it is worth recording why. Every passage embedding
already sits in SQLite, so the maximum similarity over *all* passages of a document is
computable in microseconds — an exhaustive search rather than a sampled one. That should
make absence measurable: "nothing anywhere in this document is close." Implemented as
`scripts/absence_support.py` and calibrated against the answer key, it **fails to
separate the two classes**: verified-absent provisions score 0.679–0.732, squarely inside
the verified-present range of 0.591–0.836.

The reason is the important part. **Absence in this codebook is almost never topical
absence.** Both verified absences are fine-grained: the contract discusses special
education at length but states no special-education pay differential, and discusses health
insurance at length but never extends coverage to dependents. The topic is richly present;
only the specific proposition is missing. Any topic-level signal — dense, lexical or
hybrid — is structurally incapable of detecting that, which also explains why retrieval
always returns plausible-looking passages and why the model, given plausible material, is
biased toward asserting the provision exists rather than declining.

A strategy for absence therefore has to work at proposition level, not topic level:

1. **Cross-document exemplar probes.** For a question that other documents *do* answer,
   search this document using the actual clause text from those documents rather than the
   question wording. Searching for the thing itself is far sharper than searching for a
   description of it, and it is only possible because there is a corpus. Designed, not yet
   tested.
2. **Per-question, per-document-type priors.** With 36 documents the base rate of each
   question is learnable. An absence on the one CBA out of 30 that lacks a provision is
   suspicious; an absence in a document type that never carries it is expected. This is
   proposition-level by construction and is the strongest lever available today.
3. **Contrastive prompting.** Instead of "does this document provide X", show the model
   what X looks like elsewhere and ask whether anything here is equivalent or whether it is
   genuinely absent. Replaces an open-ended judgement with a comparison.
4. **Symmetric scrutiny.** Today absences are challenged and presences are not, which
   pushes the model toward over-claiming — exactly what DeKalb showed. Weakly supported
   *presences* deserve the same challenge.
5. **Structural gating.** Where a whole article is missing, discharge the entire question
   family once against the document's structure rather than re-verifying each member.

Items 2, 4 and 5 are cheap and can be built now. Item 1 needs the corpus run first, since
it depends on having extracted provisions from other documents.

## Recommendation

1. ~~Fix index coverage.~~ **Not needed** — retracted above, it was a measurement error.
2. ~~Require citation integrity ~1.000 per document type.~~ **Done for three types**
   (CBA 1.000, tentative agreement 1.000, handbook 0.672 → 1.000). Keep running
   `scripts/audit_citations.py` on each new document type before trusting its output; it
   needs no answer key.
3. **Then** run the corpus and draw the stratified accuracy sample.
4. **Rebuild absence handling at proposition level** using the priors and symmetric
   scrutiny above. This is the highest-value open problem, replacing index coverage.
5. **Do not treat low answer coverage as failure.** Report it per document type so the
   expected variation is visible, and reserve judgement for integrity and for absence
   claims the text contradicts.
6. **Treat every accuracy figure in `extraction_results.md` as development-set only.**
   Manchester was used to build the pipeline and cannot also measure it.

## The 6 excluded documents

Six of the 42 have no usable extracted text and are silently absent from everything
above: they are not indexed, so they would yield nothing. That is 14% of districts. They
need OCR before they can be coded at all, and the pipeline should say so out loud rather
than quietly skipping them.
