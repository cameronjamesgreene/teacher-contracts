#!/usr/bin/env bash
# Staggered launch of the 15-doc vision-primary salary run. Concurrency ramps 1->15 as
# each doc starts STAGGER seconds after the last, so the API load builds gradually.
set -u
cd /home/cjg79/contracts/contract_coding_CG
source .venv/bin/activate 2>/dev/null
export CONTRACT_OUT_DIR=output_v8_15docs
STAGGER=${STAGGER:-25}
mkdir -p logs "$CONTRACT_OUT_DIR"
i=0
while IFS=$'\t' read -r district file; do
  [ -z "$district" ] && continue
  i=$((i+1))
  slug=$(echo "$district" | tr 'A-Z ' 'a-z_' | tr -cd 'a-z0-9_')
  log="logs/v8p_${slug}.log"
  echo "$(date +%H:%M:%S) launch $i: $district / $file -> $log"
  setsid nohup python scripts/salary_schedule.py --district "$district" --file "$file" \
      > "$log" 2>&1 < /dev/null &
  sleep "$STAGGER"
done < v8p_runlist.tsv
echo "$(date +%H:%M:%S) all $i launched"
