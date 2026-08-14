#!/usr/bin/env bash
# Run salary_schedule.py or rights_score.py over a document list, one at a time.
#
# Sequential on purpose. Both programs already fan out internally — salary escalates
# blocks to vision concurrently, rights sends its chunks with RIGHTS_CONCURRENCY workers
# — so running documents in parallel on top of that multiplies in-flight requests past
# the endpoint's measured ~24-32 ceiling. The corpus extraction hit exactly this: a
# dropped connection at 24 in-flight silently voided 41% of one document's windows.
#
# Resumable: a document whose per-document output already exists is skipped, so an
# interrupted run continues by re-issuing the same command.
#
# Usage:
#   scripts/run_programs.sh salary <list.tsv> <out_dir>
#   scripts/run_programs.sh rights <list.tsv> <out_dir>
set -uo pipefail

PROGRAM="${1:?salary|rights}"
LIST="${2:?document list tsv: district<TAB>file}"
OUT="${3:?CONTRACT_OUT_DIR value}"
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
mkdir -p logs

case "$PROGRAM" in
  salary) SCRIPT=scripts/salary_schedule.py ;;
  rights) SCRIPT=scripts/rights_score.py ;;
  *) echo "unknown program: $PROGRAM" >&2; exit 2 ;;
esac

total=$(grep -c . "$LIST")
index=0
failed=0
started=$(date +%s)
echo "=== $PROGRAM over $total document(s) -> $OUT ==="

while IFS=$'\t' read -r district file; do
  [ -z "${district:-}" ] && continue
  index=$((index + 1))
  echo "--- [$index/$total] $district | $file"
  # Per-document output dir. rights_score writes ONE rights_score_long.csv into
  # CONTRACT_OUT_DIR and overwrites it every run, so a shared dir keeps only the last
  # document - 42 runs produced one document's clauses. The v9 parallel driver already
  # solved this by giving each document its own dir and merging; this does the same.
  slug=$(echo "$district" | tr 'A-Z ' 'a-z_' | tr -cd 'a-z0-9_')
  if ! CONTRACT_OUT_DIR="$OUT/per_doc/$slug" "$PY" "$SCRIPT" --district "$district" --file "$file" \
        >> "logs/${PROGRAM}_v12.log" 2>&1; then
    echo "    FAILED (see logs/${PROGRAM}_v12.log)"
    failed=$((failed + 1))
  fi
done < "$LIST"

echo "=== $PROGRAM COMPLETE: $((total - failed))/$total ok, $failed failed,"\
     "$(( ($(date +%s) - started) / 60 )) min ==="
