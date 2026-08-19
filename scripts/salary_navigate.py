#!/usr/bin/env python3
"""Find a document's salary-schedule page blocks with a bounded tool-calling agent.

## What this replaces, and why

`salary_schedule.py` locates schedules with two hand-tuned heuristics: a regex over
headings (`find_heading_pages`), then a density rule that extends a block while
`dollar_density >= 3 or numeric_density >= 20` (`group_schedule_blocks`). Both are
reasonable and both produce the defects the version history records — tables truncated
at a page break, appendix schedules missed entirely, continuation pages swallowed into
the wrong block. A threshold cannot tell a schedule that continues from a different
schedule that happens to start with a dense page.

Deciding *where to look* is a navigation problem, which is what an agent is for. The
model gets cheap tools to survey the document and read pages, and returns the page
ranges. It never extracts a single number — `salary_schedule.py` still does that with
the same text and vision calls as before.

## Design constraints, each for a stated reason

**Bounded.** A hard cap on tool calls. The recorded failure of an earlier agent attempt
in this project was unboundedness, not tools; a counter fixes that and nothing else has
to change.

**Thinking off.** Navigation is mechanical. Measured on this endpoint, a real
extraction-shaped prompt runs 62.3s with reasoning on and 9.6s off, finding the same
content. Reasoning is worth paying for on judgement, not on "which pages have a table".

**Never worse than the heuristic.** Any failure — cap exceeded, malformed reply, empty
result, unusable ranges — falls back to `group_schedule_blocks`. The agent can improve
the outcome; it cannot break a document that used to work.

**The host validates.** Proposed ranges are clamped to the document, de-overlapped and
sorted here. The model proposes; it does not get to return page 700 of a 200-page PDF.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from som_client import MODEL, create_with_retries, get_client

# A long document takes a few calls to survey and a few more to check appendices before
# the agent can answer. Measured on a 110-page contract it spends 1 call surveying and
# 3-4 searching, so a cap of 12 cut it off mid-exploration; the budget is now large
# enough to finish and small enough to bound cost.
MAX_TOOL_CALLS = 24
# When this few calls remain, the agent is told to stop looking and answer. Without it a
# cap is just a truncation — the run ends with nothing rather than with its best guess.
NUDGE_AT_REMAINING = 6
# Enough of a page for the model to tell a salary table from prose, without spending
# the context window on a document that can run to hundreds of pages.
PAGE_PREVIEW_CHARS = 1200
# Fallback only. The caller passes salary_schedule's own MAX_BLOCK_PAGES, because that
# is the ceiling the extraction calls were sized against — a block longer than it is
# handed to a text call as 100k+ chars, or to a vision call as dozens of page images.
# Hard-coding a different number here silently hands the extractor blocks it cannot
# process, which looks like an extraction failure rather than a navigation bug.
DEFAULT_MAX_BLOCK_PAGES = 4

SYSTEM = """You locate salary-schedule tables in a teacher union contract.

You are given tools to survey and read the document. Your job is ONLY to decide which
PDF page ranges contain salary-schedule tables. You do not read out any salary values.

What counts as a salary schedule: a table of pay amounts, typically step x lane
(experience x education), including extra-duty/stipend schedules and schedules for
non-teacher groups. A table of contents entry is NOT a schedule. Prose describing a
raise is NOT a schedule.

What matters most:
- A table that continues onto the next page must be ONE block covering both pages.
- Two different schedules that happen to be adjacent must be TWO blocks.
- Appendix schedules are easy to miss; survey the whole document before answering.

Call survey_pages first to see where the dense pages are. Read pages when you cannot
tell from the summary. Then call propose_blocks exactly once with your answer."""

TOOLS = [
    {"type": "function", "function": {
        "name": "survey_pages",
        "description": ("Density summary for a range of pages: how many dollar amounts "
                        "and bare numbers each page holds, and its first line. Cheap — "
                        "use this to find candidate regions before reading anything."),
        "parameters": {"type": "object", "properties": {
            "start": {"type": "integer", "description": "first PDF page, 1-based"},
            "end": {"type": "integer", "description": "last PDF page, inclusive"}},
            "required": ["start", "end"]}}},
    {"type": "function", "function": {
        "name": "read_page",
        "description": "The opening text of one PDF page. Use when the summary is ambiguous.",
        "parameters": {"type": "object", "properties": {
            "page": {"type": "integer", "description": "PDF page number, 1-based"}},
            "required": ["page"]}}},
    {"type": "function", "function": {
        "name": "find_text",
        "description": ("Pages whose text contains a phrase, case-insensitive. Use for "
                        "headings like 'salary schedule' or 'Appendix A'."),
        "parameters": {"type": "object", "properties": {
            "phrase": {"type": "string"}}, "required": ["phrase"]}}},
    {"type": "function", "function": {
        "name": "propose_blocks",
        "description": ("Your final answer: every page range holding a salary schedule. "
                        "Call this exactly once, when you are done looking."),
        "parameters": {"type": "object", "properties": {
            "blocks": {"type": "array", "items": {"type": "object", "properties": {
                "start": {"type": "integer"}, "end": {"type": "integer"},
                "label": {"type": "string", "description": "the table's own title, if visible"}},
                "required": ["start", "end"]}}},
            "required": ["blocks"]}}},
]


def _survey(pages: list[str], start: int, end: int, dollar_density, numeric_density) -> str:
    start, end = max(1, start), min(len(pages), end)
    lines = []
    for number in range(start, end + 1):
        page = pages[number - 1]
        first = next((l.strip() for l in page.splitlines() if l.strip()), "")
        lines.append(f"p{number}: ${dollar_density(page)} nums={numeric_density(page)} | {first[:90]}")
    return "\n".join(lines) or "no pages in range"


def _dispatch(name: str, args: dict, pages: list[str], dollar_density, numeric_density) -> str:
    if name == "survey_pages":
        return _survey(pages, int(args.get("start", 1)), int(args.get("end", len(pages))),
                       dollar_density, numeric_density)
    if name == "read_page":
        number = int(args.get("page", 0))
        if not 1 <= number <= len(pages):
            return f"no such page; document has {len(pages)} pages"
        return pages[number - 1][:PAGE_PREVIEW_CHARS]
    if name == "find_text":
        phrase = str(args.get("phrase", "")).lower().strip()
        if not phrase:
            return "empty phrase"
        hits = [str(i) for i, page in enumerate(pages, 1) if phrase in page.lower()]
        return ("pages: " + ", ".join(hits[:60])) if hits else "no page contains that phrase"
    return f"unknown tool {name}"


def _clean_blocks(raw: list[dict], page_count: int,
                  max_block_pages: int = DEFAULT_MAX_BLOCK_PAGES) -> list[tuple[int, int]]:
    """Clamp, split over-long, sort and merge overlaps. The host owns the page range."""
    spans: list[tuple[int, int]] = []
    for item in raw or []:
        try:
            start, end = int(item.get("start", 0)), int(item.get("end", 0))
        except (TypeError, ValueError):
            continue
        if start < 1 or start > page_count:
            continue
        end = max(start, min(end if end else start, page_count))
        spans.append((start, end))
    if not spans:
        return []
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    # Same ceiling salary_schedule applies: an over-long run is split so neither the
    # text call nor the vision call is handed a block it cannot process.
    out: list[tuple[int, int]] = []
    for start, end in merged:
        cursor = start
        while cursor <= end:
            out.append((cursor, min(cursor + max_block_pages - 1, end)))
            cursor += max_block_pages
    return out


JOIN_SYSTEM = """You are shown the bottom of one page of a teacher contract and the top
of the next. Both contain salary figures with the same column layout.

