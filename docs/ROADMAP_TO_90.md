# Getting to 90%+ — an engineering roadmap

## The framing that matters: we are compute-rich and accuracy-poor

Two measured facts sit next to each other:

- The pipeline uses roughly **2% of a shared inference endpoint** (12 in-flight of ~44 admitted), and the SOM cluster has **2 fully idle GPU nodes, 6 idle RTX8000s and 2 H100 nodes**, with a working vLLM Apptainer SLURM template already in `~/ocr-examples/hpc/slurm/`.
- Accuracy is **~56% strict / 80% acceptable** on the v11 audit, and the model doing the work is `Qwen3.6-35B-A3B` — a mixture-of-experts with only **~3B active parameters per token**.

Throughput is no longer the binding constraint; it stopped being one when calls/document fell from ~425 to ~61. **Every remaining lever that trades compute for accuracy is therefore cheap, and we are not pulling any of them.** That is the core of this roadmap.

## The problem with "70–80%"

There is no random-sample measurement of this pipeline. There never has been.

| audit | sampling | why it can't support a target |
|---|---|---|
| `output/audit_report.xlsx` | full census, **4 documents** | 2 of 4 are Utah districts; gold for CORRECT rows is the pipeline's own answer |
| v9 / v10 | ~5 questions/doc | v9 spent 19% of its LLM sample on the single easiest question |
| **v11** | ~5/doc, **deliberately adversarial** | auditor was told to over-sample disagreements: `quote_verified=False` is 24% of the sample vs **0.2%** of the corpus |

So 29% strict for rights is a lower bound on a suspicious subpopulation, and 74% strict for llm_extract is a number from 50 cells across 10 documents. **The true rate could plausibly be anywhere from 65% to 90%, and no one can currently say which.**

You cannot drive a metric you have not measured. Step 0 is not optional.

Also binding: the **measured run-to-run flip rate is 6.4%** on identical configuration. Any improvement smaller than that is invisible, and ~6% of all cells are effectively a coin flip today.

---

## Where the errors actually are

From the v11 audit, with corpus-wide rates where they exist:

| Component | strict | dominant failure | corpus rate |
|---|---|---|---|
| llm_extract | 74% | `not_discussed` on a present provision | ~15% of sampled ND were provably wrong |
| salary | 67% | structural: duplicated lanes, fabrication, truncation | 201/3,473 cells = 5.8% |
| rights | 29% | quote not verbatim; wrong bucket | **300/8,273 quotes = 3.6% unlocatable** |

And a pattern that matters more than any single number: **of the five defects found in v11, four produced completely normal-looking output.** Inert cache/telemetry, silent single-view coding, silent truncation of 22% of documents, an orphan interleaving two runs. Only two announced themselves. The self-checks are unreliable in *both* directions — `quote_verified` reported True on 8,255/8,273 rows while 300 were unlocatable, salary validation said "audit confirmed" on the two worst duplication defects, and **all four hard false negatives carried `confidence: high`.**

An accuracy program that only chases the numbers will keep shipping silent errors. Half the work below is making failure *visible*.

---

## The roadmap

### Phase 0 — Establish the real baseline (1 week, gates everything)

1. **Random stratified gold set.** 20 documents × 106 questions, stratified on (state, document type, page count, native vs scanned). Label from the **PDF**, never from pipeline output. I draft, you adjudicate only contested cells — the v11 run already flags 18% of cells, so the review queue is ~100–200 cells, not 2,120.
2. **Pin the determinism floor.** Three identical runs; report per-field flip rate. Everything downstream is measured against this.
3. **Define the target precisely.** "90%" needs to name a metric: per-field strict accuracy on a random sample, with document-clustered CIs. Recommend reporting **recall and precision separately per field type** — aggregate accuracy hides the recall problem that is the actual defect.
4. **Set and log `temperature`/`top_p`/`seed`.** Currently unset. A/B greedy vs Qwen's recommended sampling; do not assume `temperature=0` helps (thinking mode is documented to degrade under greedy decoding).

**Deliverable: a number we can defend, plus a harness that detects a 5pp change.**

### Phase 1 — Make the model's uncertainty visible (1–2 weeks)

This is the highest-value work and it is mostly *not* prompt engineering.

1. **Graded quote grounding, everywhere.** Replace the boolean with `exact | contiguous_fuzzy | spliced | absent`. The current check accepts a quote when 60% of its 4-word shingles appear *anywhere* in the document, which is exactly why a cross-passage splice passes. Only `exact`/`contiguous_fuzzy` may enter the dataset. This makes fabrication structurally impossible rather than statistically rare.
2. **Schema-constrained decoding.** Move from "JSON mode + prose instructions" to an enforced JSON schema. This eliminates an entire defect class: the Polk crash (a bare string where a clause object belonged), silently missing question ids, malformed enum values.
3. **Never-silent invariants.** Every stage asserts its own preconditions and records a degradation flag *in the output row*, not in a log: document indexed, both views ran, page count aligned, all requested qids returned. v11 added this for View B; generalise it.
4. **Calibrate or discard `confidence`.** It is currently anti-diagnostic. Either replace it with an agreement-derived score (Phase 2) or stop emitting it.

**Deliverable: every published cell is either source-grounded or flagged. "Unflagged accuracy" becomes a meaningful number.**

### Phase 2 — Spend compute on accuracy (2 weeks)

We have the headroom; we are simply not using it.

