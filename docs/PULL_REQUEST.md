# Contract question extraction: a measured pipeline, and what it cost to learn

Extracts the 106-question codebook from teacher-contract PDFs, with a verbatim quote and a
correct PDF page for every substantive answer.

On the one document with a hand-verified answer key, accuracy went from **0.079 to 0.895**.
That number is the least interesting thing in this PR. What follows is written for whoever
scales this to thousands of districts, so it leads with the mechanisms, the traps, and the
things that are *not* established.

---

## 1. How it runs

```sh
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python openai pydantic fastembed ocrmac pypdf

# build the index: page-aware passages, then dense embeddings into the same SQLite file
.venv/bin/python scripts/contract_search.py --db cache/contract_search_structural.sqlite3 index
.venv/bin/python scripts/sqlite_vectors.py

# extract: two independent extractors, then a deterministic merge
.venv/bin/python scripts/grind_sweep.py  --out output/extraction/results/sweep.jsonl
.venv/bin/python scripts/grind_verify.py --out output/extraction/results/verify.jsonl
.venv/bin/python scripts/grind_reconcile.py \
    --input B=output/extraction/results/verify.jsonl \
    --input A=output/extraction/results/sweep.jsonl \
    --out output/extraction/results/ensemble.jsonl

# score against a key (about a second, no model calls)
.venv/bin/python scripts/grind_score.py --jsonl output/extraction/results/ensemble.jsonl --label ensemble
```

`docs/extraction_pipeline.md` is the full guide. Retrieval needs **no service**: passages, the
FTS5 index and the embeddings live in one SQLite file.

---

## 2. The five things that actually made it work

Each was measured. Each replaced something that seemed reasonable and was not.

**Take the page number away from the model.** The previous extractor scored **0.132** on pages
because it reported the number *printed on the page*. In these contracts printed footers run 1
behind the PDF page in the body and up to 7 behind in appendices; one citation pointed to page
59 of a 54-page PDF. Retrieval already knows the true page, so the model is never asked. This
one change accounts for most of the headline improvement.

**Never accept an absence claim on the first pass.** Wrongly answering `not_discussed` was the
dominant error in every earlier system. Re-querying with contract vocabulary before accepting
absence took discussion-status accuracy from 0.658 to **0.947**. Of 38 absence claims, the 3
overturned were all appendix or special-employee-group provisions.

**Have the model select sentence numbers, not write out quotes.** Asking a model to copy text
is asking it to do the one thing it is bad at. On a handbook, 19 of 58 answers carried a quote
that appeared nowhere in the document — the model paraphrased. Three repair tiers each
recovered a fraction. Numbering the sentences and having the model return *numbers*, with the
host slicing the span, made quotes verbatim **by construction**: 19 unciteable → **0**, with no
change on the document where it was already fine.

**Fuse lexical and dense retrieval by interleaving.** BM25 alone has a hard recall ceiling on
appendices: its P@8 and P@10 are identical, and it never retrieves Appendix B's
`Plus.22 Title I Supervisor` line even at depth 30, because that text shares no vocabulary with
"extra pay for high-need subjects". Dense retrieval finds it at depth 8.

| retrieval | P@8 | P@10 | appendix recall@8 |
| --- | --- | --- | --- |
| BM25 only | 0.889 | 0.889 | 0.375 |
| dense only | 0.861 | 0.861 | 0.750 |
| interleaved | **0.944** | **0.972** | 0.750 |

Reciprocal-rank fusion is *worse* than plain interleaving, because RRF rewards passages both
engines found and the whole value of the pair is that they fail on different questions.

**Run two extractors and merge deterministically.** A full-document windowed sweep (33 calls,
8 minutes) and per-question retrieval with absence verification (0.842 alone) fail on different
questions. The merge is arithmetic, not a model: a grounded substantive answer outranks an
absence claim, and a variant may contribute a missing figure only if its own quote verifies.

---

## 3. What is measured, and what is not

**Measured.** Citation integrity, on five documents spanning 4 to 739 pages, three document
types, and an OCR'd scan:

