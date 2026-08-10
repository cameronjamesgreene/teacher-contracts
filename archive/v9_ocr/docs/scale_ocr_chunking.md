# Scale OCR: page-range chunking

Design note for OCR-ing thousands of district contracts on the Yale SOM HPC via
`yale-som-hpc/ocr-examples`. Reference implementation: `scripts/chunk_ocr.py`.

## The problem

`docling-serve` converts **one whole PDF per HTTP request**. That's fine for
small docs but breaks down at scale on the large scanned contracts that are
common in this corpus (100–300+ pages):

1. **Timeouts.** A 287-page scan is a single ~20-minute request. It blew past
   docling-serve's default 120 s sync-wait (`DOCLING_SERVE_MAX_SYNC_WAIT`) and
   the client's 600 s read timeout, returning `504 Gateway Timeout`. (We raised
   both to 3600 s as a stopgap — see `hpc/slurm/docling_serve.slurm` and
   `hpc/client/docling_http_client.py` — but that only defers the ceiling.)
2. **No parallelism within a document.** One PDF pins exactly one GPU worker for
   the whole run. A 287-page doc can't use the other GPUs even when they're idle.
3. **All-or-nothing failure.** If page 280 fails (OOM, a malformed page, a
   dropped tunnel), the whole 20-minute job is wasted and restarts from page 1.

At 3 documents the timeout bump is enough. At thousands it is not.

## The pattern

Split each PDF into fixed-size **page-range chunks** (~25 pages), OCR every
chunk as an independent unit across the worker pool, then concatenate each
document's chunks back in page order.

```
 source.pdf (287p)
   │  split (chunk-size 25)
   ▼
 chunk 00 (pp 1–25)  chunk 01 (pp 26–50)  …  chunk 11 (pp 276–287)
   │                    │                        │
   └──────── OCR all chunks across N GPU workers (ocr-examples) ────────┐
                                                                        ▼
                          concat in page order  →  cache/ocr_text/<document_id>.txt
```

### Why it's better

- **Timeout-safe.** A 25-page chunk is ~2 min — comfortably under even the
  *default* 120 s, so it works regardless of the server-side cap.
- **Parallel.** A 287-page doc's 12 chunks spread across the worker pool; and
  chunks from *many* documents keep every GPU busy. Wall-clock for one big doc
  drops from `pages × per_page` to `≈ (chunks / workers) × per_chunk`.
- **Failure-isolated + resumable.** Each chunk's output is cached
  independently. A failed chunk retries on its own; the other 11 are untouched.
  Re-runs only redo missing chunks.
- **No changes to the HPC service.** Chunking wraps the existing ocr-examples
  workflow with a pre-split and a post-concat. The GPU side stays stock.

## Workflow

```sh
WORK="/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG"
OCR=~/ocr-examples

# 1. split every OCR-needed source PDF into 25-page chunks (stages chunk PDFs,
#    writes chunk-ids.txt + chunk_manifest.json)
python3 "$WORK/scripts/chunk_ocr.py" split --chunk-size 25

# 2. OCR all chunks with the normal ocr-examples workflow — many workers, since
#    there are now many small units to spread across GPUs
cd "$OCR"
export HPC_USER=cjg79
uv run --script scripts/documents_process.py \
  --from-file       "$WORK/cache/ocr_documents/chunk-ids.txt" \
  --documents-root  "$WORK/cache/ocr_documents/chunks" \
  --stages ocr --engines docling \
  --use-hpc --hpc-workers docling=8 --hpc-in-flight docling=2

# 3. reassemble each source document from its chunks into the override slot
python3 "$WORK/scripts/chunk_ocr.py" concat
```

Step 3 writes `cache/ocr_text/<document_id>.txt` — the same OCR override slot
`utils.extract_text()` prefers — so all three coding pipelines consume the
chunked OCR text with no further change. `chunk_ocr.py concat` supersedes
`splice_ocr.py` for any document that was chunked.

## Design parameters

| Parameter | Default | Notes |
|---|---|---|
| `--chunk-size` | 25 pages | ~2 min/chunk at current docling throughput (~4.3 s/pg on RTX 8000), safely under the 120 s default cap. Smaller = finer retry granularity + more parallelism, but more per-request overhead. |
| workers (`--hpc-workers docling=N`) | scale to N GPUs | The chunk queue is large; N workers drain it continuously. Size to your cluster GPU allocation. |
| overlap | 0 pages | Contracts split cleanly at page boundaries. If a table/section routinely spans a boundary, add a 1-page overlap and dedup at concat. |

## Scale considerations

- **Chunk UUIDs are deterministic** — `uuid5(document_id + page-range)` — so
  re-splitting is idempotent and a chunk's OCR output is stable/cacheable.
- **Provenance.** `chunk_manifest.json` records `parent_document_id`,
  `chunk_index`, and `page_start/page_end` for every chunk. Keep it: it lets you
  re-OCR a *specific* page range (e.g. a salary-schedule table that came out
  poorly) without redoing the document, and it ties OCR text back to source
  pages for auditing.
- **Page structure.** Concatenation inserts a form-feed (`\f`) between chunks,
  so `text.split("\f")` yields chunk-level segments. That's coarser than true
  per-page boundaries; if the pipelines need exact page citations, emit
  docling's page-level output and delimit per page instead. (The current
  pipelines send full text to the LLM, so this is a refinement, not a blocker.)
- **Where this fits the larger scale pipeline.** Chunking is the OCR stage of
  the broader rebuild discussed for thousands of districts: object store for the
  corpus (not Dropbox), a results DB keyed by `(document_id, question_id)`
  instead of wholesale-rewritten CSVs, idempotent/resumable/parallel stages, and
  automated QA. Chunk-level caching + the manifest are exactly the
  idempotence/provenance that stage needs.

## Status

`scripts/chunk_ocr.py` implements `split` and `concat`. For the current 3-doc
sample the whole-file path (with the raised timeouts) is sufficient and already
in use; chunking is the pattern to switch to when the corpus grows.
