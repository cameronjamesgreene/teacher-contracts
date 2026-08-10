#!/bin/bash
# Self-contained overnight driver: waits for the running Chicago salary job, then runs
# rights_score for all 3 docs to output_v4, then writes a consolidated verification.
# Launched with nohup so it survives the ssh session and the user's laptop.
REPO=~/contracts/contract_coding_CG
cd "$REPO/scripts" || exit 1
DONE="$REPO/logs/v4_ALLDONE.marker"
rm -f "$DONE"

echo "[driver] $(date) waiting for Chicago salary (PID 980582) to finish..."
while kill -0 980582 2>/dev/null; do sleep 30; done
echo "[driver] $(date) Chicago salary finished."

echo "[driver] $(date) starting rights_score for all 3 docs -> output_v4 ..."
CONTRACT_OUT_DIR=output_v4 RIGHTS_CONCURRENCY=12 ../.venv/bin/python -u rights_score.py \
  --doc "Chicago Public Schools|Chicago_CPS-CBA-2019-24.pdf" \
  --doc "Clark County School District|Clark_County_2021-2023_CBA.pdf" \
  --doc "Detroit Public Schools Community District|22.pdf" \
  > "$REPO/logs/rights_v4.log" 2>&1
RC=$?
echo "[driver] $(date) rights_score exit code $RC"

echo "[driver] $(date) running consolidated verification ..."
CONTRACT_OUT_DIR=output_v4 ../.venv/bin/python "$REPO/verify_v4_full.py" \
  > "$REPO/logs/v4_verification_summary.txt" 2>&1

echo "[driver] $(date) ALL DONE (rights_score rc=$RC)" | tee "$DONE"
