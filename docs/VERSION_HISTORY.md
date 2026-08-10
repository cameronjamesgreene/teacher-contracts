# Version history — what survives, and what does not

## v12, 2026-08-06 to 2026-08-10: Kyle's extractor integrated into the v9 program

**v12 is the current version.** `utils.CURRENT_VERSION` carries the string and
`OUT_DIR` defaults to `output/output_v12`, so a run writes to the right place without
anyone remembering to set `CONTRACT_OUT_DIR`.

### What v12 covers, and what it does not

v12 ran the **106-question extraction over all 42 documents** — 3,093 substantive
answers, citation integrity 0.998 verbatim / 0.995 on-page, zero failed or degraded
documents. The deliverable is `output/output_v12/contract_coding_v12.xlsx`.

It has **not** run `salary_schedule.py` or `rights_score.py`. Both are wired to consume
v12 output through `grind_to_dataset.py` and neither has been executed since the
integration, so v12 currently has no salary grids and no rights scores. Any comparison
against v9-v11 on those two programs is therefore not yet possible.

### There is no v12 audit workbook

`audit_report_v1..v11.xlsx` are a different artefact from anything v12 has produced.
They are **independent quality audits**: a separate agent re-read sampled answers
against the source PDFs and graded each one (`Status`, `Audit Note`, `Verify Note`),
across all three programs. That is a judgement of correctness on a sample.

`contract_coding_v12.xlsx` is the **output dataset** plus two measurements: mechanical
citation integrity on every answer, and scores against the five pre-existing answer
keys. Nobody re-read any v12 answer against a PDF. The two artefacts answer different
questions and the workbook must not be filed as if it were an audit.

Producing a real `audit_report_v12.xlsx` needs: a sample drawn across the 42 documents,
an independent agent grading each sampled answer against the PDF, and — to match the
v9/v11 format — `salary_schedule` and `rights_score` to have been run at all.

`main` had held both programs side by side since the merge (`f66db2a`) — they shared
`utils.py` and nothing else. This is the integration.

**Two regressions from our own merges, which had broken Kyle's pipeline outright:**

* The v9 restore (`9541b0e`) reverted `PDF_ROOT` to `ROOT/nctq_contracts`, a directory
  that does not exist. Restored to `WORK/raw`. This is not cosmetic: `document_id` is a
  sha256 of the PDF path *relative to ROOT*, so `raw/` is what makes the ids in
  `corpus_manifest.csv` and every answer key resolve. Verified — 36 of 42 documents
  reproduce their frozen text checksum byte-for-byte, and Manchester still hashes to
  `de5d62c9`.
* The output consolidation (`b2a7b3c`) moved `output_v*/` under `output/` while
  `OUT_DIR` still pointed at the old location, breaking the *v9* programs. `OUT_DIR`
  now resolves under `output/` and accepts either spelling.

**The Manchester leak.** `grind_retrieve.ground/exact_page/fused_passages/document_pages/
locate_in_document` all defaulted to `doc=MANCHESTER`, and six call sites omitted the
argument — including `grind_reconcile`, which also stamped Manchester's `document_id`
onto whatever it reconciled. On any other document that derived page numbers from
Manchester's pages: confident, plausible, wrong. The defaults are gone, the functions
raise without an explicit document, and `tests/test_document_binding.py` fails if a
default comes back.

**New:** `verify_corpus.py` (checksums before anything is built on the text),
`run_ocr.py` (engines → arbitration → adoption → manifest), `run_extraction.py` (the
corpus driver the grind stages never had), `grind_to_dataset.py` (JSONL → the
436-column wide/long CSV pair, so `salary_schedule.py` and the audit workbooks consume
the new extractor unchanged).

**OCR:** Kyle's stack is now the front door; the v9 OCR cluster moved to
`archive/v9_ocr/` (nothing in the live pipeline imported it). See that directory's
README for the measurements that motivated the switch.

**Regression checks, all passing on the modified code.**

