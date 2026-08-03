#!/usr/bin/env bash
# Run several documents THROUGH THE FULL PIPELINE IN PARALLEL, one output dir per doc,
# then merge into a single combined output dir. Each document runs llm_extract,
# rights_score and salary_schedule concurrently (single-doc mode decouples them — rights
# and salary read the raw PDF directly and do not need llm_extract's CSV), under its own
# CONTRACT_OUT_DIR so the three writers never clobber each other's CSVs.
#
# The 32k MAX_TOKENS cap is a PER-CALL output limit, unaffected by concurrency, so no
# token change is needed here. We do cap rights_score's intra-doc fan-out
# (RIGHTS_CONCURRENCY) so aggregate in-flight calls stay well under the tested ceiling:
#   N docs x (llm 1 + rights RIGHTS_CONCURRENCY + salary 1). With 3 docs x (1+4+1) = 18.
#
# Usage:
#   ./run_parallel_v6.sh "District A|file_a.pdf" "District B|file_b.pdf" ...
# If no docs are given, the DOCS array below is used. Run from the scripts/ directory.

set -uo pipefail
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
LOGS="$SCRIPTS/../logs"
mkdir -p "$LOGS"

OUT_VERSION="${OUT_VERSION:-output_v6}"
export RIGHTS_CONCURRENCY="${RIGHTS_CONCURRENCY:-4}"   # per-doc rights fan-out cap
LLM_MAX_RESTARTS="${LLM_MAX_RESTARTS:-10}"
RESTART_SLEEP="${RESTART_SLEEP:-30}"
# Python interpreter. On the HPC the deps live in the project venv, not system python3;
# pass PY=/path/to/.venv/bin/python (e.g. "$SCRIPTS/../.venv/bin/python").
PY="${PY:-python3}"
[ -x "$SCRIPTS/../.venv/bin/python" ] && [ "$PY" = "python3" ] && PY="$SCRIPTS/../.venv/bin/python"

# Default document set (edit to taste): "District folder name|file name.pdf"
DOCS_DEFAULT=(
    # "Denver Public Schools|denver_2022_2025.pdf"
    # "Baltimore City Public School System|baltimore_city_2021_2023.pdf"
    # "Broward County Public Schools|broward_2011_2014.pdf"
)
if [ "$#" -gt 0 ]; then
    DOCS=("$@")
else
    DOCS=("${DOCS_DEFAULT[@]}")
fi
if [ "${#DOCS[@]}" -eq 0 ]; then
    echo "No documents given and DOCS_DEFAULT is empty. Pass docs as \"District|file.pdf\" args." >&2
    exit 2
fi

slugify() {  # district + file stem -> dir-safe slug
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' \
        | sed -E 's/_+/_/g; s/^_//; s/_$//' | cut -c1-80
}

# Run one program with a bounded auto-restart on non-zero exit (transient SOM errors).
run_with_retry() {  # <max_restarts> <log> <cmd...>
    local max="$1" log="$2"; shift 2
    local n=0
    while true; do
        n=$((n + 1))
        "$@" >>"$log" 2>&1 && return 0
        local rc=$?
        if [ "$n" -ge "$max" ]; then
            echo "  [$(date)] GAVE UP after $n attempts (rc=$rc): $*" | tee -a "$log"
            return "$rc"
        fi
        echo "  [$(date)] rc=$rc — restart $n/$max in ${RESTART_SLEEP}s: $*" | tee -a "$log"
        sleep "$RESTART_SLEEP"
    done
}

# Process one document: its three programs concurrently, in its own CONTRACT_OUT_DIR.
process_doc() {
    local doc="$1"
    local district="${doc%%|*}"
    local file="${doc#*|}"
    local slug; slug="$(slugify "${district}_${file%.pdf}")"
    local outdir="$OUT_VERSION/$slug"
    local log="$LOGS/v6_${slug}.log"
    : > "$log"
    echo "[$(date)] START $district | $file  (CONTRACT_OUT_DIR=$outdir)" | tee -a "$log"

    CONTRACT_OUT_DIR="$outdir" run_with_retry "$LLM_MAX_RESTARTS" "$log" \
        "$PY" "$SCRIPTS/llm_extract.py" --doc "$district|$file" &
    local p_llm=$!
    CONTRACT_OUT_DIR="$outdir" run_with_retry 3 "$log" \
        "$PY" "$SCRIPTS/rights_score.py" --district "$district" --file "$file" &
    local p_rights=$!
    CONTRACT_OUT_DIR="$outdir" run_with_retry 3 "$log" \
        "$PY" "$SCRIPTS/salary_schedule.py" --district "$district" --file "$file" &
    local p_salary=$!

    local ok=0
    wait "$p_llm"    || ok=1
    wait "$p_rights" || ok=1
    wait "$p_salary" || ok=1
    echo "[$(date)] DONE  $district | $file  (status=$ok)" | tee -a "$log"
    return "$ok"
}

doc_slug() {  # "District|file.pdf" -> the same slug process_doc uses
    local doc="$1" district="${1%%|*}" file="${1#*|}"
    slugify "${district}_${file%.pdf}"
}

echo "=== Parallel v6 run started $(date) — ${#DOCS[@]} doc(s), RIGHTS_CONCURRENCY=$RIGHTS_CONCURRENCY ===" \
    | tee -a "$LOGS/pipeline.log"

SLUGS=()
PIDS=()
for doc in "${DOCS[@]}"; do
    process_doc "$doc" &
    PIDS+=($!)
    SLUGS+=("$(doc_slug "$doc")")
done

overall=0
for pid in "${PIDS[@]}"; do
    wait "$pid" || overall=1
done

echo "=== All docs finished ($(date), status=$overall) — merging into $OUT_VERSION ===" \
    | tee -a "$LOGS/pipeline.log"
"$PY" "$SCRIPTS/merge_parallel_outputs.py" "$SCRIPTS/../$OUT_VERSION" "${SLUGS[@]}" \
    2>&1 | tee -a "$LOGS/pipeline.log"

echo "=== Parallel v6 run complete $(date) ===" | tee -a "$LOGS/pipeline.log"
exit "$overall"
