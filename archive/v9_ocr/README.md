# The v9 OCR stack, retired 2026-08-06

Superseded by `scripts/ocr_scanned.py`, `ocr_quality_gate.py`, `ocr_reconcile.py` and
`ocr_adjudicate.py`, driven by `scripts/run_ocr.py`. Kept because they are the only
record of how v1–v10 OCR text was produced, and every audit workbook through v11 grades
text these scripts made.

Nothing in the live pipeline imports any of them; the cluster only ever imported itself.

## Why they were retired

The replacement is not a refactor, it is a different answer to the question "which
engine do you believe?" Measured on four pages of one scanned contract whose contents
were verified against the PDF by hand:

| engine | verified figures | corrupted | hallucinations |
| --- | --- | --- | --- |
| olmOCR-2 | 0 of 3 | 3 of 3 | 2 |
| Apple Vision | **3 of 3** | 0 | 0 |
| GLM-OCR | 0 of 3 | 0 of 3 | 0 |
| DeepSeek-OCR-2 | *empty output* | — | — |

`195 days` became `135 days`; `eight (8) hours` became `eighty (8) hours`. A
vision-language model *reconstructs* a page rather than recognising glyphs, so on a hard
layout it smooths, transposes, loops or invents — and the result is fluent, which
defeats every spell-check-shaped defence.

This stack ran olmOCR-2 as the single engine and had no gate for any of that. The
replacement runs two engines and arbitrates per page: figures decide ties, because this
codebook asks for figures. Voting was tried and rejected — pairwise figure agreement is
0.12–0.34, so three engines disagree three ways, and the correct values were found by
exactly one engine. A vote discards the only correct reading.

Degenerate pages went 28/299 → 0 under the replacement's gate.

## What is here

| file | was |
| --- | --- |
| `hybrid_ocr.py` | olmOCR-2 on SLURM, the v9 OCR entry point |
| `splice_ocr.py` | merged OCR pages back into pdftotext output |
| `chunk_ocr.py` | split/concat for documents too large for one SLURM job |
| `ocr_som_vision.py` | OCR through the SOM vision endpoint |
| `apple_vision_ocr.py` | standalone Apple Vision runner (now inside `ocr_scanned.py`) |
| `prep_ocr_batch.py`, `stage_for_ocr.py` | staging PDFs for the HPC workflow |
| `build_ocr_accuracy_report.py`, `build_engine_comparison.py` | CER/WER engine comparison, superseded by `ocr_quality_gate.py` (which needs no reference text) and the per-page provenance in `output/extraction/ocr_provenance/` |
| `run_v6_full.sh` | the v6 full-pipeline driver; called `hybrid_ocr.py build` |
| `docs/` | the runbooks for the above |

## If you need to run one

They are unmodified and still import from `scripts/utils.py`, so copy the file back to
`scripts/` rather than running it from here — `sys.path` assumes it sits next to
`utils.py`.
