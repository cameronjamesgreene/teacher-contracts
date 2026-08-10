#!/bin/bash
# Final overnight driver: runs rights_score NOW (parallel with the slow, ongoing
# Chicago salary job so Program 3 isn't blocked), then waits up to ~5h for salary,
# then writes the consolidated verification. nohup-detached; survives session/laptop.
REPO=~/contracts/contract_coding_CG
cd "$REPO/scripts" || exit 1
DONE="$REPO/logs/v4_ALLDONE.marker"; rm -f "$DONE"

echo "[final] $(date) starting rights_score (conc 4, parallel with ongoing salary)..."
CONTRACT_OUT_DIR=output_v4 RIGHTS_CONCURRENCY=4 ../.venv/bin/python -u rights_score.py \
  --doc "Chicago Public Schools|Chicago_CPS-CBA-2019-24.pdf" \
  --doc "Clark County School District|Clark_County_2021-2023_CBA.pdf" \
  --doc "Detroit Public Schools Community District|22.pdf" \
  > "$REPO/logs/rights_v4.log" 2>&1 &
RPID=$!
echo "[final] rights_score PID $RPID"
wait $RPID; RRC=$?
echo "[final] $(date) rights_score finished (rc=$RRC)"

echo "[final] $(date) waiting for Chicago salary (PID 980582), up to ~5h..."
for i in $(seq 1 300); do
  kill -0 980582 2>/dev/null || { echo "[final] salary finished"; break; }
  sleep 60
done
kill -0 980582 2>/dev/null && echo "[final] salary STILL running after 5h; verifying partial" || true

echo "[final] $(date) running consolidated verification..."
CONTRACT_OUT_DIR=output_v4 ../.venv/bin/python "$REPO/verify_v4_full.py" > "$REPO/logs/v4_verification_summary.txt" 2>&1
echo "[final] $(date) ALL DONE (rights rc=$RRC)" | tee "$DONE"
