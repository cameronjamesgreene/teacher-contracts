#!/usr/bin/env bash
# Full-pipeline (llm_extract + rights_score + salary_schedule) on the 15 docs. Each doc
# gets its OWN CONTRACT_OUT_DIR (output_v8_full/<slug>) so the shared output CSVs never
# race; caches are keyed by document_id so the shared cache is safe. Staggered per doc.
set -u
cd /home/cjg79/contracts/contract_coding_CG
source .venv/bin/activate 2>/dev/null
export PYTHONUNBUFFERED=1
STAGGER=${STAGGER:-20}
mkdir -p logs output_v8_full
i=0
while IFS=$'\t' read -r district file; do
  [ -z "$district" ] && continue
  i=$((i+1))
  slug=$(echo "$district" | tr 'A-Z ' 'a-z_' | tr -cd 'a-z0-9_')
  out="output_v8_full/$slug"; mkdir -p "$out"
  echo "$(date +%H:%M:%S) launch $i: $district"
  CONTRACT_OUT_DIR="$out" setsid nohup python scripts/llm_extract.py    --doc "${district}|${file}"          > "logs/full_${slug}_llm.log"    2>&1 </dev/null &
  CONTRACT_OUT_DIR="$out" setsid nohup python scripts/rights_score.py   --district "$district" --file "$file" > "logs/full_${slug}_rights.log" 2>&1 </dev/null &
  CONTRACT_OUT_DIR="$out" setsid nohup python scripts/salary_schedule.py --district "$district" --file "$file" > "logs/full_${slug}_salary.log" 2>&1 </dev/null &
  sleep "$STAGGER"
done < v8p_runlist.tsv
echo "$(date +%H:%M:%S) all $i docs launched (x3 programs = $((i*3)) procs)"
