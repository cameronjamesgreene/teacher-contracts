#!/usr/bin/env bash
# Full pipeline watchdog: llm_extract (with auto-restart on failure) → salary_schedule → rights_score
# Logs go to ../logs/  Run from the scripts/ directory.

set -euo pipefail
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
LOGS="$SCRIPTS/../logs"
mkdir -p "$LOGS"

MAX_RESTARTS=20
RESTART_SLEEP=30   # seconds between restarts

echo "=== Pipeline started at $(date) ===" | tee -a "$LOGS/pipeline.log"

# ── Stage 1: llm_extract with auto-restart ─────────────────────────────────
echo "[Stage 1] llm_extract.py" | tee -a "$LOGS/pipeline.log"
attempts=0
while true; do
    attempts=$((attempts + 1))
    echo "  attempt $attempts at $(date)" | tee -a "$LOGS/pipeline.log"
    set +e
    python3 "$SCRIPTS/llm_extract.py" 2>&1 | tee -a "$LOGS/llm_extract_full.log"
    exit_code=${PIPESTATUS[0]}
    set -e
    if [ "$exit_code" -eq 0 ]; then
        echo "  llm_extract finished OK (attempt $attempts)" | tee -a "$LOGS/pipeline.log"
        break
    fi
    echo "  llm_extract exited $exit_code — restarting in ${RESTART_SLEEP}s (attempt $attempts/$MAX_RESTARTS)" | tee -a "$LOGS/pipeline.log"
    if [ "$attempts" -ge "$MAX_RESTARTS" ]; then
        echo "  MAX_RESTARTS reached — giving up on llm_extract" | tee -a "$LOGS/pipeline.log"
        exit 1
    fi
    sleep $RESTART_SLEEP
done

# ── Stage 2: salary_schedule ───────────────────────────────────────────────
echo "[Stage 2] salary_schedule.py at $(date)" | tee -a "$LOGS/pipeline.log"
python3 "$SCRIPTS/salary_schedule.py" 2>&1 | tee -a "$LOGS/salary_schedule_full.log"
echo "  salary_schedule finished OK" | tee -a "$LOGS/pipeline.log"

# ── Stage 3: rights_score ──────────────────────────────────────────────────
echo "[Stage 3] rights_score.py at $(date)" | tee -a "$LOGS/pipeline.log"
python3 "$SCRIPTS/rights_score.py" 2>&1 | tee -a "$LOGS/rights_score_full.log"
echo "  rights_score finished OK" | tee -a "$LOGS/pipeline.log"

echo "=== Pipeline complete at $(date) ===" | tee -a "$LOGS/pipeline.log"