1. **Self-consistency on contested fields.** n=3 samples; unanimous → publish; split → escalate to review. This converts idle throughput directly into either accuracy or a targeted queue. Note the decision rule must stay asymmetric for existence questions (a single quoted `yes` beats two `not_discussed`), but for **values** — years, dollar amounts, counts — agreement is a strong signal and disagreement is a strong review trigger.
2. **Serve a larger model on the idle GPUs.** This is probably the single biggest lever and it is untouched. `Qwen3.6-35B-A3B` activates ~3B parameters per token; a dense 32B, or a 72B across the idle A100s, is a different class of reader for exactly the hard cases we fail — dense tables, cross-reference reasoning, long-context recall. The vLLM Apptainer template exists and the OCR pipeline already proved GPU serving works on this cluster.
   *Caveat, stated plainly:* this invalidates every A/B baseline taken against `api.som.chat`, so it must land **after** Phase 0 and be evaluated as a straight model swap on the same gold set. It also needs an allocation conversation with Kyle.
3. **Two-model cross-check on high-stakes fields.** Where two different models agree on a grounded value, confidence is real. Where they disagree, that is the review queue. This is the cheapest path to trustworthy output short of human review of everything.

**Deliverable: a measured accuracy/compute curve, and a defensible answer to "why this model".**

### Phase 3 — Component work, ranked by measured damage (2–3 weeks)

- **rights_score** — worst component, 60% of runtime. Follow `RIGHTS_IMPROVEMENT_PLAN.md`; items 1, 2 and 6 there re-score the existing 8,273 clauses **offline with no API calls**. Open question below on whether it earns its cost at all.
- **salary_schedule** — the defects are structural, not numeric. Duplicated-lane detection should be a deterministic post-check (compare every column pair — trivial, catches the worst v11 defect), not something the model is asked to avoid. Cross-validate extracted cells against the dollar amounts actually present on the page.
- **llm_extract** — the FTS5 escalation is working; extend it to *value* questions, and settle the handbook-vs-CBA distinction the audit surfaced (Jefferson Parish 87/106 `not_discussed`, Guilford 38 flagged — both handbooks).

### Phase 4 — Scale (1 week + run time)

Only after Phase 0–3 hold on the gold set:
- **Single-process driver.** The current per-process governor splits 14 permits across 3 coder processes, which is most of the gap between the 7.8 calls/min observed and 12.2 benchmarked.
- **Idempotent resumable batch.** The request-hash cache already makes re-runs nearly free (Alpine re-ran in 9.8s); build the corpus runner on top of it.
- **Continuous audit.** Sample and score every batch, so quality regressions surface during the run rather than after 1,190 documents.

---

## Honest expectations

- **Phase 0 may reveal we are already near 85%, or nearer 65%.** Both are live possibilities and they imply very different amounts of work.
- **90% strict, fully automated, on every field, is not obviously reachable** with a 3B-active model on 300-page contracts. 90% *with reliable flagging of the residual* is very reachable, and is what most research datasets actually need.
- **The largest single uncertainty is model capacity.** We have never tested whether these errors are prompt/architecture failures or capability failures. Phase 2.2 answers that, and it is cheap to try.

## The decisions that shape all of this

1. **Which output matters most?** rights is 60% of runtime at 29% strict. If it is secondary to the 106 questions, it should be deprioritised or redesigned rather than repaired.
2. **Is human review acceptable in the loop?** If yes, target "90% accurate + trustworthy flags" and the path is short. If it must be fully automated, Phase 2.2 becomes mandatory.
3. **Can we get a GPU allocation for a larger model?** This is the biggest untested lever and needs Kyle.

---

## MEASURED 2026-08-04: the failures are mostly CAPABILITY, not retrieval

Before requesting a GPU allocation, we ran the cheap decisive experiment: take documented
false negatives and hand Qwen **the exact passage containing the answer**, 2–3.5k chars, no
retrieval involved. If it answers correctly, the pipeline failure was retrieval. If it still
fails, no amount of retrieval engineering will fix it.

| case | passage contains | Qwen, given the passage |
|---|---|---|
| OKC emergency closure | Article XIII, four sections | **recovered** |
| Polk return rights | §21.6 return from leave | **recovered** |
| OKC performance pay | *"$500.00 for each student that scores a 3, 4, or 5"* | still `not_discussed` |
| Guilford probation length | *"at least three consecutive years"* / *"five consecutive years"* | still `not_discussed` |
| Polk medical/pregnancy leave | *"may be granted up to one (1) year of medical leave"* | still `not_discussed` |
| Polk class size | *"optimum class size is an important aspect"* | `no` (arguable — a goal, not a limit) |

**2 of 6 were retrieval failures. 4 of 6 persist with the answer directly in front of the
model**, and at least 3 of those are unambiguous — the required string is verbatim in a
2–3k-char passage.

### What this changes

- The retrieval work (FTS5 second view, never-silent escalation, semantic sectioning)
  addresses roughly **a third** of the failure mass. It was worth doing and it is done.
- The remaining two thirds are the model not extracting an answer that is plainly present.
  More prompt engineering, more views and more retrieval cannot fix that.
- Combined with the requirement that the pipeline be **fully automated** (no human review of
  flagged cells), a capacity upgrade moves from optional to **the critical path**.

### Caveats

n=6, chosen from documented failures, so this measures the hard tail rather than the corpus.
It does not tell us the *size* of the capability gap, only that it dominates the errors we
have. Phase 0's random sample is still required to size it. But it is enough to justify the
GPU allocation conversation, and enough to stop spending effort on retrieval.
