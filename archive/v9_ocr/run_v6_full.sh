#!/usr/bin/env bash
# v6 overnight chain: OCR the scanned doc (Pittsburgh) via olmocr2, then run all 3 docs
# through the pipeline in parallel, then the driver merges into output_v6/. Fully
# detached (nohup) so it survives the operator logging off / the laptop sleeping — it
# runs on the HPC login node + GPU workers, independent of any local machine.
set -uo pipefail
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"                 # uv, needed by hybrid_ocr's olmocr2 call
PY="$SCRIPTS/../.venv/bin/python"
LOGS="$SCRIPTS/../logs"; mkdir -p "$LOGS"
CHAIN="$LOGS/v6_chain.log"
PITTS_OCR="$SCRIPTS/../cache/ocr_text/pittsburgh_public_schools__pittsburgh_10_15__75d52cf8.txt"

echo "=== v6 chain START $(date) ===" | tee -a "$CHAIN"

# ── Step 1/2 — OCR Pittsburgh (fully scanned). Born-digital Boston/Duval need no OCR. ──
# Wrapped in `timeout` so a stuck GPU-worker launch can never block the whole pipeline;
# on timeout/failure Pittsburgh simply codes as ocr_needed and the run continues.
echo "[chain] STEP 1/2 OCR Pittsburgh (olmocr2) $(date)" | tee -a "$CHAIN"
timeout 4200 "$PY" "$SCRIPTS/hybrid_ocr.py" build \
    --doc "Pittsburgh Public Schools|Pittsburgh_10-15.pdf" \
    > "$LOGS/v6_ocr_pittsburgh.log" 2>&1
echo "[chain] OCR exit rc=$? $(date)" | tee -a "$CHAIN"
if [ -s "$PITTS_OCR" ]; then
    echo "[chain] OCR text OK: $(wc -c < "$PITTS_OCR") chars" | tee -a "$CHAIN"
else
    echo "[chain] WARNING: no OCR text produced — Pittsburgh will code as ocr_needed" | tee -a "$CHAIN"
fi

# ── Step 2/2 — 3-doc parallel pipeline (Boston/Duval resume from cache; Pittsburgh fresh) ──
echo "[chain] STEP 2/2 parallel pipeline (3 docs) $(date)" | tee -a "$CHAIN"
PY="$PY" RIGHTS_CONCURRENCY=4 bash "$SCRIPTS/run_parallel_v6.sh" \
    "Boston Public Schools|Boston_2021-24-Collective-Bargaining-Agreement.pdf" \
    "Duval County Public Schools|Collective_Bargaining_Agreement_2011-2014T_.pdf" \
    "Pittsburgh Public Schools|Pittsburgh_10-15.pdf" \
    >> "$CHAIN" 2>&1

echo "=== v6 chain DONE $(date) ===" | tee -a "$CHAIN"
