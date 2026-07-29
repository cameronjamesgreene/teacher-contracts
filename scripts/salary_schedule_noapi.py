#!/usr/bin/env python3
"""Extract teacher salary-schedule tables — agent-run variant, no OpenAI API key
required.

Same goal and outputs as salary_schedule.py, but instead of this script calling
the OpenAI API itself, it delegates the actual table-reading step to whatever
coding agent (Claude Code, Codex, etc.) is running it:

  - pages with extractable table text -> a text task: the agent reads the page
    text already included in the task file and writes the JSON answer.
  - pages with little/no table text   -> a vision task: this script renders the
    page(s) to PNG images and tells the agent to read them with its own
    file-reading tool, then write the JSON answer.

For each detected schedule the script writes a task and stops; the agent
answers it and re-runs the script to continue with the next one.

Outputs (identical shape to salary_schedule.py):
  output/salary_schedule_wide/<district>/<school year>/*.csv

Usage (run repeatedly until it reports "All documents complete"):
    python3 salary_schedule_noapi.py
    python3 salary_schedule_noapi.py --max-docs 3
    python3 salary_schedule_noapi.py --district "Davis School District" --file "Davis_2019-2020.pdf"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OUT_DIR, PDF_ROOT, TEXT_DIR, WORK, extract_text
from agent_task import AgentTaskPending, run_task
from salary_schedule import (
    SCHEDULE_SYSTEM_PROMPT,
    WIDE_DIR,
    _page_framing,
    document_id_for,
    dollar_density,
    find_heading_pages,
    group_schedule_blocks,
    load_yes_rows,
    parse_page_hints,
    render_pages_to_images,
    write_wide_grid,
)

TASK_DIR = WORK / "cache" / "salary_schedule_tasks"
IMAGE_DIR = TASK_DIR / "images"
CACHE_DIR = WORK / "cache" / "salary_schedule_cache_noapi"


def process_document(
    document_id: str, file_name: str, district: str, page_hint: str,
) -> tuple[list[dict], str]:
    pdf_path = PDF_ROOT / district / file_name
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        return [], "needs_dropbox_hydration"

    text_path = TEXT_DIR / f"{document_id}.txt"
    text = extract_text(pdf_path, text_path)
    pages = text.split("\f") if text else []
    if not pages:
        return [], "no_extractable_text"

    heading_pages = find_heading_pages(pages)
    if not heading_pages:
        heading_pages = [p for p in parse_page_hints(page_hint) if 1 <= p <= len(pages)]
    if not heading_pages:
        return [], "no_schedule_heading_found"

    blocks = group_schedule_blocks(pages, heading_pages)
    schedules: list[dict] = []
    CACHE_DIR.mkdir(exist_ok=True)

    for start, end in blocks:
        cache_path = CACHE_DIR / f"{document_id}__{start}-{end}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            block_text = "\f".join(pages[start - 1:end])
            task_id = f"{document_id}__{start}-{end}"
            lookahead_page = end + 1 if end + 1 <= len(pages) else None
            if dollar_density(block_text) >= 3:
                raw = run_task(
                    task_id,
                    SCHEDULE_SYSTEM_PROMPT,
                    f"Document: {file_name}\n{_page_framing(start, end, None)}\n\n"
                    f"---PAGE TEXT---\n{block_text}\n---END---",
                    TASK_DIR,
                )
                method = "text"
            else:
                end_render = lookahead_page or end
                image_dir = IMAGE_DIR / task_id
                image_dir.mkdir(parents=True, exist_ok=True)
                images = render_pages_to_images(pdf_path, start, end_render, image_dir)
                raw = run_task(
                    task_id,
                    SCHEDULE_SYSTEM_PROMPT,
                    f"Document: {file_name}\n{_page_framing(start, end, lookahead_page)}\n"
                    "Extract the salary schedule table(s) from the page image(s) listed below.",
                    TASK_DIR,
                    image_paths=images,
                )
                method = "vision"
            cached = {
                "tables": raw.get("tables", []),
                "extraction_method": method,
                "page_start": start,
                "page_end": end,
            }
            cache_path.write_text(json.dumps(cached, indent=2, ensure_ascii=False), encoding="utf-8")

        # Backward compatible with the older single-schedule cache shape.
        tables = cached["tables"] if "tables" in cached else [cached]
        for table in tables:
            if not table.get("has_table", True):
                continue
            entry = dict(table)
            entry.setdefault("extraction_method", cached.get("extraction_method", ""))
            entry.setdefault("page_start", cached.get("page_start", start))
            entry.setdefault("page_end", cached.get("page_end", end))
            schedules.append(entry)

    return schedules, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--district", help="Process a single PDF: district folder name")
    parser.add_argument("--file", help="Process a single PDF: file name within --district")
    parser.add_argument(
        "--doc", action="append", metavar="DISTRICT|FILE.pdf",
        help="Process specific document(s) together, writing one combined output. May be "
             "repeated. Example: --doc \"Davis School District|Davis_2019-2020.pdf\"",
    )
    parser.add_argument("--max-docs", type=int, default=None, help="Limit number of documents processed")
    args = parser.parse_args()

    if args.doc:
        targets = [
            (document_id_for(district, file_name), file_name, district, "")
            for district, file_name in (d.split("|", 1) for d in args.doc)
        ]
    elif args.district or args.file:
        if not (args.district and args.file):
            sys.exit("Error: --district and --file must be given together.")
        document_id = document_id_for(args.district, args.file)
        targets = [(document_id, args.file, args.district, "")]
    else:
        targets = load_yes_rows(args.max_docs)

    print(f"Processing {len(targets)} document(s) ...")

    statuses: dict[str, int] = {}
    schedule_count = 0

    for i, (document_id, file_name, district, page_hint) in enumerate(targets, start=1):
        print(f"[{i:>2}/{len(targets)}] {file_name} ...")
        try:
            schedules, status = process_document(document_id, file_name, district, page_hint)
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
        print(f"      {len(schedules)} schedule(s) found")
        for schedule in schedules:
            wide_path = write_wide_grid(file_name, district, schedule)
            schedule_count += 1
            print(f"      -> {wide_path.name}")

    print(f"\nAll documents complete.")
    print(f"{schedule_count} schedule grid(s) -> {WIDE_DIR}")
    print(f"Document status summary: {statuses}")


if __name__ == "__main__":
    main()
