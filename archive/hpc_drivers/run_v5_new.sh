#!/bin/bash
# output_v5 validation build on 3 NEVER-SEEN born-digital docs (Denver 2022-25,
# Baltimore 2021-23, Broward 2011-14) with the fixed code. No OCR, no cache
# invalidation (these docs have no caches). nohup-detached.
REPO=~/contracts/contract_coding_CG
cd "$REPO/scripts" || exit 1
DONE="$REPO/logs/v5_ALLDONE.marker"; rm -f "$DONE"

D1='--doc "Denver Public Schools|Denver_2022-2025-CBA-Final.pdf"'
echo "[v5] $(date) STEP 1/3 llm_extract -> output_v5 (Broward 228pp dominates)..."
CONTRACT_OUT_DIR=output_v5 ../.venv/bin/python -u llm_extract.py \
  --doc "Denver Public Schools|Denver_2022-2025-CBA-Final.pdf" \
  --doc "Baltimore City Public School System|Baltimore_City_Public_Schools_2021-2023.pdf" \
  --doc "Broward County Public Schools|Broward_Teachers_U_Contract_2011_2014.pdf" \
  > "$REPO/logs/llm_v5.log" 2>&1
echo "[v5] $(date) llm_extract done (rc=$?)"

echo "[v5] $(date) STEP 2/3 rights_score + salary_schedule concurrently..."
CONTRACT_OUT_DIR=output_v5 RIGHTS_CONCURRENCY=4 ../.venv/bin/python -u rights_score.py \
  --doc "Denver Public Schools|Denver_2022-2025-CBA-Final.pdf" \
  --doc "Baltimore City Public School System|Baltimore_City_Public_Schools_2021-2023.pdf" \
  --doc "Broward County Public Schools|Broward_Teachers_U_Contract_2011_2014.pdf" \
  > "$REPO/logs/rights_v5.log" 2>&1 &
RPID=$!
CONTRACT_OUT_DIR=output_v5 ../.venv/bin/python -u salary_schedule.py \
  > "$REPO/logs/salary_v5.log" 2>&1 &
SPID=$!
wait $RPID; echo "[v5] $(date) rights_score done (rc=$?)"
wait $SPID; echo "[v5] $(date) salary_schedule done (rc=$?)"

echo "[v5] $(date) STEP 3/3 ALL DONE" | tee "$DONE"
