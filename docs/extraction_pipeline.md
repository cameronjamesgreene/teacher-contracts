# Contract question extraction: how to run it

Extracts the 106-question codebook from a contract PDF, with a verbatim quote and a
correct PDF page for every substantive answer.

Everything is local. Retrieval needs no service: passages, the FTS5 index and the
embeddings all live in one SQLite file. The only network call is to the SOM LLM
endpoint.

## Setup

```sh
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python openai pydantic fastembed
export SOM_HPC_LLM_API_KEY=...        # or scripts/som_api_key.txt
```

`fastembed` runs `BAAI/bge-small-en-v1.5` through ONNX Runtime, so there is no PyTorch
dependency (~183 MB venv in total).

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

```sh
DOC=manchester_school_district__83__de5d62c9

# A: full-document sweep — reads every page in overlapping windows, ~33 calls
.venv/bin/python scripts/grind_sweep.py  --out output/extraction/results/sweep.jsonl

# B: per-question retrieval with absence verification — best single extractor, ~254 calls
.venv/bin/python scripts/grind_verify.py --out output/extraction/results/verify.jsonl

# reconcile (deterministic, no model calls)
.venv/bin/python scripts/grind_reconcile.py \
    --input B=output/extraction/results/verify.jsonl \
    --input A=output/extraction/results/sweep.jsonl \
    --out output/extraction/results/ensemble.jsonl

# optional completeness polish: adds grounded subset variations, never removes anything
.venv/bin/python scripts/grind_subset.py \
    --input output/extraction/results/ensemble.jsonl \
    --out output/extraction/results/final.jsonl
```

Both extractors support `--resume`, and `--scored-only` (verify) or `--gold-only`
restricts to the 38 questions covered by the answer key for fast iteration.

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
