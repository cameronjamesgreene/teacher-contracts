#!/usr/bin/env python3
"""Stage 3: label each salary table's semantics. One short call per table.

The numbers never travel. Geometry already produced them and they are correct by
construction; sending them to a model only creates an opportunity to corrupt them, which
is exactly what the path this replaces did (28,241 cells round-tripped through Qwen, and
UTLA p339 came back with the annual column copied over the monthly one and one row's
values pulled from another).

What geometry cannot know is what the columns MEAN. After the deterministic pass:

    employee_group   100% empty      (nothing in the geometry says "paraprofessional")
    pay_basis         97% empty      (hourly vs annual is a semantic, not a coordinate)
    lane_type         80% "none"     (a column headed "1" could be a step or a year)
    days_per_year     91% null       (stated in the page's prose, not in the table)

Each is a small, closed-vocabulary judgement, and the model is good at those. It is sent
the schedule title, the column headers, up to three row labels, and the page's prose —
never a value.

## Why this is affordable now

Measured against api.som.chat on 2026-08-14 (scripts/som_measurements.md): a forced tool
call returns in ~1.0s and concurrency 16 completes 16/16 faster than 8 does. 486 tables
therefore cost well under a minute. The pipeline's configured "concurrency 8, ~9.6s per
call" was an order of magnitude pessimistic.

**Thinking must be off.** With `enable_thinking` left on, a forced `tool_choice` returns
no tool call at all — a silent failure, not an error.

## Caching

Keyed on a hash of the ACTUAL PROMPT, not on (document, index). Every other cache in this
repo keys on position alone, so editing a prompt and re-running silently returns the old
prompt's answers — which makes prompt experiments impossible without hand-deleting files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from salary_schema import EMPLOYEE_GROUPS, LANE_TYPES, PAY_BASES
from som_client import MODEL, get_client
from utils import OUT_DIR, PDF_ROOT, WORK

CACHE_DIR = WORK / "cache" / "salary_label_cache"
TEACHER_GROUPS = {"teacher", "substitute_teacher"}
WORKERS = 16
PROSE_CHARS = 1200

TOOL = {
    "type": "function",
    "function": {
        "name": "label_schedule",
        "description": "Record what one salary table's rows and columns mean.",
        "parameters": {
            "type": "object",
            "properties": {
                "employee_group": {"type": "string", "enum": list(EMPLOYEE_GROUPS),
                                   "description": "Who this schedule pays."},
                "pay_basis": {"type": "string", "enum": list(PAY_BASES),
                              "description": "The unit each amount is expressed in."},
                "lane_type": {"type": "string", "enum": list(LANE_TYPES),
                              "description": "What the COLUMNS vary by."},
                "days_per_year": {"type": ["integer", "null"],
                                  "description": "Contract days, ONLY if the page states "
                                                 "it. Null otherwise - never guess."},
            },
            "required": ["employee_group", "pay_basis", "lane_type"],
        },
    },
}

SYSTEM = """\
You label salary tables from U.S. school district contracts. You are given a table's title, \
its column headers, a few of its row labels, and the prose printed on the same page. You \
are NOT given the salary figures, and you do not need them.

Call label_schedule exactly once.

employee_group - who is paid by THIS table. A contract covers many groups; use the title \
and row labels, not the district's main bargaining unit. "other" only when nothing fits.
When the title names SEVERAL groups ("Level 1 Teachers & Librarians and Career Pathway \
Level 1 Counselors, Nurses, Social Workers & Interpreters"), choose the FIRST-NAMED group \
- it is the schedule's primary population. Do not pick the last one you read.

pay_basis - the unit of the amounts. Headers like "Hourly Rate" or "Per Diem" decide it. \
An annual teacher salary schedule is "annual"; a substitute day rate is "daily".

lane_type - what the COLUMNS vary by. Degree lanes (BA, MA+30) are "education". Dated \
columns (9/1/21, September 2011) are "effective_date". Pay grades are "pay_grade". A \
paired monthly/annual layout is "basis". Use "none" when the columns carry no such meaning.

