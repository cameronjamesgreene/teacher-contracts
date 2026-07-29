# HPC OCR batch — run this on your machine (needs your Duo login)

This OCRs the scanned / image-only PDFs in the 40-doc sample whose `pdftotext`
extraction is empty, so the three pipelines (`llm_extract.py`, `rights_score.py`,
`salary_schedule.py`) stop coding them as a wall of `not_discussed`.

**Why only these docs:** all three pipelines read one shared text file per
document (`cache/extracted_text/<document_id>.txt`). `utils.extract_text()` now
prefers an OCR override at `cache/ocr_text/<document_id>.txt` when present, so
OCR done once here fixes all three programs with no per-program change. Only the
documents below actually need it (see `ocr_manifest.json` for the full list).

## The OCR work-list (auto-derived by `scripts/prep_ocr_batch.py`)

| Ready? | District | File | Pages | Notes |
|--------|----------|------|-------|-------|
| ✅ now  | Santa Ana USD        | `Santa_Ana_2016-2019_Contract.pdf`          | 152 | hydrated; already staged |
| ⬜ hydrate | West Ada SD       | `Wes_Ada_Agreement_2022-2023.pdf`           | 27  | smallest — fastest test |
| ⬜ hydrate | Birmingham City   | `Birmingham_Policy_Manual_updated_6_2012.pdf` | 287 | largest |

`document-ids.txt` currently holds **only the ready (Santa Ana) UUID** — that is
your tiny first sample. West Ada and Birmingham are 0-byte Dropbox
"online-only" placeholders on this machine and can't be OCR'd until hydrated
(see the last section).

These are **public** school-district contracts, so use the repo's ordinary
disk-backed workflow — not the sensitive/tunneled one.

## 0. (Recommended) Load the Yale SOM HPC skills so the agent manages Slurm for you

```sh
/plugin marketplace add yale-som-hpc/claude-code-marketplace
/plugin install hpc@yale-som-hpc
```

Useful ones here: `managing-jobs`, `using-gpus`, `connecting-securely`,
`troubleshooting`. (There is no OCR-specific skill; these just run/monitor the job.)

## 1. Clone the OCR repo (on Yale VPN — you're connected)

```sh
git clone https://github.com/yale-som-hpc/ocr-examples.git
cd ocr-examples
```

## 2. Check prerequisites (Duo prompts here)

```sh
uv --version
just --version
ssh hpc.som.yale.edu true      # triggers Duo
just check
```

## 3. Sync the repo to the HPC login node

```sh
export HPC_HOST=hpc.som.yale.edu
just sync-hpc
```

## 4. Run the tiny sample (Santa Ana) — docling on RTX 8000

Start small: one engine, one worker (per the repo's own guidance). Point
`--documents-root` and `--from-file` at this staging folder.

```sh
STAGE="/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/ocr_documents"

uv run --script scripts/documents_process.py \
  --from-file "$STAGE/document-ids.txt" \
  --documents-root "$STAGE/documents" \
  --stages ocr \
  --engines docling \
  --use-hpc --workers 1 --in-flight 1 \
  --hpc-gres gpu:rtx8000:1 --hpc-exclude c001 --hpc-mem 32G \
  --force
```

If a flag name differs on your checkout, the repo is the source of truth:
`uv run --script scripts/documents_process.py --help` and `just --list`. Santa
Ana is 152 pages — give it time, no need to babysit.

Monitor / clean up:
```sh
just hpc-status --ocr-only
just hpc-cleanup            # only if a run was interrupted and left orphan jobs
```

## 5. When it finishes

OCR text lands at:
```
cache/ocr_documents/documents/1eb86aeb-5ff1-5361-b58e-577d487b6e49/ocr/docling.txt
```
Open it, confirm it reads like real contract text (not an error log), then tell
Claude it's done. Claude will (Phase 4): copy it to
`cache/ocr_text/santa_ana_unified_school_district__santa_ana_2016_2019_contract__79de7c42.txt`
(the override `extract_text()` now checks), clear that doc's stale
`llm_cache` / `rights_score_cache` / `salary_schedule_cache` entries, re-run the
three pipelines on just that document, and re-audit it.

## If docling looks poor on a document

It has rotated/skewed scanned pages in places. Try a vision-LLM engine (same
command shape, swap `--engines`): `olmocr2` or `deepseek_ocr` (both RTX 8000),
per the repo's `docs/ocr-engines.md`. `unlimited_ocr` needs an A100.

## To add West Ada + Birmingham to the batch

1. In Finder, right-click each of these PDFs → **"Make Available Offline"**
   (Dropbox), wait for the solid green check:
   - `nctq_contracts/West Ada School District/Wes_Ada_Agreement_2022-2023.pdf`
   - `nctq_contracts/Birmingham City Schools/Birmingham_Policy_Manual_updated_6_2012.pdf`
2. Re-run the prep script — it copies the now-hydrated PDFs into `documents/` and
   adds their UUIDs to `document-ids.txt`:
   ```sh
   cd "/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/scripts"
   python3 prep_ocr_batch.py
   ```
3. Re-run step 4 above (now `document-ids.txt` covers all three). Tip: West Ada
   is only 27 pages — the fastest possible smoke test if you want one before
   committing the 287-page Birmingham manual.
