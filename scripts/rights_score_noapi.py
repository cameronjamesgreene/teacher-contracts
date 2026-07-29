#!/usr/bin/env python3
"""Score worker rights and responsibilities — agent-run variant, no API key required.

Same goal and outputs as rights_score.py, but instead of this script calling the SOM
API itself, it delegates the actual clause-reading step to whatever coding agent
(Claude Code, Codex, etc.) is running it: for each text chunk it writes a task and
stops; the agent reads the chunk, extracts clauses per the same instructions, writes
the JSON answer, and re-runs the script to continue with the next chunk.

See rights_score.py's module docstring for the underlying method (Hohfeldian clause
classification, modal-strength weighting, correlative protected_party scoring) and
its documented caveat (clause-level counting can double-count an entitlement that is
restated in two different grammatical framings elsewhere in the same contract).

Outputs (identical shape to rights_score.py):
  output/rights_score_long.csv
  output/rights_score_summary.csv

Usage (run repeatedly until it reports "All documents complete"):
    python3 rights_score_noapi.py --doc "Davis School District|Davis_2019-2020.pdf"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import PDF_ROOT, TEXT_DIR, WORK, extract_text
from agent_task import AgentTaskPending, run_task
from rights_score import (
    LONG_FIELDS,
    RIGHTS_SYSTEM_PROMPT,
    SUMMARY_FIELDS,
    aggregate,
    build_long_rows,
    chunk_text,
    classify_and_score,
    exclude_appendices,
    load_targets,
    write_long_csv,
    write_summary_csv,
)

TASK_DIR = WORK / "cache" / "rights_score_tasks"
CACHE_DIR = WORK / "cache" / "rights_score_cache_noapi"


def process_document(document_id: str, file_name: str, district: str) -> tuple[list[dict], str]:
    pdf_path = PDF_ROOT / district / file_name
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        return [], "needs_dropbox_hydration"

    text_path = TEXT_DIR / f"{document_id}.txt"
    text = extract_text(pdf_path, text_path)
    pages = text.split("\f") if text else []
    if not pages:
        return [], "no_extractable_text"

    filtered_text = "\f".join(exclude_appendices(pages))
    chunks = chunk_text(filtered_text)
    if not chunks:
        return [], "no_extractable_text"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_clauses: list[dict] = []
    for i, chunk in enumerate(chunks, start=1):
        cache_path = CACHE_DIR / f"{document_id}__chunk{i:03d}.json"
        if cache_path.exists():
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            task_id = f"{document_id}__chunk{i:03d}"
            raw = run_task(
                task_id,
                RIGHTS_SYSTEM_PROMPT,
                f"Document: {file_name}\nChunk {i} of {len(chunks)}.\n\n"
                f"---TEXT---\n{chunk}\n---END---\n\nExtract every clause from this chunk.",
                TASK_DIR,
            )
            cache_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        for clause in raw.get("clauses", []):
            entry = classify_and_score(clause)
            entry["chunk_index"] = i
            all_clauses.append(entry)
    return all_clauses, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doc", action="append", metavar="DISTRICT|FILE.pdf",
        help="Process specific document(s), writing one combined output. May be repeated.",
    )
    parser.add_argument("--district", help="Process a single PDF: district folder name")
    parser.add_argument("--file", help="Process a single PDF: file name within --district")
    parser.add_argument(
        "--max-docs", type=int, default=None,
        help="Limit number of documents processed (only applies to the full-sample default run)",
    )
    args = parser.parse_args()

    targets = load_targets(args)
    print(f"Processing {len(targets)} document(s) ...")

    long_rows: list[dict] = []
    summary_rows: list[dict] = []
    statuses: dict[str, int] = {}

    for i, (document_id, file_name, district) in enumerate(targets, start=1):
        print(f"[{i:>2}/{len(targets)}] {file_name} ...")
        try:
            clauses, status = process_document(document_id, file_name, district)
        except AgentTaskPending as pending:
            print(f"\nStopped — agent action required.")
            print(f"Task:     {pending.task_id}")
            print(f"Read:     {pending.task_path}")
            print(f"Write to: {pending.response_path}")
            print("Then re-run this script to continue with the next task.")
            sys.exit(0)

        statuses[status] = statuses.get(status, 0) + 1
        if status != "ok":
            print(f"      {status}")
            continue
        totals = aggregate(clauses)
        summary_rows.append({
            "document_id": document_id, "file_name": file_name, "district_name": district,
            "total_clauses_extracted": len(clauses), **totals,
        })
        long_rows.extend(build_long_rows(document_id, file_name, district, clauses))
        print(f"      {len(clauses)} clauses extracted, {totals['total_clauses_scored']} scored")

    long_path = write_long_csv(long_rows)
    summary_path = write_summary_csv(summary_rows)
    print(f"\nAll documents complete.")
    print(f"{len(long_rows)} clause rows    -> {long_path}")
    print(f"{len(summary_rows)} document rows -> {summary_path}")
    print(f"Document status summary: {statuses}")


if __name__ == "__main__":
    main()