*Deterministic, on Kyle's saved output:* `grind_score` returns `overall=0.895
status=0.947 req=0.921 cov=0.774 page=0.921 ev=1.000` — every figure matching his
table. `audit_citations` reproduces his per-document rates exactly for every document
whose text did not change.

*A fresh end-to-end run of Manchester*, through `run_extraction.py`, 24 minutes:

| run | overall | status | required | complete | page | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| sweep (A), fresh | 0.684 | 0.842 | 0.737 | 0.504 | 0.789 | 1.000 |
| verify (B), fresh | 0.816 | 0.947 | 0.868 | 0.747 | 0.921 | 1.000 |
| ensemble, fresh | 0.842 | 0.947 | 0.895 | 0.747 | 0.921 | 1.000 |
| ensemble, Kyle's saved run | 0.895 | 0.947 | 0.921 | 0.774 | 0.921 | 1.000 |

The sweep hits **0.684 exactly**, and status (0.947), page (0.921) and evidence
(1.000) are identical across both runs — those three are the invariants the design
enforces in code rather than in prompts, and they reproduce exactly. Overall lands
0.053 below Kyle's saved ensemble, which is inside the run-to-run noise he measured
and documented (three identical sweep configurations scored 0.658 / 0.684 / 0.737 at
temperature 0; "single-run differences under about 0.05 are not signal"). The fresh
run's citation audit is **verbatim 1.000, contiguous 1.000, on_page 1.000** on 72 of
106 answered questions.

### The six scans were rebuilt, and what that cost

The OCR text for the six scans **did not survive**. It was a build artifact of a temp
directory on one machine and is in no checkout. It has been rebuilt from scratch with
both engines — Apple Vision locally, olmOCR-2 on the HPC GPUs (45 min for 299 pages) —
and arbitrated per page by `ocr_reconcile.py`.

**The rebuild closely reproduces Kyle's.** Per-document olmOCR-2 output is within 1–4%
of what his manifest froze, and the arbitration reaches the *same decision on the same
pages* for three of six documents:

| document | pages by engine, this rebuild | Kyle's original | |
| --- | --- | --- | --- |
| Dayton | olmocr2=5 | olmocr2=5 | identical |
| Pittsburgh | none=1, apple=19, olmocr2=14 | none=1, apple=19, olmocr2=14 | identical |
| San Bernardino | apple=3, olmocr2=5 | apple=3, olmocr2=5 | identical |
| Sacramento | apple=4, olmocr2=43 | apple=5, olmocr2=42 | 1 page differs |
| New York City | apple=8, olmocr2=55 | apple=4, olmocr2=59 | 4 pages differ |
| Fresno | apple=84, olmocr2=58 | apple=58, olmocr2=84 | **mirrored** |

Pittsburgh matching exactly is the meaningful one: it is the hardest document in the
set — olmOCR-2 degenerated on 7 of its 34 pages and one page is blank — and the
arbitration reproduced every decision including the blank.

**Fresno is unstable and its figures deserve scrutiny.** Figures disagreed on 66 of its
142 pages, which pushed those pages to the figure-preferred engine and inverted the
split against Kyle's run. Two runs of the same pipeline disagreeing this much on one
document is the arbitration doing its job — surfacing disagreement rather than hiding
it — but any numeric answer citing Fresno should be checked against the PDF.

**Still stale.** `output/extraction/keys/pittsburgh.csv` was hand-verified against text
that no longer exists. The rebuilt text is very close, but "very close" is not the same
text: that key's quotes and pages need re-validation before it is used again, and
Kyle's Pittsburgh accuracy figure (0.688) is not reproducible until it is.

## Corrected 2026-08-04: v10 *is* preserved on GitHub.

The `teacher-contracts` repo (github.com/cameronjamesgreene/teacher-contracts, commit
`f85690b` "first upload to git for meeting with Kyle") contains a full snapshot of the
pipeline whose `scripts/*.py` are **byte-identical to the v10 baseline** — som_client,
llm_extract, salary_schedule, rights_score and utils all match commit `d1da2c3` exactly.
So v10 code is recoverable, and a v10-vs-v11 diff is possible.

v1–v9 remain unrecoverable. The statement below applies to those.

## There is no code history for v1–v9.

`git init` was run on 2026-08-03, at the start of the v11 work. The first commit
(`d1da2c3`, "Baseline: v10 pipeline as deployed") is a snapshot of v10 as it stood that
day. Everything before it is unrecoverable: each version edited `scripts/*.py` **in place**
and was synced to the HPC by `scp`, which overwrites. There are no dated copies, no `.bak`
files, no tags, no branches. The `cache/_v6_/_v7_/_v8_bak` directories on the HPC are
CACHES, not code.

Consequences, stated plainly:

* We cannot diff v8 against v9, or reproduce any pre-v10 result. (v10 vs v11 IS diffable,
  via the teacher-contracts snapshot.)
* We cannot attribute an accuracy change to a code change for any version before v11.
* The rights polarity inversion found in the v11 audit is present in `classify_statement_type`
  in the v10 snapshot, but we still cannot say when it was introduced.
* Every audit workbook v1–v10 grades a code state that no longer exists in retrievable form.

## What DOES survive: results and audits

Reconstructed from file mtimes and the `document_id` values inside each version's CSVs.
Dates are filesystem mtimes and are approximate — Dropbox sync can rewrite them.

| version | first | last | files | docs coded | audit workbook |
|---|---|---|---|---|---|
| `output` | 2026-05-28 | 2026-07-28 | 52 | 2 | audit_report.xlsx |
| `output_v2` | 2026-07-01 | 2026-07-20 | 58 | 2 | audit_report_2.xlsx |
| `output_v3` | 2026-05-27 | 2026-07-20 | 25 | 1 | audit_report_v3_olmocr2.xlsx |
| `output_v4` | 2026-07-20 | 2026-07-20 | 32 | 1 | audit_report_v4_olmocr2.xlsx |
| `output_v5` | 2026-07-20 | 2026-07-20 | 36 | 1 | audit_report_v5_olmocr2.xlsx |
| `output_v6` | 2026-07-20 | 2026-07-21 | 85 | 3 | audit_report_v6_olmocr2.xlsx |
| `output_v7` | 2026-07-21 | 2026-07-21 | 131 | 3 | audit_report_v7_olmocr2.xlsx |
| `output_v8` | 2026-07-21 | 2026-07-22 | 64 | 1 | audit_report_v8_olmocr2.xlsx |
| `output_v9` | 2026-07-22 | 2026-08-03 | 402 | 15 | audit_report_v9.xlsx |
| `output_v10` | 2026-07-27 | 2026-07-27 | 3 | 0 | audit_report_v10 copy.xlsx |
| `output_v11` | 2026-08-04 | 2026-08-04 | 102 | 10 | audit_report_v11.xlsx |
| `output_v12` | 2026-08-06 | 2026-08-10 | — | **42** | **none yet — see below** |

Also surviving: `archive/` holds pre-v1 material (the original `extraction_elements.md`,
`llm_agent_prompt.md`, `merge_llm_parts.py`, and the June DCPS manual-verification
workbooks), and the HPC keeps driver scripts that were never copied down
(`run_new15.py`, `ramp_driver.py`, `run_c6.py`, `verify_v4_full.py`).

## From v11 onward

Every change is committed with the measurement that motivated it. `store.py` records
`run.git_rev` per run, and `som_client.request_cache_key` hashes the prompt version into
every cache entry, so a result can be traced to the code that produced it. That was not
true for any earlier version.

## Done 2026-08-04

1. Tagged `v11`; pushed tag to the remote.
2. Pushed the full 17-commit history to
   `github.com/cameronjamesgreene/teacher-contracts` as branch **`v11-overhaul`**.
   `main` is untouched and still holds the v10 snapshot, so the two are directly comparable.
3. Audit workbooks for every version are now force-tracked in git — previously they sat
   untracked under gitignored `output_v*/` directories and were the only surviving record of
   v1–v10 quality.

## Still recommended

* Tag each future version at the commit that produced its run, rather than reconstructing
  from mtimes afterwards.
* `teacher-contracts` tracks 9,279 `cache/*.json` files and carries a 417 MB `.git`. Those
  are regenerable API-response caches; gitignoring them would shrink the repo substantially.
  This overhaul's repo excludes them deliberately (56 tracked files).