Decide ONE thing: is the second page the SAME table continuing, or a DIFFERENT table?

Continuing looks like: the step/row sequence carries on where the first page stopped;
no new title; the second page starts straight into rows.
Different looks like: the step sequence starts over at 1; a new heading, year, employee
group or schedule name appears; the second page starts with a title row.

Answer with the tool. Do not explain."""

JOIN_TOOL = [{"type": "function", "function": {
    "name": "decide_join",
    "description": "Whether the second page continues the first page's table.",
    "parameters": {"type": "object", "properties": {
        "same_table": {"type": "boolean"},
        "why": {"type": "string", "description": "one short clause"}},
        "required": ["same_table"]}}}]


def adjudicate_join(client, page_before: str, page_after: str,
                    tail_chars: int = 900, head_chars: int = 900) -> tuple[bool | None, str]:
    """Same table or not, for one ambiguous page break. Returns (decision, why).

    Called only where `salary_segment` could not decide from geometry — typically a
    page whose layout matches its predecessor and which calls itself "(cont.)" but
    carries no step labels to confirm it. That is a handful of joins per document
    rather than a judgement on every page, which is what makes an agent affordable
    here at all.

    Returns (None, reason) on any failure so the caller keeps its deterministic guess.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL, max_tokens=2000, tools=JOIN_TOOL,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            messages=[
                {"role": "system", "content": JOIN_SYSTEM},
                {"role": "user", "content":
                    f"--- END OF FIRST PAGE ---\n{page_before[-tail_chars:]}\n\n"
                    f"--- START OF SECOND PAGE ---\n{page_after[:head_chars]}"},
            ])
    except Exception as error:
        return None, f"adjudication failed: {type(error).__name__}"
    calls = response.choices[0].message.tool_calls or []
    if not calls:
        return None, "model did not answer"
    try:
        args = json.loads(calls[0].function.arguments or "{}")
    except json.JSONDecodeError:
        return None, "unparseable answer"
    if "same_table" not in args:
        return None, "answer omitted same_table"
    return bool(args["same_table"]), str(args.get("why", ""))[:120]


def locate_blocks(client, pages: list[str], district: str, file_name: str,
                  dollar_density, numeric_density,
                  max_tool_calls: int = MAX_TOOL_CALLS,
                  max_block_pages: int = DEFAULT_MAX_BLOCK_PAGES) -> tuple[list[tuple[int, int]], str]:
    """Agent-proposed salary blocks, or ([], reason) so the caller can fall back."""
    if not pages:
        return [], "no pages"
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content":
            f"Document: {district} / {file_name}. It has {len(pages)} PDF pages.\n"
            f"Find every salary-schedule page range, then call propose_blocks once."},
    ]
    calls = 0
    while calls < max_tool_calls:
        try:
            response = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS, max_tokens=4000,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        except Exception as error:
            return [], f"model call failed: {type(error).__name__}"
        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            return [], "model stopped without proposing blocks"

        messages.append({"role": "assistant", "content": message.content or "",
                         "tool_calls": [tc.model_dump() for tc in tool_calls]})
        for call in tool_calls:
            calls += 1
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if call.function.name == "propose_blocks":
                blocks = _clean_blocks(args.get("blocks"), len(pages), max_block_pages)
                return (blocks, "") if blocks else ([], "agent proposed no usable blocks")
            messages.append({
                "role": "tool", "tool_call_id": call.id,
                "content": _dispatch(call.function.name, args, pages,
                                     dollar_density, numeric_density)})

        remaining = max_tool_calls - calls
        if 0 < remaining <= NUDGE_AT_REMAINING:
            messages.append({
                "role": "user",
                "content": (f"You have {remaining} tool call(s) left. Stop searching and "
                            f"call propose_blocks now with the best answer you have.")})
    return [], f"tool-call cap of {max_tool_calls} reached without an answer"