| document | type | pp | answered | quote real | on right page |
| --- | --- | --- | --- | --- | --- |
| Manchester | CBA | 54 | 35/38 | 1.000 | 1.000 |
| Anoka-Hennepin | tentative agreement | 4 | 14/106 | 1.000 | 1.000 |
| Providence | CBA | 84 | 77/106 | 1.000 | 0.987 |
| Dallas | policy manual | 739 | 87/106 | 1.000 | 0.954 |
| Pittsburgh | tentative agreement, OCR'd | 34 | 38/106 | 0.974 | 0.947 |

Every quote is real text from the document, on the page claimed. `scripts/audit_citations.py`
checks this with **no answer key**, so it scales to the whole corpus.

**Accuracy, against independently built keys:**

| document | score |
| --- | --- |
| Anoka-Hennepin | 0.875 |
| Providence | 0.688 |
| Dallas | 0.688 |
| Pittsburgh (OCR'd) | 0.688 |
| Manchester *(development set — contaminated)* | 0.842 |

**Not measured.** Ground truth covers **102 of 4,452 question-document pairs — 2.3%**: 5 of 42
documents, and 51 of 106 questions, of which only 16 have a key on more than one document.
Manchester was used to *build* the pipeline, so its 0.842 is optimistically biased.

Nothing here supports a corpus-level accuracy claim. `docs/extraction_next_steps.md` sets out
the sampling design that would: a two-phase stratified sample of 200–400 labelled pairs with
inverse-probability weighting, rather than labelling everything.

---

## 4. Traps. Read this section twice

These cost real time and every one of them looked fine from inside the pipeline.

**Citation integrity cannot see OCR errors.** The audit verifies a quote against the *extracted
text*. For a scan, that text *is* the OCR output, so OCR errors are structurally invisible.
olmOCR-2 emitted a fabricated image URL on a blank page; that string is in the text, so an
answer quoting it scores 1.000 on every check. **Internal consistency is not fidelity.**

**Generative OCR hallucinates; classical OCR does not.** Four engines on four pages whose
contents were verified by hand:

| engine | verified figures | corrupted | hallucinations | loop ratio |
| --- | --- | --- | --- | --- |
| olmOCR-2 | 0 of 3 | 3 of 3 | 2 | 0.156 |
| GLM-OCR | 0 of 3 | 0 of 3 | 0 | 0.018 |
| DeepSeek-OCR-2 | *empty output* | — | — | — |
| Apple Vision | **3 of 3** | 0 | 0 | 0.383 |

`195 days` became `135 days`; `eight (8) hours` became `eighty (8) hours`. A VLM *reconstructs*
a page, so on a hard layout it smooths, transposes, loops or invents. Character accuracy rewards
fluency; **fact recall punishes confabulation**, and this codebook wants facts.

**Multi-engine voting does not work here.** Pairwise figure agreement is 0.12–0.34, so engines
disagree three ways with no majority — and the correct values were found by *exactly one*
engine. A vote discards the only correct reading. `scripts/ocr_reconcile.py` arbitrates instead:
per page, drop engines failing a degeneracy gate, then prefer the figure-authority engine when
figures disagree and the prose-authority engine when they agree, recording the decision for
every page. Degenerate pages went **28/299 → 0**.

**Absence is the hard problem, and retrieval cannot solve it.** Two mechanisms were built and
both failed to separate present from absent: exhaustive dense similarity over every passage, and
probing with another document's evidence for the same question. The reason is that absence here
is almost never *topical* — a contract discusses special education at length and never states a
special-education pay differential. Similarity measures topical proximity; these absences are
propositional. `scripts/grind_contrast.py` therefore uses another contract's clause as a
*comparison target for judgement*, not as a search query.

**Your reference standard is uncertain too.** On Providence, four of five apparent errors were
cases the reviewer explicitly flagged as arguable — and our answer matched the alternative
reading *they named*. One they put at 55/45. Single-reviewer keys need double-coding with a
reported inter-annotator agreement before accuracy figures carry weight.

**Beware scorers that punish better answers.** `classify()` recognised only a bare `no`, so
*"No, the document grants a maternity leave but does not specify that it is paid"* — semantically
the exact gold answer — scored wrong. Fixing that alone moved Providence 0.625 → 0.688.

**Re-running OCR invalidates prior extractions.** Answers are grounded against the extracted
text; replace the text and old quotes point at nothing. Swapping engines dropped an audit from
1.000 to 0.789 — not a quality change, just answers checked against text they were never
derived from. Treat the OCR engine as part of a result's provenance.

---

## 5. Scaling to thousands of districts

**Costs, measured.** Per-question extraction is roughly flat at 210–290 model calls per
document regardless of length. The full-document sweep scales with text: 11 windows for a
54-page contract, ~146 for a 739-page one. Across 36 documents that is ~9,100 calls for verify
and ~4,100 for sweep. Embedding is ~13 passages/second on CPU; 12,700 passages took 16 minutes.

**The counter-intuitive cost driver:** verify's expense is the *absence rate*, not length. A
4-page tentative agreement took 18.5 minutes because 92 of 106 questions hit the expensive
absence path. Documents that legitimately answer fewest questions are the most expensive per
answer. At thousands of districts this dominates, and it is the strongest argument for building
the per-question priors described in the next-steps doc.

**Document type matters more than size.** A 4-page tentative agreement answering 14 of 106
questions is *correct*, not broken. Report coverage per document type so expected variation is
visible, and never treat low coverage as failure on its own.

**OCR at scale.** 14% of this corpus was image-only and invisible to everything until OCR'd.
Budget for it, run two engines, and gate on `scripts/ocr_quality_gate.py` — it catches
repetition loops by compression ratio and fabricated content by URL markers, both without a
reference text.

**What to build first at scale**, in order:
1. Per-question, per-document-type priors from the corpus. The only absence signal that is not
   similarity-based, and it targets verification budget where it changes answers.
2. Symmetric scrutiny — absences are challenged today and presences are not, which biases the
   model toward over-claiming.
3. Cross-document exemplars fed to judgement, not to retrieval.
4. The stratified accuracy sample. Human review is the binding constraint, not compute.

---

## 6. What is in this PR

```
scripts/
  contract_search.py     page-aware FTS5 passage index and BM25 search
  sqlite_vectors.py      dense embeddings in the same SQLite file; brute-force search
  grind_retrieve.py      shared layer: fused retrieval, grounding, page derivation
  grind_sweep.py         extractor A — full-document windowed sweep
  grind_verify.py        extractor B — per-question with absence verification
  grind_reconcile.py     deterministic ensemble of A and B
  grind_subset.py        completeness pass for subset variations
  grind_contrast.py      absence recheck against another contract's clause
  grind_score.py         deterministic scorer against an answer key
  audit_citations.py     citation integrity with no answer key required
  absence_support.py     absence signals (records two negative results)
  absence_triage.py      base rates and exemplar probes (records a negative result)
  ocr_scanned.py         OCR for image-only scans: HPC olmOCR-2 or local Apple Vision
  ocr_quality_gate.py    degeneracy and cross-engine figure disagreement
  ocr_reconcile.py       per-page multi-engine arbitration with provenance
  ocr_adjudicate.py      figure disputes settled on internal consistency
output/extraction/
  answer_gold.csv        verified key, Manchester (38 questions)
  keys/*.csv             verified keys for four further documents (16 questions each)
  retrieval_gold.csv     36 verified retrieval labels
  corpus_manifest.csv    frozen document list with checksums, repo-relative paths
  blinded_review/        the review packet the Manchester key came from
  results/               extractor outputs, scores, per-document audits
  ocr_provenance/        which OCR engine supplied each page, and why
docs/
  extraction_pipeline.md         how to run it
  extraction_results.md          what was measured, and its limits at length
  extraction_strategy_review.md  written for collaborators; leads with what broke
  extraction_next_steps.md       the sampling design for a corpus-level claim
  ocr_scanned_documents.md       OCR engine choice and end-to-end check
  ocr_fidelity_warning.md        why the audit cannot see OCR errors
```

Both test suites pass. Approaches that were measured and rejected are documented with their
numbers, including two that looked obviously right beforehand.

---

## 7. Honest summary

The pipeline is **demonstrably honest about its sources** and **largely unmeasured on
correctness**. Those are very different claims and the first is much stronger than the second.

The most useful thing here may not be the code but the record of what failed: index coverage
that turned out to be a measurement error of my own, an eager quote-repair that made things
worse, two similarity-based absence detectors that could not work in principle, a monotonicity
check that got the one known case backwards and was deleted, and an OCR engine that fabricated
a URL on a blank page. Each of those is a trap someone scaling this would otherwise re-enter.
