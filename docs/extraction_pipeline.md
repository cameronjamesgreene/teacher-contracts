# Contract question extraction: how to run it

Extracts the 106-question codebook from a contract PDF, with a verbatim quote and a
correct PDF page for every substantive answer.

Everything is local. Retrieval needs no service: passages, the FTS5 index and the
embeddings all live in one SQLite file. The only network call is to the SOM LLM
endpoint.

## Setup

```sh
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -r requirements.txt
export SOM_HPC_LLM_API_KEY=...        # or scripts/som_api_key.txt
```

`fastembed` runs `BAAI/bge-small-en-v1.5` through ONNX Runtime, so there is no PyTorch
dependency (~238 MB venv in total). Python 3.13, not 3.14: onnxruntime has no 3.14 wheels.

## Check the corpus first

Extracted text is not in the repository — it is gitignored and regenerable — so a fresh
checkout has PDFs and no text. Everything downstream is derived from that text, so
verify it before building anything on it:

```sh
.venv/bin/python scripts/verify_corpus.py --extract
```

This recomputes each PDF's and each text's sha256 against
`output/extraction/corpus_manifest.csv` and reports one of `ok`, `needs_ocr` (no text
layer — expected for the scans) or `mismatch` (the text differs from what the answer
keys were built against, so results are not comparable).

Documents reported `needs_ocr` are handled by `scripts/run_ocr.py`; see
`docs/ocr_scanned_documents.md`.

## Build the index

```sh
# 1. page-aware FTS5 passages for every PDF with usable extracted text
.venv/bin/python scripts/contract_search.py --db cache/contract_search_structural.sqlite3 index

# 2. dense embeddings into the same file (~16 min for 12,177 passages, CPU only)
.venv/bin/python scripts/sqlite_vectors.py
```

Both are idempotent and resumable. `sqlite_vectors.py` skips passages it has already
embedded, so an interrupted run can simply be repeated.

Sanity check:

```sh
.venv/bin/python scripts/sqlite_vectors.py --query "job share health insurance premium"
```

## Run the extraction

Two extractors are run and then reconciled, because they fail on different questions.
For the corpus, or for more than one document, use the driver:

```sh
.venv/bin/python scripts/run_extraction.py --all
```

It runs sweep → verify → reconcile → citation audit per document into
`output/extraction/results/<document_id>/`, skips stages whose output already exists
(so an interrupted run resumes by re-running the same command), and bounds concurrency
against the endpoint's ~24-32 in-flight ceiling. Note that cost tracks the *absence
rate*, not length: a 4-page tentative agreement took 18.5 minutes because 92 of its
106 questions hit the absence-verification path.

The stages individually, for one document:

```sh
DOC=manchester_school_district__83__de5d62c9
R=output/extraction/results/$DOC

# A: full-document sweep — reads every page in overlapping windows, ~33 calls
.venv/bin/python scripts/grind_sweep.py  --document-id $DOC --out $R/sweep.jsonl

# B: per-question retrieval with absence verification — best single extractor, ~254 calls
.venv/bin/python scripts/grind_verify.py --document-id $DOC --out $R/verify.jsonl

# reconcile (deterministic, no model calls)
.venv/bin/python scripts/grind_reconcile.py \
    --input B=$R/verify.jsonl --input A=$R/sweep.jsonl --out $R/ensemble.jsonl

# optional completeness polish: adds grounded subset variations, never removes anything
.venv/bin/python scripts/grind_subset.py --input $R/ensemble.jsonl --out $R/final.jsonl
```

Every stage takes `--document-id`, and reconcile/subset infer it from their input when
it names one document. None of them will ground a quote against a document you did not
name — the retrieval and grounding functions have no default document, because when
they did, a forgotten argument silently derived page numbers from the wrong contract.

Both extractors support `--resume`, and `--scored-only` (verify) or `--gold-only`
restricts to the 38 questions covered by the answer key for fast iteration.

## Hand the answers to the rest of the project

```sh
.venv/bin/python scripts/grind_to_dataset.py output/extraction/results/*/ensemble.jsonl
```

This writes `llm_main_dataset.csv` (wide) and `llm_coding_log.csv` (long) into
`utils.OUT_DIR`, with the same 436-column schema `llm_extract.py` produces — so
`salary_schedule.py` and the audit workbooks consume the grind pipeline's output
without knowing it changed. Set `CONTRACT_OUT_DIR` to choose the run directory.

## Score it

```sh
.venv/bin/python scripts/grind_score.py \
    --jsonl output/extraction/results/ensemble.jsonl --label ensemble
```

Deterministic, no model calls, about a second. Five fields per question: discussion
status, required tokens, completeness, page, and whether the quote is verbatim and
contiguous.

The answer key currently covers **Manchester only** (`output/extraction/answer_gold.csv`,
38 questions). Scoring another document requires building a key for it first; pass
`--document-id` and `--gold`.

## Output format

One JSON object per line:

```json
{"document_id": "...", "batch": 1, "answers": [
  {"question_id": "...", "answer": "...", "evidence": "...",
   "page": "12;50", "confidence": "high", "coder_notes": "..."}]}
```

## Three invariants worth knowing before you change anything

These are enforced in code, not in prompts, because each was learned from a measured
failure. See `docs/extraction_results.md`.

1. **The host owns the page number.** The model is never shown or asked for a page. It
   cannot distinguish the number printed on a page from the PDF page, and in this
   corpus those differ by 0 to 18 pages depending on the document. The page is derived
   from the passage the quote was found in.
2. **Evidence must be one contiguous verbatim span.** Quotes stitched from separated
   fragments are rejected; a per-fragment containment check silently accepted them
   before and lost the governing clause.
3. **An absence claim is never accepted on the first pass.** `not_discussed` is
   re-queried with contract vocabulary before it stands, and `no` requires an explicit
   denial in the text.

## Layout

```
scripts/
  verify_corpus.py      PDF/text checksums against the frozen manifest — run this first
  run_ocr.py            OCR driver: engines -> arbitration -> adoption -> manifest
  run_extraction.py     corpus driver: sweep -> verify -> reconcile -> audit, per document
  grind_to_dataset.py   JSONL -> the wide/long CSV pair the v9 programs read
  contract_search.py    page-aware FTS5 passage index and BM25 search
  sqlite_vectors.py     dense embeddings in the same SQLite file + brute-force search
  grind_retrieve.py     shared layer: fused retrieval, grounding, page derivation
  grind_sweep.py        extractor A, full-document windowed sweep
  grind_verify.py       extractor B, per-question with absence verification
  grind_reconcile.py    deterministic ensemble of A and B
  grind_subset.py       completeness pass for subset variations
  grind_score.py        deterministic scorer against the answer key
  evaluate_question_extraction.py   blinded A/B review harness
output/extraction/
  corpus_manifest.csv   frozen document list with checksums
  answer_gold.csv       verified answer key (Manchester, 38 questions)
  retrieval_gold.csv    verified retrieval labels (36 questions)
  results/              extractor outputs and scores
  blinded_review/       the review packet the answer key came from
  baseline/             the previous extractor's output, for comparison
```
