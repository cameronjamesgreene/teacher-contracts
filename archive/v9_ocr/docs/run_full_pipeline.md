# Run the full pipeline on new documents

End-to-end: **OCR (olmocr2 on the HPC) → all three coders**. Use this for
documents that are not already in the 40-doc sample.

## Architecture (where each step runs)

| Step | Runs on | Engine/API |
|------|---------|-----------|
| OCR | **Yale SOM HPC GPUs** | **olmocr2** (via ocr-examples) |
| `llm_extract` / `salary_schedule` / `rights_score` | **your Mac** | Yale **SOM API** (`api.som.chat`) |

So "on the HPC" = the OCR. The three coders run locally and call the SOM API for
the LLM work — that's how they're built today. (Moving the *coders* onto
HPC-served inference is the separate scale project.)

## Prerequisites

1. On the Yale VPN; `ssh hpc` works passwordlessly (key registered as `cjg79`).
2. The 3 PDFs are hydrated (not 0-byte) at `nctq_contracts/<District>/<File.pdf>`.
   That path defines the `document_id`, so OCR text lands where the coders look.
3. `scripts/som_api_key.txt` present (already is).

Set these once per shell:

```sh
WORK="/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG"
OCR=~/ocr-examples
# your 3 new documents, "District|File.pdf" each:
D1="Some District|SomeContract.pdf"
D2="Another District|Another.pdf"
D3="Third District|Third.pdf"
```

---

## Step 1 — OCR the new docs with olmocr2 (HPC)

*Skip a doc here if its PDF already has selectable text (born-digital). OCR is
for scanned/image-only PDFs. When unsure, OCR it — olmocr2 output is clean either way.*

```sh
# 1a. stage the docs into the ocr-examples layout
cd "$WORK/scripts"
python3 stage_for_ocr.py --doc "$D1" --doc "$D2" --doc "$D3"

# 1b. run olmocr2 on the HPC (c001 auto-excluded; first run downloads the model, ~10-15 min)
cd "$OCR"
export HPC_USER=cjg79
export HPC_LAUNCH_TIMEOUT_S=3600
STAGE="$WORK/cache/ocr_documents"
uv run --script scripts/documents_process.py \
  --from-file      "$STAGE/document-ids.new.txt" \
  --documents-root "$STAGE/documents" \
  --stages ocr --engines olmocr2 \
  --use-hpc

# 1c. load the OCR text into the pipeline's override slot (splice defaults to olmocr2 now)
cd "$WORK/scripts"
python3 splice_ocr.py $(sed 's/^/--uuid /' "$STAGE/document-ids.new.txt")
```

After 1c, `cache/ocr_text/<document_id>.txt` exists for each doc and every coder
picks it up automatically (via `utils.extract_text`).

---

## Step 2 — run the three coders (local, SOM API)

⚠️ **Back up first.** `llm_extract.py` and `rights_score.py` **overwrite** their
shared output CSVs wholesale — running them on only the 3 new docs would replace
the existing 40-doc rows. Snapshot before you run:

```sh
cd "$WORK"
cp -r output_v2 "output_v2.backup_$(date +%Y%m%d)"
```

Then run each coder on the 3 docs (pass all three in one invocation so they land
in one CSV together):

```sh
cd "$WORK/scripts"

# 2a. main 106-question dataset  (~12-18 min/doc)
python3 llm_extract.py --doc "$D1" --doc "$D2" --doc "$D3"

# 2b. salary schedules  (per-doc; writes one file per table, no clobber)
python3 salary_schedule.py --district "${D1%%|*}" --file "${D1##*|}"
python3 salary_schedule.py --district "${D2%%|*}" --file "${D2##*|}"
python3 salary_schedule.py --district "${D3%%|*}" --file "${D3##*|}"

# 2c. rights scoring  (~1 min/page; dominant cost)
python3 rights_score.py --doc "$D1" --doc "$D2" --doc "$D3"
```

Outputs land in `output_v2/` (main dataset, salary_schedule_wide/, rights_score_*).
Spot-check a few rows against the source PDFs before treating anything as final —
this pipeline is one noisy draw, not ground truth.

---

## Notes / gotchas

- **Don't run the coders in parallel** on overlapping docs — `llm_extract` and
  `rights_score` overwrite CSVs (race). One invocation covering all 3 is safe.
- **Per-doc caches** (`cache/llm_cache`, `cache/rights_score_cache`,
  `cache/salary_schedule_cache`) make re-runs fast and are safe to build in
  parallel; only the final CSV write must be a single run.
- **To permanently add these docs to the dataset**, add them to `readme.md`'s
  sample table and re-run the coders over the full sample (all cache hits, fast).
- **Keep the HPC session warm**: after `ssh hpc` once, the olmocr2 job reuses key
  auth. `just hpc-status --ocr-only` (from `$OCR`) shows running jobs;
  `just hpc-cleanup` clears orphans.
