#!/bin/bash
# output_v5 validation build: re-run all 3 programs on the 3 v4 docs with the fixed
# code. Invalidates the caches whose upstream logic/prompts changed, keeps the
# expensive llm Stage-1 caches. nohup-detached; survives the session.
REPO=~/contracts/contract_coding_CG
cd "$REPO/scripts" || exit 1
DONE="$REPO/logs/v5_ALLDONE.marker"; rm -f "$DONE"
IDS="chicago_public_schools clark_county_school_district detroit_public"

echo "[v5] $(date) invalidating caches (keep llm Stage-1 s1c; drop llm finals, rights, salary)..."
for id in $IDS; do
  ls "$REPO"/cache/llm_cache/ 2>/dev/null | grep "$id" | grep -v "__s1" \
    | sed "s#^#$REPO/cache/llm_cache/#" | xargs -r rm -f
  ls "$REPO"/cache/rights_score_cache/ 2>/dev/null | grep "$id" \
    | sed "s#^#$REPO/cache/rights_score_cache/#" | xargs -r rm -f
  ls "$REPO"/cache/salary_schedule_cache/ 2>/dev/null | grep "$id" \
    | sed "s#^#$REPO/cache/salary_schedule_cache/#" | xargs -r rm -f
done
echo "[v5] caches cleared."

echo "[v5] $(date) STEP 1/3 llm_extract -> output_v5 ..."
CONTRACT_OUT_DIR=output_v5 ../.venv/bin/python -u llm_extract.py \
  --doc "Chicago Public Schools|Chicago_CPS-CBA-2019-24.pdf" \
  --doc "Clark County School District|Clark_County_2021-2023_CBA.pdf" \
  --doc "Detroit Public Schools Community District|22.pdf" \
  > "$REPO/logs/llm_v5.log" 2>&1
echo "[v5] $(date) llm_extract done (rc=$?)"

echo "[v5] $(date) STEP 2/3 rights_score + salary_schedule concurrently..."
CONTRACT_OUT_DIR=output_v5 RIGHTS_CONCURRENCY=4 ../.venv/bin/python -u rights_score.py \
  --doc "Chicago Public Schools|Chicago_CPS-CBA-2019-24.pdf" \
  --doc "Clark County School District|Clark_County_2021-2023_CBA.pdf" \
  --doc "Detroit Public Schools Community District|22.pdf" \
  > "$REPO/logs/rights_v5.log" 2>&1 &
RPID=$!
CONTRACT_OUT_DIR=output_v5 ../.venv/bin/python -u salary_schedule.py \
  > "$REPO/logs/salary_v5.log" 2>&1 &
SPID=$!
wait $RPID; echo "[v5] $(date) rights_score done (rc=$?)"
wait $SPID; echo "[v5] $(date) salary_schedule done (rc=$?)"

echo "[v5] $(date) STEP 3/3 ALL DONE" | tee "$DONE"