days_per_year - ONLY if the page states a contract-day count in words, e.g. "Matrices \
AT-1, AT-2 and AT-3: 184 days". If the page does not say, return null. Do not infer it \
from the salary level or from a school-year length."""


def _days_supported(days: int, prose: str) -> bool:
    """True only when the page really prints this number as a day count.

    Both spellings occur: "184 days" and "one hundred eighty-four (184) days".
    """
    return bool(re.search(rf"\b{days}\b[^.\n]{{0,24}}?\bdays?\b", prose or "", re.I)
                or re.search(rf"\bdays?\b[^.\n]{{0,24}}?\b{days}\b", prose or "", re.I))


def prompt_for(table: dict) -> str:
    lines = [f"Schedule title: {table['title'] or '(untitled)'}",
             f"Column headers: {' | '.join(table['lanes']) or '(none)'}",
             f"Row labels (first few): {', '.join(table['steps'][:3]) or '(none)'}"]
    if table["prose"]:
        lines.append(f"Prose on the page:\n{table['prose']}")
    return "\n".join(lines)


def label_one(client, table: dict, *, refresh: bool = False) -> dict | None:
    text = prompt_for(table)
    # Hash the prompt AND the tool schema, so editing either invalidates. Positional keys
    # elsewhere in this repo silently serve stale answers after a prompt edit.
    digest = hashlib.sha1((SYSTEM + text + json.dumps(TOOL, sort_keys=True)
                           + MODEL).encode()).hexdigest()[:20]
    cached = CACHE_DIR / f"{digest}.json"
    if cached.exists() and not refresh:
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    try:
        response = client.chat.completions.create(
            model=MODEL, max_tokens=300,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": text}],
            tools=[TOOL],
            tool_choice={"type": "function", "function": {"name": "label_schedule"}},
            # Required: with thinking ON, a forced tool_choice returns NO tool call.
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    except Exception:
        return None
    calls = response.choices[0].message.tool_calls
    if not calls:
        return None
    try:
        answer = json.loads(calls[0].function.arguments or "{}")
    except json.JSONDecodeError:
        return None
    # An answer outside the vocabulary is a validation failure, not a new category.
    if answer.get("employee_group") not in EMPLOYEE_GROUPS: return None
    if answer.get("pay_basis") not in PAY_BASES: return None
    if answer.get("lane_type") not in LANE_TYPES: return None
    # days_per_year is CHECKED, not trusted. The model returned 120 for a substitute
    # hourly table whose page says no such thing. The host can settle this: the number has
    # to actually appear on the page next to the word "day".
    days = answer.get("days_per_year")
    if days is not None:
        if not (120 <= int(days) <= 260) or not _days_supported(int(days), table["prose"]):
            answer["days_per_year"] = None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(answer), encoding="utf-8")
    return answer


def page_prose(pdf: Path, page_number: int) -> str:
    """The page's text, which is where a contract states its day basis."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf)) as document:
            if 1 <= page_number <= len(document.pages):
                return (document.pages[page_number - 1].extract_text() or "")[:PROSE_CHARS]
    except Exception:
        return ""
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--out", type=Path, default=OUT_DIR / "salary_long.csv")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--refresh", action="store_true", help="ignore cached labels")
    args = parser.parse_args()

    rows = list(csv.DictReader(args.long.open(newline="", encoding="utf-8")))
    fields = list(rows[0].keys())
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["source_pdf"], row["page_start"], row["grid_id"])].append(row)

    pdfs = {p.name: p for p in PDF_ROOT.rglob("*.pdf")}
    tables = []
    for key, members in groups.items():
        source, page, _ = key
        lanes, steps = [], []
        for member in members:
            if member["lane_raw"] and member["lane_raw"] not in lanes:
                lanes.append(member["lane_raw"])
            if member["step_raw"] and member["step_raw"] not in steps:
                steps.append(member["step_raw"])
        tables.append({"key": key, "title": members[0]["schedule_title"],
                       "lanes": lanes[:12], "steps": steps[:3],
                       "prose": page_prose(pdfs[source], int(page or 0))
                                if source in pdfs else ""})
    if args.limit:
        tables = tables[: args.limit]
    print(f"  tables to label: {len(tables)}")

    client = get_client()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(lambda t: label_one(client, t, refresh=args.refresh), tables))

    labelled = failed = 0
    for table, answer in zip(tables, answers):
        if answer is None:
            failed += 1
            continue
        labelled += 1
        for row in groups[table["key"]]:
            row["employee_group"] = answer["employee_group"]
            row["is_teacher"] = str(answer["employee_group"] in TEACHER_GROUPS)
            if not row["pay_basis"]:
                row["pay_basis"] = answer["pay_basis"]
            if row["lane_type"] == "none":
                row["lane_type"] = answer["lane_type"]
            if not row["days_per_year"] and answer.get("days_per_year"):
                row["days_per_year"] = str(answer["days_per_year"])

    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  labelled {labelled} tables, {failed} failed")
    print(f"  -> {args.out}")
    print("LABEL_DONE")


if __name__ == "__main__":
    main()
