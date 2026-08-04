#!/usr/bin/env python3
"""Extract teacher salary-schedule tables (step x lane matrices) from district PDFs.

Reads output/llm_main_dataset.csv, the wide output of llm_extract.py. For every
document where pay_salary_schedule_001_answer is "yes", locates the salary-schedule
page(s) in the *original* PDF (the cached extracted_text/*.txt is not reliable for
this — many schedule tables come through blank or garbled) and extracts the full
matrix of values with an LLM:

  - pages with extractable table text   -> text-only LLM call on the page text
  - pages with little/no table text     -> vision LLM call on a rendered page image
    (image-only / complex tables that pdftotext cannot capture)

A single set of pages can contain multiple distinct tables (different position types,
contract lengths, or fiscal years stacked on one page), and a table's data sometimes
continues onto the page after its heading (a bordered box prints on one page, the rows
print at the top of the next). The model is given an explicit primary-vs-lookahead page
distinction to handle this, and is asked to label each table's title (schedule_label)
and the employee population it covers (population / is_teacher_schedule) so non-teacher
schedules (principals, classified staff, etc.) can be told apart from the certified
teacher schedules this is primarily meant to capture.

When several large tables are stacked on one page (e.g. separate 10/11/12-month
variants of one fiscal year's schedule), asking for all of them in a single call has
been observed to make the model give up and cleanly return no tables at all, even on
pages dense with dollar amounts — total expected output volume, not page density per
se, seems to be what breaks it. split_into_subtasks() addresses this for the text path:
when a text block contains more than one heading occurrence (not just the block's own),
it is split at each heading into one smaller, single-table call instead of one large
multi-table call. Blocks with a single heading — the common case — are sent unsplit,
so this has no effect on documents that were already extracting correctly.

Every proposed table is checked twice before being accepted:
  1. validate_table() — a free, deterministic structural check for the failure mode
     observed in practice: the model collapsing a multi-column table (e.g. one column
     per fiscal year) into duplicate rows that all hold just one column's values.
  2. An independent audit LLM call — given the same source page text/image(s) plus the
     proposed table (annotated with validate_table()'s hints), it re-derives the table
     itself from the source and either confirms the proposal or supplies a corrected
     version. This mirrors llm_extract.py's stage1/stage2 retrieve-then-audit pattern.
Both checks' findings (validation_warnings, audit_matched, audit_issues, audit_corrected)
are attached to each table and written into the output CSV's header comments, so a human
reviewer can immediately see what was flagged or corrected without re-deriving it.

Per-task-block results (post-audit) are cached in cache/salary_schedule_cache/ as JSON
so an interrupted run can be resumed without re-querying the API. A block whose
extraction or audit call fails outright (e.g. malformed JSON the API retries can't fix)
is NOT cached, so it is retried fresh on the next run rather than being permanently
locked in as "no table found".

Outputs:
  output/salary_schedule_wide/<district>/<school year>/*.csv - one literal step x lane
  grid per schedule, grouped by the district and the school year/effective date the
  table itself states (so every schedule covering the same district-year lands in one
  folder, e.g. multiple position types or a teacher schedule plus a coaching-stipend
  schedule for the same year).

Calls the SOM API (an OpenAI-compatible chat completions endpoint at
https://api.som.chat/v1) rather than OpenAI directly. The key is read from
som_api_key.txt next to this script (override with SOM_API_KEY env var). SOM's only
available model as of this writing, Qwen3.6-35B-A3B-FP8, is a reasoning model that
emits a long chain-of-thought before its final JSON answer, so MAX_TOKENS is set high
(12000) to give it room to finish; truncated responses are retried with backoff, since
the backend has been observed to intermittently return "backend_unavailable" errors.

Usage:
    python3 salary_schedule.py                          # run the full "yes" gate
    python3 salary_schedule.py --max-docs 3              # limit for a quick test
    python3 salary_schedule.py --district "Davis School District" --file "Davis_2019-2020.pdf"
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pypdf import PdfReader, PdfWriter

try:  # optional: recovers real table structure from born-digital PDFs (see extract_structured_grids)
    import pdfplumber as _pdfplumber
except Exception:  # bare venvs without pdfplumber fall back to the flat-text path
    _pdfplumber = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OCR_TEXT_DIR, OUT_DIR, PDF_ROOT, ROOT, TEXT_DIR, WORK, extract_text, norm_ws, slugify
from som_client import (
    MAX_TOKENS, MODEL, budgeted_max_tokens, create_with_retries, get_client,
    reasoning_kwargs,
)

# Vision calls carry base64 page images whose token cost the char-based estimator cannot
# see, so they get a fixed, generous output budget instead of a computed one. Text calls
# are budgeted from their actual prompt. Both replace the old `max_tokens=MAX_TOKENS`
# (32000 against what the client believed was a 32000-token window) — a reasoning model
# given a 32k budget will spend it, and these were the slowest calls in the pipeline.
VISION_MAX_OUTPUT = int(os.environ.get("SALARY_VISION_MAX_OUTPUT", "8000"))

MAIN_DATASET = OUT_DIR / "llm_main_dataset.csv"
CACHE_DIR = WORK / "cache" / "salary_schedule_cache"
WIDE_DIR = OUT_DIR / "salary_schedule_wide"

# Cap on how many pages a single salary block is sent to the LLM at once. A long
# dollar-dense appendix under one heading is split into sub-blocks of at most this
# many pages so no extraction call is handed dozens of pages. Override with
# SALARY_MAX_BLOCK_PAGES.
MAX_BLOCK_PAGES = int(os.environ.get("SALARY_MAX_BLOCK_PAGES", "4"))
# Heading blocks are independent of one another (the cross-grid checks deliberately run
# after all blocks are collected), so they can be extracted concurrently. This was the
# largest single source of dead wall-clock in this coder: a 62-page appendix splits into
# ~16 blocks that were extracted strictly one at a time, each blocking on a reasoning-model
# call. The real in-flight ceiling is enforced centrally by som_client.GOVERNOR.
SALARY_BLOCK_CONCURRENCY = int(os.environ.get("SALARY_BLOCK_CONCURRENCY", "6"))
# DPI for rasterizing pages on the vision path. Higher DPI separates the columns of
# dense side-by-side multi-lane salary tables more cleanly. Override with SALARY_DPI.
SALARY_RENDER_DPI = int(os.environ.get("SALARY_DPI", "220"))

# Case-sensitive: a genuine section heading is Title Case or ALL CAPS ("Salary
# Schedule", "SALARY SCHEDULE"). All-lowercase matches are narrative cross-references
# ("...rehired on a teacher salary schedule shall...") rather than the table itself.
HEADING_RE = re.compile(
    r"(Salary\s+Schedule|SALARY\s+SCHEDULE|Salary\s+Scale|SALARY\s+SCALE|"
    r"Salary\s+Table|SALARY\s+TABLE|Salary\s+Matri(?:x|ces)|SALARY\s+MATRI(?:X|CES)|"
    r"Compensation\s+Schedule|COMPENSATION\s+SCHEDULE|"
    r"Wage\s+Schedule|WAGE\s+SCHEDULE|Pay\s+Schedule|PAY\s+SCHEDULE)"
)
# A table-of-contents entry repeats the same heading text followed shortly by
# dot-leaders and a page number; a real heading is followed by table content instead.
TOC_LEADER_RE = re.compile(r"\.{3,}")
# Dollar amounts in pdftotext output sometimes lose the literal "$" — match
# comma-grouped numbers either way (e.g. "$66,655" or "66,655").
DOLLAR_RE = re.compile(r"\$?\s?[0-9]{1,3}(?:,[0-9]{3})+(?:\.\d+)?")

# ── prompt ──────────────────────────────────────────────────────────────────────

SCHEDULE_SYSTEM_PROMPT = """\
You are extracting salary schedule tables from a U.S. public school district \
employment contract.

You will be given the text or page image(s) of one or more pages: a PRIMARY page \
range (this task's own pages) and, sometimes, one extra LOOKAHEAD page provided only \
so you can check whether a table's data continues past the primary range. Treat the \
primary page(s) as the pages you are responsible for. Use the lookahead page only to:
  (a) find the rest of a table whose heading/start appears on a primary page but whose
      data box looks incomplete or empty there (tables sometimes print a labeled,
      bordered box on one page with the actual rows printed at the top of the next
      page), or
  (b) confirm a table on the primary page(s) is NOT cut off (nothing more to add).
Do NOT extract a different table whose own heading/title starts fresh on the lookahead
page — that table will be assigned its own task later when its heading is reached.

A single set of pages can contain MORE THAN ONE distinct table — e.g. separate \
schedules for different position types (teachers vs. principals vs. paraprofessionals \
vs. classified/support staff), different contract lengths (10-month vs. 11-month vs. \
12-month), or different fiscal years stacked on the same page. Extract every distinct \
table whose heading falls on a primary page as its own entry. Do not merge unrelated \
tables together, and do not split one continuous table into multiple entries. Extract \
every such table completely even when the page is dense with several large tables — \
a page having a lot of content is not a reason to return fewer tables, fewer rows, or \
fewer cells than are actually present.

CRITICAL — SIDE-BY-SIDE PANELS: two or more panels are often printed side by side in the \
SAME horizontal band, each with its OWN lane/degree header (e.g. a "Bachelor's or \
Equivalent" panel on the left and a "Master's or Equivalent" panel on the right, then a \
"Master's + 30" panel left and a "Doctorate" panel right below), and EACH panel has its \
OWN "Step" column and its own effective-date/year columns. In flat text these panels \
interleave on one physical line (e.g. "01 47,192 48,490 50,066 51,568  01 48,580 49,916 \
51,539 53,085" is step 01 of the LEFT panel followed by step 01 of the RIGHT panel). You \
MUST read each panel separately and emit it as its OWN table (or its own set of lanes). \
The left and right panels are DIFFERENT lanes with DIFFERENT values — NEVER read one \
panel twice, never copy the left panel's numbers into the right (or vice versa), and never \
merge the two panels' step rows into one. When two panels share a step number on one line, \
the first value-group belongs to the left panel and the second to the right.

For each table, identify:
  - schedule_label: its title or caption, exactly as written (e.g. "Appendix A Salary
    Schedule", "ET-15 Salary Schedule", "Administrative Salary Schedule").
  - population: the employee population/classification it covers, in the document's
    own words if stated (e.g. "certified teachers", "principals", "classified/support
    staff", "substitutes", a position code like "EG-09" or "ET-15"). If the document
    does not name the population, infer it conservatively from context (e.g. a table
    under "Teacher Salary Schedule" in a teacher's CBA covers certified teachers) and
    say so in notes.
  - is_teacher_schedule: true only for schedules covering classroom/certified teachers
    generally. Set it false for principal, administrator, classified, substitute, or
    other non-teacher schedules — still extract them in full, just flag them as not
    the primary target. Certified teacher salary schedules are what matters most here.

Each table is typically a grid of dollar amounts indexed by a row axis (step number, \
years of service, or a salary "level" code) and, often but not always, a column axis \
(degree/lane: BA, BA+30, MA, MA+45, Doctorate, or a classification code). Some \
schedules have only one axis (a single ordered list of salary levels with no separate \
lane dimension) — that is normal; do not invent a lane axis that is not in the \
document. IMPORTANT — EXTRACT ALL COLUMNS: If the source table shows multiple named \
columns (e.g. "Base Salary", "TSSA", "Total"; or "BA", "BA+30", "MA", "PhD"; or \
separate columns for different fiscal years), every column MUST appear as a distinct \
entry in lane_labels and every cell MUST record the value from its own column. Never \
collapse multiple columns into one, never report only the TOTAL column while omitting \
base or supplement columns, and never copy one column's values across multiple lanes. \
If in doubt whether two adjacent columns are separate, preserve both.

Extra qualifier columns that don't fit a normal step/lane grid (e.g. \
longevity tiers like "17-18 Yrs Service") are still part of the same table — encode \
them as additional step or lane labels, whichever matches the document's own layout, \
rather than dropping them.

Preserve the exact row and column labels used in the document (e.g. "Step 1", \
"BA+30", "Salary Level A", "CLASS III", "14B"). If a cell has a sub-code in addition \
to a dollar value (e.g. "T02-14B  $66,655"), record the sub-code separately from the \
value.

If the input includes a "STRUCTURED TABLE" block (an aligned pipe-table recovered directly \
from the PDF), treat it as the AUTHORITATIVE source for cell values and for which row and \
column each value belongs to — transcribe it exactly, column-for-column and row-for-row. \
Never copy a column's values across other columns and never drop a column or row. Use the \
"PAGE CONTEXT" text only for the schedule title, the employee population, and the effective \
date/school year. Otherwise (flat page TEXT), if the numbers do not \
align cleanly under their column headers (common with complex tables), do your best \
to reconstruct the correct row groupings from context, but lower confidence and say \
so in notes rather than silently guessing at misaligned values.

NEVER FABRICATE — extract only what is legibly present. This source may be imperfect \
OCR. Specifically:
  - Do NOT add a fiscal-year or lane COLUMN the source does not actually contain; if the \
    source shows three year-columns, return three — never invent a fourth by copying the \
    last one. Two columns must never hold identical values unless the source truly prints \
    them identically.
  - Do NOT fill an illegible/garbled cell, row, or column by INTERPOLATING a smooth \
    uniform progression (e.g. +500 every step) or by copying an adjacent column/row. If a \
    value is unreadable, leave that cell's value an empty string and note it; if a whole \
    region is garbled/destroyed, extract only the rows you can read and set confidence \
    "low" with a note — do not manufacture plausible numbers.
  - Do NOT pull a row or column's values from a DIFFERENT schedule to fill gaps. Every \
    cell must come from THIS table.

Return ONLY a valid JSON object, no markdown fences, with this exact shape:
{
  "tables": [
    {
      "has_table": true,
      "schedule_label": "<title as written in the document>",
      "population": "<employee population/classification covered>",
      "is_teacher_schedule": true | false,
      "school_year_or_effective_date": "<as stated, empty string if not stated>",
      "lane_labels": ["<column labels in left-to-right order, or [] if no lane axis>"],
      "step_labels": ["<row labels in top-to-bottom order>"],
      "cells": [
        {"step": "<step label>", "lane": "<lane label, or null if no lane axis>",
         "value": "<dollar amount, digits only, no $ or commas>",
         "cell_code": "<sub-code if present, else null>"}
      ],
      "continues_on_lookahead_page": true | false,
      "notes": "<footnotes, caveats, ambiguities, or empty string>",
      "confidence": "high" | "medium" | "low"
    }
  ]
}

If the primary page(s) contain no salary table at all, return {"tables": []}. Extract \
every cell you can read for every table found; do not summarize, sample, or truncate.\
"""

AUDIT_SYSTEM_PROMPT = """\
You are independently auditing salary-schedule table(s) that another extraction pass \
just proposed from a U.S. public school district employment contract page. You will \
receive the same source page text or image(s) the proposed extraction was based on, \
plus the proposed table(s) as JSON. Some proposed tables carry a \
"deterministic_guardrail_hints" field — automated structural checks flagging possible \
problems (e.g. duplicate row labels, identical values repeated across rows). Treat \
these as hints to investigate, not conclusions; confirm or dismiss them yourself \
against the actual source.

Re-derive each table yourself from the source page text/image(s), independently of the \
proposed extraction. Then compare your own reading to what was proposed. Look \
specifically for:
1. WRONG AXIS ORIENTATION — step labels (e.g. "Step 1", years of service) end up as \
   lane/column labels, or vice versa, or both axes collapse into one.
2. DUPLICATE ROWS — two or more step labels are identical, or carry identical values \
   across every lane, when the source does not actually repeat a row. This typically \
   happens when only one column (e.g. the rightmost fiscal year) was read correctly \
   and copied across every row instead of reading each row's own data.
3. MISSING ROWS/COLUMNS — the source has more distinct steps, lanes, or fiscal years \
   than the proposed table captured.
4. WRONG VALUES — spot-check several cells against the source; flag any dollar amount \
   that doesn't match what the source actually shows.
5. ADJACENT-CELL BLEED — for a stipend / supplemental-pay / extra-duty table where each \
   row is a distinct position or duty (e.g. "Head Basketball", "Head Track", "Department \
   Chair"), do NOT spot-check — verify EVERY row's amount against its own label. A value \
   silently copied from the row directly above or below (adjacent-row bleed) is a common \
   error here and is invisible to a partial check because each individual value still \
   looks plausible.
6. FABRICATION (critical on OCR'd sources) — the proposed table must not contain data the \
   source does not. Check: (a) COLUMN COUNT — does the proposal have MORE value-columns \
   (e.g. fiscal years) than the source actually prints? If a column merely duplicates its \
   neighbour verbatim, it was invented — drop it. (b) SMOOTH PROGRESSION — a column filled \
   with a suspiciously uniform +N increment (e.g. +500 every step) where the source shows \
   irregular jumps is fabricated smoothing; report the real source values or mark them \
   unreadable. (c) CROSS-SCHEDULE CONTAMINATION — a row/column whose values actually belong \
   to a DIFFERENT schedule on another page. If the source region is genuinely garbled/\
   destroyed and cannot be read, say so in issues and set matches_source false with \
   corrected_table null — do NOT bless invented numbers as matching.

If you find no discrepancy, set matches_source to true. If you find a discrepancy and \
can confidently re-derive the correct table yourself from the source, set \
matches_source to false and supply corrected_table in the exact same shape as the \
proposed table entry (has_table, schedule_label, population, is_teacher_schedule, \
school_year_or_effective_date, lane_labels, step_labels, cells, notes, confidence). If \
you find a discrepancy but cannot confidently re-derive the full correct table, set \
matches_source to false, describe the issue in issues, and leave corrected_table null.

Return ONLY a valid JSON object, no markdown fences, with this exact shape:
{
  "audits": [
    {
      "table_index": <integer index matching the proposed table's position, 0-based>,
      "matches_source": true | false,
      "issues": ["<short description of each discrepancy found, empty list if none>"],
      "corrected_table": <corrected table object, or null>
    }
  ]
}
"""


# ── page location ────────────────────────────────────────────────────────────────

def parse_page_hints(value: str) -> list[int]:
    """Recorded page fields from llm_extract.py look like '107-112' or '49'."""
    nums = [int(n) for n in re.findall(r"\d+", value or "")]
    if len(nums) >= 2:
        lo, hi = min(nums), max(nums)
        if hi - lo <= 30:
            return list(range(lo, hi + 1))
    return nums


def find_heading_pages(pages: list[str]) -> list[int]:
    """1-based PDF page indices whose text matches a real salary-schedule heading.

    Printed/TOC page numbers recorded by llm_extract.py often differ from the
    actual PDF page index (front matter offsets), so headings are located by
    content match across the whole document rather than trusting the recorded
    page number literally. Table-of-contents lines (heading text immediately
    followed by dot-leaders and a page number) are excluded.
    """
    found = []
    for i, page in enumerate(pages, start=1):
        for match in HEADING_RE.finditer(page):
            window = page[match.end():match.end() + 250]
            if not TOC_LEADER_RE.search(window):
                found.append(i)
                break
    return found


def dollar_density(page_text: str) -> int:
    return len(DOLLAR_RE.findall(page_text))


# Multi-digit numbers (salaries like "65,882", step values, position codes like "093").
_NUMERIC_RE = re.compile(r"\d[\d,]{2,}")


def numeric_density(page_text: str) -> int:
    return len(_NUMERIC_RE.findall(page_text))


def covered_cell_count(tables: list[dict]) -> int:
    """Total non-empty numeric cell values across the given tables."""
    return sum(
        1
        for t in tables
        for c in (t.get("cells") or [])
        if c.get("value") not in ("", None) and any(ch.isdigit() for ch in str(c.get("value")))
    )


def block_undercovered(block_text: str, tables: list[dict], frac: float = 0.75) -> bool:
    """True when a block's extracted tables hold far fewer values than the source
    block's dollar amounts imply — the signature of rows/columns dropped at a page
    break (v5: Baltimore "G. New Hire" lost Prof steps 8-14; Broward Appendix F lost
    the MS Inservice max row). Compares non-empty numeric cells against dollar_density
    (comma-grouped $ amounts, which in a salary appendix are almost always table cells,
    not prose). No-ops on image tables (source dollar count ~0) and on blocks with too
    few dollar amounts to judge — those are handled elsewhere (cross-grid / vision)."""
    source_dollars = dollar_density(block_text)
    if source_dollars < 8:
        return False
    return covered_cell_count(tables) < frac * source_dollars


def group_schedule_blocks(pages: list[str], heading_pages: list[int]) -> list[tuple[int, int]]:
    """Return (start_page, end_page), 1-based inclusive, one range per heading.

    A block extends past its heading page while the rows keep going — either
    dollar-dense ($-prefixed salaries) OR simply value-dense (a stipend/extra-duty
    table that lists many bare numbers without "$", which would otherwise be cut off
    at the page break and truncate the table). Extension stops at the next heading.
    """
    blocks: list[tuple[int, int]] = []
    for idx, start in enumerate(heading_pages):
        next_heading = heading_pages[idx + 1] if idx + 1 < len(heading_pages) else len(pages) + 1
        end = start
        page_idx = start
        while page_idx + 1 < next_heading and (
            dollar_density(pages[page_idx]) >= 3 or numeric_density(pages[page_idx]) >= 20
        ):
            page_idx += 1
            end = page_idx
        # A long dollar-dense run under one heading (e.g. Chicago's 62-page salary
        # appendix) must not be sent to the LLM as a single block — neither the text
        # call (100k+ chars) nor the vision call (dozens of page images) can handle
        # it. Split it into <= MAX_BLOCK_PAGES-page sub-blocks, each extracted
        # independently; the per-block lookahead page preserves tables that spill
        # across a split. Normal 1-2 page schedules are unaffected.
        s = start
        while s <= end:
            e = min(s + MAX_BLOCK_PAGES - 1, end)
            blocks.append((s, e))
            s = e + 1
    return blocks


def split_into_subtasks(block_text: str) -> list[str]:
    """Split a block's text at every heading occurrence (not just the block's own,
    page-level one) so each LLM call handles one table's worth of output instead of
    several large stacked tables at once.

    Diagnosed in practice on DCPS pages with 3 stacked ET-15 month-variant tables
    (~225 dollar amounts, 4 heading matches: one page-level title plus one per
    variant) — the model reliably returned a clean-but-wrong {"tables": []} for the
    whole page, while a structurally similar page with one heading and ~50 dollar
    amounts extracted correctly every time. The failure tracked total output volume
    per call, not page density, so splitting by heading occurrence (which is exactly
    where one distinct table ends and the next begins) directly reduces that volume.
    Single-heading blocks — the common case — are returned unsplit and unchanged."""
    positions = []
    for match in HEADING_RE.finditer(block_text):
        window = block_text[match.end():match.end() + 250]
        if not TOC_LEADER_RE.search(window):
            positions.append(match.start())
    if len(positions) <= 1:
        return [block_text]
    segments = [
        block_text[pos:(positions[i + 1] if i + 1 < len(positions) else len(block_text))]
        for i, pos in enumerate(positions)
    ]
    # Drop segments with no real table content (e.g. a page-level title repeating the
    # same heading text just above the first real sub-table) rather than spending a
    # call on each.
    dense = [s for s in segments if dollar_density(s) >= 3]
    return dense or [block_text]


# ── PDF rendering ────────────────────────────────────────────────────────────────

_PAGE_COUNT_CACHE: dict = {}


def pdf_page_count(pdf_path: Path) -> int:
    """True page count of the PDF itself, cached.

    This is NOT the same number as len(text.split("\\f")). Page indices everywhere else in
    this module come from form-feed segments in the extracted text, and the two disagree
    routinely — Alpine 2014-15 yields 40 text segments for a 39-page PDF, because pdftotext
    emits a trailing form feed. Any index derived from the text and then handed to pdftoppm
    can therefore point past the end of the document.
    """
    key = str(pdf_path)
    if key not in _PAGE_COUNT_CACHE:
        try:
            out = subprocess.run(["pdfinfo", str(pdf_path)],
                                 capture_output=True, text=True, timeout=120).stdout
            m = re.search(r"^Pages:\s+(\d+)", out, re.M)
            _PAGE_COUNT_CACHE[key] = int(m.group(1)) if m else 0
        except Exception:
            _PAGE_COUNT_CACHE[key] = 0
    return _PAGE_COUNT_CACHE[key]


def render_pages_to_images(
    pdf_path: Path, start: int, end: int, tmp_dir: Path, dpi: int | None = None,
) -> list[Path]:
    """Render [start, end] to PNGs, clamped to pages the PDF actually has.

    Previously this ran pdftoppm with check=True on an unvalidated range, so a page index
    one past the end (the lookahead page of a block ending on the last page) raised
    CalledProcessError and killed the whole document's salary run. Rendering nothing is a
    recoverable outcome — the caller already treats an empty image list as "vision found
    no table" — whereas an exception is not.
    """
    n = pdf_page_count(pdf_path)
    if n:
        start, end = max(1, min(start, n)), max(1, min(end, n))
    if end < start:
        return []
    prefix = tmp_dir / "page"
    r = subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi or SALARY_RENDER_DPI),
         "-f", str(start), "-l", str(end), str(pdf_path), str(prefix)],
        check=False, capture_output=True, text=True,
    )
    images = sorted(tmp_dir.glob("page*.png"))
    if r.returncode != 0 and not images:
        print(f"  render failed p{start}-{end} of {pdf_path.name} "
              f"({(r.stderr or '').strip()[:80]}) — skipping this block")
    return images


def render_pages_rotated(
    pdf_path: Path, start: int, end: int, tmp_dir: Path, rotation: int,
) -> list[Path]:
    """Render pages [start, end] to PNGs, first rotating them `rotation` degrees
    clockwise (0 = unchanged). Rotation is applied via pypdf's page /Rotate (which
    pdftoppm honors) rather than an image library, so it works in the bare HPC venv
    (no Pillow/Tesseract/ImageMagick). Each rotation renders into its own subdir so
    the page*.png globs never collide across attempts on the same block."""
    sub = tmp_dir / f"r{rotation}"
    sub.mkdir(exist_ok=True)
    if not rotation:
        return render_pages_to_images(pdf_path, start, end, sub)
    # The rotation branch is the ONLY pypdf entry on the vision path. An AES-encrypted PDF
    # (v7: Columbus) makes PdfReader raise (needs the `cryptography` package) — and an
    # unguarded raise here crashed the whole document's salary run. Degrade gracefully to an
    # unrotated render instead: a rotated read is a best-effort landscape-recovery attempt,
    # never worth killing the run for.
    try:
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()
        for pageno in range(start - 1, end):
            page = reader.pages[pageno]
            page.rotate(rotation)  # clockwise; multiple of 90
            writer.add_page(page)
        rot_pdf = sub / f"rot{rotation}.pdf"
        with rot_pdf.open("wb") as fh:
            writer.write(fh)
        return render_pages_to_images(rot_pdf, 1, end - start + 1, sub)
    except Exception:
        return render_pages_to_images(pdf_path, start, end, sub)


def image_to_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


# ── LLM calls ────────────────────────────────────────────────────────────────────

def _page_framing(start: int, end: int, lookahead_page: int | None) -> str:
    framing = f"Primary page range (yours to extract): {start}-{end}."
    if lookahead_page:
        framing += (
            f" Lookahead page (context only, see system instructions): {lookahead_page}."
        )
    return framing


def call_text_llm(client, doc_label: str, text: str, start: int, end: int,
                  reasoning: bool = True, document_id: str = "") -> dict:
    """Read a salary grid out of page text.

    `reasoning=False` is passed by the structured (pdfplumber) path, where the input is
    already a 2-D pipe table and the job is transcription rather than layout inference —
    measured ~10x faster with no reasoning to do. The flat-text fallback keeps reasoning on
    because it must infer the grid from an unstructured stream of numbers.
    """
    user = (f"Document: {doc_label}\n{_page_framing(start, end, None)}\n\n"
            f"---PAGE TEXT---\n{text}\n---END---")
    return create_with_retries(
        client,
        _stage="salary_text", _document_id=document_id,
        model=MODEL,
        max_tokens=budgeted_max_tokens(SCHEDULE_SYSTEM_PROMPT, user),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SCHEDULE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        extra_body=reasoning_kwargs(reasoning),
    )


def call_vision_llm(
    client, doc_label: str, image_paths: list[Path], start: int, end: int,
    lookahead_page: int | None, extra_instruction: str = "",
) -> dict:
    content = [{
        "type": "text",
        "text": (
            f"Document: {doc_label}\n{_page_framing(start, end, lookahead_page)}\n"
            "Extract the salary schedule table(s) from the page image(s) below."
            + (f"\n\n{extra_instruction}" if extra_instruction else "")
        ),
    }]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(p)}})
    return create_with_retries(
        client,
        _stage="salary_vision",
        model=MODEL,
        max_tokens=VISION_MAX_OUTPUT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SCHEDULE_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )


# ── structure-preserving extraction (born-digital tables) ────────────────────────
# Flat pdftotext — even the `-layout` the pipeline uses — emits a dense salary table as a
# bare vertical stream of numbers with no step/lane/year association, so the LLM has to
# reconstruct the 2-D grid and (on complex multi-year/multi-lane/stacked schedules) copies
# a fiscal-year column across other years, drops a lane, shifts rows, or truncates. The v7
# audit tied ~10 of 20 salary PARTIALs to exactly this. pdfplumber recovers the real grid
# from the PDF's character COORDINATES, so those columns stay distinct.
_PP_STRATEGIES = (
    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
    {"vertical_strategy": "text", "horizontal_strategy": "text",
     "text_x_tolerance": 1, "text_y_tolerance": 3, "snap_tolerance": 4},
)


def _grid_is_salary(rows: list) -> bool:
    """A pdfplumber-extracted grid that looks like a salary schedule: enough rows/cols and a
    mostly-numeric body. Rejects prose tables and the character-interleaved garble that
    borderless tables sometimes produce (few real dollar-amount cells)."""
    if len(rows) < 3:
        return False
    if max((len(r) for r in rows), default=0) < 2:
        return False
    body = [c for r in rows[1:] for c in (r[1:] if len(r) > 1 else [])]
    filled = [str(c).strip() for c in body if c and str(c).strip()]
    numeric = [c for c in filled if re.search(r"\d[\d,]{2,}", c)]
    return len(filled) >= 4 and len(numeric) >= 0.55 * len(filled)


_STRUCTURED_HEADER = (
    "STRUCTURED TABLE (recovered directly from the PDF's character coordinates; this is the "
    "AUTHORITATIVE source for cell values AND for which row/column each value belongs to). "
    "Transcribe every cell EXACTLY as positioned — each column is a distinct lane/year, each "
    "row a distinct step. NEVER copy one column's values into another column, never drop a "
    "column or row, never merge columns. The first row is the column headers; the first cell "
    "of each later row is that row's step/level label. This block may hold SEVERAL stacked "
    "panels for different lanes/degrees (a lane/degree name printed on its own row, then that "
    "panel's step rows); split them into separate lanes/tables by those interior header rows, "
    "and never copy one panel's values into another. Extract all of it:"
)


def _grid_to_pipe(rows: list) -> str:
    """Serialize a pdfplumber grid as an aligned markdown pipe-table (one row per line)."""
    return "\n".join(
        "| " + " | ".join(re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()
                           for c in r) + " |"
        for r in rows
    )


_TWO_STEP_HEADER_RE = re.compile(r"\bstep\b", re.I)


def _has_side_by_side_panels(pg) -> bool:
    """True when a page lays two or more salary panels SIDE-BY-SIDE in one horizontal band
    (v9: Philadelphia p141 — Bachelor's|Master's, then M+30|Doctorate, each with its own
    "Step 9/1/20 ..." header). The tell is a single physical text line carrying the word
    "Step" (or a repeated date header) more than once — the left and right panels' headers
    printed on the same y. Whole-page find_tables interleaves such panels into one garbled
    wide grid and the extractor copies one lane into another; splitting by x fixes it."""
    try:
        txt = pg.extract_text() or ""
    except Exception:
        return False
    for line in txt.splitlines():
        if len(_TWO_STEP_HEADER_RE.findall(line)) >= 2:
            return True
    return False


def extract_structured_grids(pdf_path: Path, start: int, end: int) -> list[str]:
    """pdfplumber-recovered salary grids on pages [start,end] (1-based), each serialized as
    an aligned pipe-table string. Recovers the real rows x columns from the PDF's character
    COORDINATES (not flat pdftotext), keeping year/lane columns distinct. Tries a ruled-line
    strategy first (best for bordered schedules), then a text strategy for borderless ones.
    Pages with SIDE-BY-SIDE panels are split into left/right x-bands first so each panel's
    columns stay distinct (v9 Philadelphia fix). Returns [] if pdfplumber is unavailable, the
    page is a scanned image (no vector text), or no salary-like grid is found — callers then
    fall back to the flat-text/vision path."""
    if _pdfplumber is None:
        return []
    grids: list[str] = []
    try:
        with _pdfplumber.open(str(pdf_path)) as pdf:
            for pageno in range(start, min(end, len(pdf.pages)) + 1):
                pg = pdf.pages[pageno - 1]
                # A side-by-side page is read one x-band (panel column) at a time so the two
                # panels' year/lane columns never interleave into one garbled wide grid.
                if _has_side_by_side_panels(pg):
                    w = pg.width
                    regions = [pg.crop((0, 0, w / 2, pg.height)),
                               pg.crop((w / 2, 0, w, pg.height))]
                else:
                    regions = [pg]
                for region in regions:
                    for ts in _PP_STRATEGIES:
                        try:
                            tables = region.find_tables(table_settings=ts)
                        except Exception:
                            continue
                        found = []
                        for t in tables:
                            try:
                                rows = t.extract()
                            except Exception:
                                continue
                            if _grid_is_salary(rows):
                                found.append(_grid_to_pipe(rows))
                        if found:  # first strategy that yields salary grids wins for this region
                            grids.extend(found)
                            break
    except Exception:
        return []
    return grids


# ── deterministic guardrail + independent audit ──────────────────────────────────

_LEADING_INT_RE = re.compile(r"^\s*(\d{1,3})\b")


def _step_int(label) -> int | None:
    """Leading integer of a step label ('Step 7' -> 7, '10a' -> 10), else None."""
    m = _LEADING_INT_RE.match(str(label))
    return int(m.group(1)) if m else None


def _cell_num(v) -> float | None:
    """Parse a cell value to a number (strip $/commas), or None if non-numeric."""
    if v in ("", None):
        return None
    s = re.sub(r"[^0-9.]", "", str(v))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _column_values(table: dict, lane: str | None):
    """Numeric values of one lane column in step order (None for blank/non-numeric)."""
    steps = [str(s).strip() for s in (table.get("step_labels") or [])]
    cells = table.get("cells") or []
    out = []
    for step in steps:
        v = next((c.get("value") for c in cells
                  if c.get("step") == step and (c.get("lane") or "") == (lane or "")), None)
        out.append(_cell_num(v))
    return out


def validate_table(table: dict, source_text: str | None = None) -> list[str]:
    """Free, deterministic structural sanity check — no API call. Targets the failure
    mode observed in practice: the model collapses a multi-column table into duplicate
    rows that all hold just one column's values. Returns warning strings, empty if the
    table looks structurally sound.

    Only warnings containing the escalation triggers ("across lanes", "expected ~")
    force a vision re-extraction in process_document; the duplicate-value checks below
    are deliberately tuned so a *graded* column copied across lanes escalates while a
    *legitimately constant* flat rate (every Varsity sport paid the same, a step-
    elimination acceleration) does not — the false positives seen in the v5 audit.

    When `source_text` (the page text a text-method table was extracted from) is
    supplied, each row/column *label* is also checked against that text: a header that
    doesn't appear in the source (e.g. a merged "Standard Professional BTU.200") is
    flagged as possibly garbled. Skipped for the vision path (no comparable text)."""
    warnings: list[str] = []
    steps = [str(s).strip() for s in (table.get("step_labels") or [])]
    lanes = [str(l).strip() for l in (table.get("lane_labels") or [])]
    cells = table.get("cells") or []

    norm_steps = [s.lower() for s in steps]
    if len(norm_steps) > 1 and len(set(norm_steps)) < len(norm_steps):
        dupes = sorted({s for s in steps if norm_steps.count(s.lower()) > 1})
        warnings.append(f"duplicate step_labels: {dupes}")

    # S-E — dropped-row detector: when step labels are a numeric sequence, a MISSING
    # integer inside the run signals a row lost at extraction (v6: bachelor_s first '10-'
    # row dropped). Informational; only flags an interior gap on an otherwise-dense run.
    step_ints = [i for i in (_step_int(s) for s in steps) if i is not None]
    if len(step_ints) >= 4:
        lo, hi = min(step_ints), max(step_ints)
        have = set(step_ints)
        missing = [n for n in range(lo, hi + 1) if n not in have]
        if 0 < len(missing) <= max(2, (hi - lo) // 4):
            warnings.append(
                f"possible_dropped_row: step sequence {lo}-{hi} is missing step(s) {missing} "
                "— a row may have been lost; verify against source"
            )

    if steps and lanes:
        # Row-collapse check: the copied-column defect makes (nearly) EVERY row hold
        # one identical tuple of values. Legitimate tables can repeat a row too — many
        # sports sharing one flat stipend, a step-elimination acceleration — but those
        # leave several distinct row groups. So flag only a pervasive collapse (one
        # dominant group), not any repeated row. (Informational; does not escalate.)
        populated_rows: dict[str, tuple] = {}
        for step in steps:
            row = tuple(
                next((c.get("value") for c in cells
                      if c.get("step") == step and (c.get("lane") or "") == lane), "")
                for lane in lanes
            )
            if any(v not in ("", None) for v in row):
                populated_rows[step] = row
        row_groups: dict[tuple, list[str]] = {}
        for step, row in populated_rows.items():
            row_groups.setdefault(row, []).append(step)
        n_pop_rows = len(populated_rows)
        if n_pop_rows > 2:
            biggest = max(row_groups.values(), key=len)
            if len(row_groups) <= 1 or len(biggest) > 0.7 * n_pop_rows:
                warnings.append(
                    f"identical values across steps {sorted(biggest)} — looks like one "
                    "column copied across rows instead of each row's own data"
                )

        # Lane-COLUMN duplication (distinct from the row-collapse check above): two or
        # more lanes holding an identical value-column down all steps. This escalates a
        # block to the vision path — but ONLY when the shared column is a *graded* one
        # (values vary down the steps) copied across a majority of lanes, the real
        # defect seen on wide side-by-side tables flat pdftotext mis-parses (Chicago's
        # 208-Day schedule). A column that is CONSTANT down every step is a legitimate
        # flat rate shared across lanes (v5: Baltimore Addendum II) and must not force
        # a needless vision re-extraction, so it gets only an informational note.
        if len(lanes) > 1:
            populated_cols: dict[str, tuple] = {}
            for lane in lanes:
                col = tuple(
                    next((c.get("value") for c in cells
                          if (c.get("lane") or "") == lane and c.get("step") == step), "")
                    for step in steps
                )
                if any(v not in ("", None) for v in col):
                    populated_cols[lane] = col
            col_groups: dict[tuple, list[str]] = {}
            for lane, col in populated_cols.items():
                col_groups.setdefault(col, []).append(lane)
            for col, dup_lanes in col_groups.items():
                if len(dup_lanes) < 2:
                    continue
                col_varies = len({v for v in col if v not in ("", None)}) > 1
                if col_varies:
                    # ANY two columns that VARY down the steps yet are cell-for-cell
                    # identical are almost certainly one column copied across slots — the
                    # Chicago flat-text mis-parse AND the v6 OCR case of a fabricated year
                    # column that verbatim-copies its neighbour (e.g. "Sept 2014" == "Sept
                    # 2013"). Escalation-grade. (A CONSTANT shared column is a legitimate
                    # flat rate — v5 Addendum II — and gets only an informational note.)
                    warnings.append(
                        f"identical values across lanes {sorted(dup_lanes)} — one lane column "
                        "was copied across slots (or a fabricated column duplicates its "
                        "neighbour) instead of extracting each lane distinctly"
                    )
                else:
                    warnings.append(
                        f"note: lanes {sorted(dup_lanes)} share a constant value down all "
                        "steps (likely a legitimate flat rate, not a copy error)"
                    )

    if source_text:
        # Label-provenance (born-digital header garble): a real COLUMN header is a
        # contiguous string in the source text. A merged/shifted header (v5: Baltimore
        # 2021 "Standard Professional BTU.200") is not, so flag it for verbatim re-
        # transcription. Restricted to LANE (column) labels only: row/step labels in
        # stipend tables legitimately merge a code + activity ("1803 Head Football Coach")
        # that is not a contiguous source substring, which produced v6 false positives.
        src_norm = norm_ws(source_text)
        for label in lanes:
            nl = norm_ws(label)
            if len(nl) >= 5 and re.search(r"[a-z]", nl) and nl not in src_norm:
                warnings.append(
                    f"label_not_in_source: {label!r} — this column label is not found "
                    "in the page text; header may be garbled/merged (transcribe verbatim)"
                )

    expected_cells = len(steps) * len(lanes) if lanes else len(steps)
    if expected_cells and len(cells) < expected_cells * 0.5:
        warnings.append(
            f"only {len(cells)} cell(s) for {len(steps)} step(s) x {len(lanes) or 1} "
            f"lane(s) (expected ~{expected_cells})"
        )

    if len(lanes) == 1 and len(steps) >= 3:
        warnings.append(
            "only 1 lane column extracted — verify the source does not have "
            "additional columns (e.g. base salary, supplements, total) that were dropped"
        )
    elif not lanes and len(steps) >= 5:
        warnings.append(
            "no lane columns extracted — verify this is truly a single-column table "
            "(step → value only, with no separate degree, year, or category columns)"
        )

    # Header-without-data (dropped-row): a table that carries a title/lane/step header but
    # holds no readable numeric cell is a grid whose data row(s) were dropped at extraction
    # (v9: Miami section_g header-only, missing 600/840; Philadelphia PG526 empty grid). Flag
    # as escalation-grade so it is re-extracted / manual-reviewed, not emitted as an "empty"
    # schedule that reads as confirmed.
    n_numeric = sum(1 for c in cells
                    if c.get("value") not in ("", None)
                    and any(ch.isdigit() for ch in str(c.get("value"))))
    if n_numeric == 0 and (lanes or steps or table.get("schedule_label")):
        warnings.append(
            "no data rows: table has a header/label but zero numeric cells — a data row "
            "was dropped; re-extract or verify against source"
        )

    return warnings


# Escalation-grade validation warnings: structural signals that flat-text / structured /
# vision extraction likely lost or duplicated data. A grid still carrying one of these AFTER
# all extraction + audit is NOT "audit confirmed" — write_wide_grid marks it MANUAL REVIEW so
# a fabricated-but-plausible grid the LLM audit blessed (v9: Philadelphia lane/year copies) is
# visible rather than silent. Shared by suspect() (escalation) and write_wide_grid (reporting).
_HARD_REVIEW_SIGNALS = ("across lanes", "expected ~", "possible_dropped_row",
                        "missing step", "no data rows", "cross_grid_duplicate")


def hard_review_warnings(table: dict) -> list[str]:
    """Escalation-grade subset of a table's validation_warnings (empty if structurally sound)."""
    return [w for w in (table.get("validation_warnings") or [])
            if any(s in w for s in _HARD_REVIEW_SIGNALS)]


def call_text_audit_llm(
    client, doc_label: str, text: str, start: int, end: int, proposed_tables: list[dict],
) -> dict:
    user = (f"Document: {doc_label}\n{_page_framing(start, end, None)}\n\n"
            f"PROPOSED EXTRACTION (to audit):\n{json.dumps(proposed_tables, indent=2)}\n\n"
            f"---PAGE TEXT---\n{text}\n---END---")
    return create_with_retries(
        client,
        _stage="salary_text_audit",
        model=MODEL,
        max_tokens=budgeted_max_tokens(AUDIT_SYSTEM_PROMPT, user),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )


def call_vision_audit_llm(
    client, doc_label: str, image_paths: list[Path], start: int, end: int,
    lookahead_page: int | None, proposed_tables: list[dict],
) -> dict:
    content = [{
        "type": "text",
        "text": (
            f"Document: {doc_label}\n{_page_framing(start, end, lookahead_page)}\n"
            "Independently audit the proposed salary-schedule extraction below against "
            "the page image(s).\n\n"
            f"PROPOSED EXTRACTION (to audit):\n{json.dumps(proposed_tables, indent=2)}"
        ),
    }]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(p)}})
    return create_with_retries(
        client,
        _stage="salary_vision_audit",
        model=MODEL,
        max_tokens=VISION_MAX_OUTPUT,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
    )


def _extract_and_audit(
    cache_path: Path, method: str, call_extract, call_audit, source_text: str | None = None,
) -> tuple[list[dict], bool]:
    """Run one extraction+audit call, or read its already-cached result. call_extract()
    takes no arguments; call_audit(hinted_tables) takes the proposed tables annotated
    with validate_table()'s hints. `source_text`, when given (text path only), enables
    validate_table's label-provenance check. Returns (tables, failed) — failed is True
    if either call raised after retries, in which case nothing is cached."""
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8")).get("tables", []), False
    try:
        raw = call_extract()
        proposed = [t for t in raw.get("tables", []) if t.get("has_table", True)]
        if proposed:
            hinted = [{**t, "deterministic_guardrail_hints": validate_table(t, source_text)}
                      for t in proposed]
            audit = call_audit(hinted)
        else:
            audit = {"audits": []}
    except Exception:
        return [], True
    tables = apply_audit(proposed, audit.get("audits", []), source_text)
    cache_path.write_text(
        json.dumps({"tables": tables, "extraction_method": method}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return tables, False


def _vision_extract_rotated(
    client, file_name: str, document_id: str, pdf_path: Path,
    start: int, end: int, lookahead_page: int | None, cache_path: Path,
) -> tuple[list[dict], bool]:
    """Vision extraction that tolerates sideways/landscape salary tables.

    Tries the page upright first (cached under the canonical vision key — unchanged
    behavior for the common, upright case). If upright extraction yields no table —
    the signature of a table printed sideways on an otherwise-upright page (e.g.
    Buffalo 1999) — it re-renders the page rotated 90° then 270° and accepts the
    first orientation that produces a table, promoting that result to the canonical
    key. Rotations return no table (proposed empty) cost only one extract call each
    (the audit call is skipped when nothing is proposed), and this whole path only
    runs on blocks the text path already failed, so the added calls are bounded."""
    end_render = lookahead_page or end
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        images = render_pages_rotated(pdf_path, start, end_render, tmp_dir, 0)
        tables, failed = _extract_and_audit(
            cache_path, "vision",
            lambda: call_vision_llm(client, file_name, images, start, end, lookahead_page),
            lambda hinted: call_vision_audit_llm(
                client, file_name, images, start, end, lookahead_page, hinted,
            ),
        )
        if failed or tables:
            return tables, failed

        # Upright produced nothing — try rotated orientations.
        for rotation in (90, 270):
            rot_cache = CACHE_DIR / f"{document_id}__{start}-{end}__vision_r{rotation}.json"
            r_images = render_pages_rotated(pdf_path, start, end_render, tmp_dir, rotation)
            r_tables, r_failed = _extract_and_audit(
                rot_cache, "vision",
                lambda i=r_images: call_vision_llm(client, file_name, i, start, end, lookahead_page),
                lambda hinted, i=r_images: call_vision_audit_llm(
                    client, file_name, i, start, end, lookahead_page, hinted,
                ),
            )
            if r_tables:
                for t in r_tables:
                    t["orientation_correction_deg"] = rotation
                cache_path.write_text(
                    json.dumps({"tables": r_tables, "extraction_method": "vision"},
                               indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return r_tables, False

    # No orientation yielded a table; keep the (already-cached) empty upright result.
    return tables, False


def apply_audit(proposed: list[dict], audits: list[dict], source_text: str | None = None) -> list[dict]:
    """Merge independent-audit findings into the proposed tables: use a corrected_table
    when the audit found a mismatch and supplied one, otherwise keep the original. Always
    (re)computes validation_warnings on whichever table is finally chosen, and attaches
    audit_matched/audit_issues/audit_corrected for transparency in the output CSV."""
    by_index = {a.get("table_index"): a for a in audits if isinstance(a.get("table_index"), int)}
    result = []
    for i, table in enumerate(proposed):
        audit = by_index.get(i, {})
        matched = audit.get("matches_source", True)
        corrected = audit.get("corrected_table")
        used_correction = bool(not matched and corrected)
        final = dict(corrected) if used_correction else dict(table)
        final["validation_warnings"] = validate_table(final, source_text)
        final["audit_matched"] = matched
        final["audit_issues"] = audit.get("issues", [])
        final["audit_corrected"] = used_correction
        result.append(final)
    return result


# ── cross-grid duplication (document-level) ───────────────────────────────────────

# Disambiguation instruction appended to the vision re-extraction of a schedule that
# came out identical to another one (v5: Denver's page-image ProTech grid == Educators
# grid; ESLI's BA+36/MA column carrying another grid's BA+18 value).
DISAMBIGUATION_INSTRUCTION = (
    "IMPORTANT: read every value directly from THIS page's own table only. Do NOT copy, "
    "reuse, or infer any value from a different schedule. If the table is a scanned image, "
    "read the printed digits cell by cell. Map each value to the column header printed "
    "directly above it, exactly as written — do not shift, merge, or relabel columns."
)


def _value_signature(schedule: dict) -> Counter:
    """Multiset of a schedule's non-empty numeric cell values (labels ignored) — the
    fingerprint used to detect two DIFFERENT schedules extracted with the same grid."""
    return Counter(
        str(c.get("value")).strip()
        for c in (schedule.get("cells") or [])
        if c.get("value") not in ("", None) and any(ch.isdigit() for ch in str(c.get("value")))
    )


def _signature_overlap(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    return sum((a & b).values()) / max(sum(a.values()), sum(b.values()))


def _dedup_label(sch: dict) -> str:
    """Normalized schedule identity used to decide whether an identical-value grid is a safe
    verbatim REPRINT (same schedule, drop the copy) or a mis-extraction (a DIFFERENT schedule
    that came out identical, must not be dropped)."""
    return norm_ws(str(sch.get("schedule_label") or "") + " "
                   + str(sch.get("population") or "")).lower()


def _provenance_key(sch: dict) -> tuple:
    """Where this grid physically came from: (page range, panel band, label).

    Value-signature dedup alone cannot fix over-extraction, because it compares WHAT was
    read rather than WHERE it was read from. LAUSD emitted 172 grids for ~50 real schedules
    because the same physical table, re-read from a page-split or a re-extraction pass, has
    a slightly different value multiset each time (one dropped cell defeats Counter equality)
    and so survives as a "distinct" schedule.

    Two extractions of the same physical region ARE the same grid regardless of whether their
    cell sets came out byte-identical. The panel band matters because side-by-side panels are
    genuinely different schedules printed on the same pages.
    """
    return (sch.get("page_start"), sch.get("page_end"),
            sch.get("panel_band"), _dedup_label(sch))


def dedup_by_provenance(schedules: list[dict]) -> tuple[list[dict], int]:
    """Collapse grids extracted from the same physical region, keeping the richest one.

    Runs BEFORE the value-signature dedup: provenance is the stronger identity claim, and
    resolving it first stops near-duplicate re-reads of one table from being compared against
    each other as if they were separate schedules.
    """
    kept: dict = {}
    order: list = []
    dropped = 0
    for sch in schedules:
        key = _provenance_key(sch)
        if key[0] is None:                       # no page provenance -> cannot judge; keep
            order.append(id(sch))
            kept[id(sch)] = sch
            continue
        prior = kept.get(key)
        if prior is None:
            kept[key] = sch
            order.append(key)
            continue
        dropped += 1
        # Keep whichever read recovered more of the table, preferring one that resolved a
        # school year over one that did not.
        better = (len(sch.get("cells") or []) > len(prior.get("cells") or [])
                  or (not prior.get("school_year_or_effective_date")
                      and sch.get("school_year_or_effective_date")))
        if better:
            kept[key] = sch
    return [kept[k] for k in order if k in kept], dropped


_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-–—/]\s*(20\d{2}|\d{2})\b")
_FY_RE = re.compile(r"\bFY\s*(20\d{2})\b", re.I)
_EFF_RE = re.compile(
    r"\beffective\s+(?:date\s+)?(?:on\s+|as\s+of\s+)?"
    r"([A-Z][a-z]+\.?\s+\d{1,2},?\s+20\d{2}|\d{1,2}/\d{1,2}/\d{2,4})", re.I)


def resolve_schedule_year(sch: dict, page_text: str) -> str:
    """Best available (school_year | effective date) for filing this grid.

    This is the largest MEASURED salary defect: in the full-census audit, 5 of the 10 failing
    grids had 100% correct cell values and failed only because they were filed under the
    wrong year or an `unknown_year` folder. The year is almost always printed on the page
    ("FY 2025 ET-15 Salary Schedule", "Effective Oct 6, 2024"); the extractor just wasn't
    required to find it. Prefer what the model already resolved, then the grid's own label,
    then the page text.
    """
    if str(sch.get("school_year_or_effective_date") or "").strip():
        return str(sch["school_year_or_effective_date"]).strip()
    haystacks = [str(sch.get("schedule_label") or ""), str(sch.get("population") or ""),
                 page_text or ""]
    for hay in haystacks:
        m = _YEAR_RE.search(hay)
        if m:
            end = m.group(2)
            end = end if len(end) == 4 else "20" + end
            return f"{m.group(1)}_{end}"
    for hay in haystacks:
        m = _FY_RE.search(hay)
        if m:
            return f"fy_{m.group(1)}"
    for hay in haystacks:
        m = _EFF_RE.search(hay)
        if m:
            y = re.search(r"20\d{2}", m.group(1))
            if y:
                return f"effective_{y.group(0)}"
    return ""


def dedup_identical_schedules(schedules: list[dict]) -> tuple[list[dict], int]:
    """Remove grids whose numeric value-multiset is IDENTICAL to one already kept AND that
    carry the SAME schedule label/population — the byte-identical page-split reprints and
    cross-year-identical differentials that inflate the grid count (v9 audit: LA 172 grids
    ~70% duplicates from `__pNNN` page splits; Portland 19 = 10 distinct + 9 dup pairs;
    Philadelphia's `unknown_year` grids duplicate their `9_1_20` siblings; Miami's section_3
    == a0). Exact-multiset match only, so grids with genuinely different numbers are always
    kept. Two grids with identical values but DIFFERENT labels are a mis-extraction (one copied
    from the other), NOT a reprint — they are KEPT and flagged so the cross-grid resolver can
    re-extract the distinct one; dropping would lose real data (v9: Fresno JROTC career-
    increment was silently dropped as a copy of the Teachers grid). When a same-label duplicate
    carries an explicit school year and the kept copy does not, the year-labelled copy wins."""
    kept: list[dict] = []
    kept_sigs: list[Counter] = []
    dropped = 0
    for sch in schedules:
        sig = _value_signature(sch)
        if sum(sig.values()) < 4:            # too few values to judge a duplicate — keep
            kept.append(sch); kept_sigs.append(sig); continue
        match = next((i for i, ks in enumerate(kept_sigs) if ks == sig), None)
        if match is None:
            kept.append(sch); kept_sigs.append(sig); continue
        if _dedup_label(sch) != _dedup_label(kept[match]):
            # Same values, different schedule label → mis-extraction, NOT a reprint. Keep both
            # so the document-level cross-grid resolver (flag_cross_grid_duplicates →
            # reextract_disambiguated, or a MANUAL-REVIEW flag on OCR docs) can handle the
            # distinct one; dropping here would lose real data (v9: Fresno JROTC == Teachers).
            kept.append(sch); kept_sigs.append(sig); continue
        dropped += 1
        if not (kept[match].get("school_year_or_effective_date") or "").strip() and \
               (sch.get("school_year_or_effective_date") or "").strip():
            kept[match] = sch            # prefer the year-labelled copy over an unknown-year twin
    return kept, dropped


def flag_cross_grid_duplicates(schedules: list[dict], threshold: float = 0.95) -> list[tuple[int, int]]:
    """Return index pairs of schedules whose non-empty cell VALUES are >= `threshold`
    identical despite carrying different schedule_labels — the cross-grid duplication
    seen on Denver's page-image teacher schedules (the ProTech grid came out cell-for-
    cell identical to the Educators grid). Pure/deterministic and side-effect free; the
    caller decides how to resolve (a disambiguating vision re-extraction) and flag."""
    sigs = [_value_signature(s) for s in schedules]
    pairs: list[tuple[int, int]] = []
    for i in range(len(schedules)):
        if sum(sigs[i].values()) < 6:  # too few values to judge confidently
            continue
        for j in range(i + 1, len(schedules)):
            if sum(sigs[j].values()) < 6:
                continue
            li = (schedules[i].get("schedule_label") or "").strip().casefold()
            lj = (schedules[j].get("schedule_label") or "").strip().casefold()
            if li and li == lj:
                continue  # same-label split/continuation of one table, not a dup
            if _signature_overlap(sigs[i], sigs[j]) >= threshold:
                pairs.append((i, j))
    return pairs


def _add_cross_grid_warning(schedule: dict, other: dict) -> None:
    ws = schedule.setdefault("validation_warnings", [])
    msg = (
        f"cross_grid_duplicate: cell values are ~identical to a different schedule "
        f"({other.get('schedule_label', '?')} p{other.get('page_start', '?')}) — distinct "
        "schedules should not share a value grid; verify each against its own page"
    )
    if msg not in ws:
        ws.append(msg)


def reextract_disambiguated(
    client, file_name: str, pdf_path: Path, start, end, dpi: int = 300,
) -> dict | None:
    """Re-extract one page range via the vision path at raised DPI with an explicit
    'read this page's own digits, don't copy between schedules' instruction, to break a
    cross-grid duplication / lane-mislabel on image tables. Returns the first post-audit
    table (with recomputed validation_warnings), or None. Not cached — only runs on the
    rare page already flagged as a cross-grid duplicate."""
    if not start:
        return None
    end = end or start
    with tempfile.TemporaryDirectory() as tmp:
        images = render_pages_to_images(pdf_path, int(start), int(end), Path(tmp), dpi=dpi)
        try:
            raw = call_vision_llm(
                client, file_name, images, int(start), int(end), None,
                extra_instruction=DISAMBIGUATION_INSTRUCTION,
            )
            proposed = [t for t in raw.get("tables", []) if t.get("has_table", True)]
            if not proposed:
                return None
            hinted = [{**t, "deterministic_guardrail_hints": validate_table(t)} for t in proposed]
            audit = call_vision_audit_llm(
                client, file_name, images, int(start), int(end), None, hinted,
            )
        except Exception:
            return None
        tables = apply_audit(proposed, audit.get("audits", []))
    return tables[0] if tables else None


def resolve_cross_grid_duplicates(
    client, file_name: str, pdf_path: Path, schedules: list[dict], text_is_ocr: bool = False,
) -> None:
    """Detect cross-grid duplicates and try to fix them in place. For each duplicated
    pair, re-extract each vision-method member from its own page with the disambiguation
    instruction; adopt a re-extraction that materially changes the grid. Whatever pair
    remains ~identical afterward is flagged (the CSV writer also stamps MANUAL REVIEW on
    any vision-method schedule), so a genuine duplicate is surfaced, never silent.

    On an OCR-sourced document the "original page" is a scanned image the vision path can
    read no better than the OCR did, so re-extraction is skipped — the pair is flagged for
    manual review instead."""
    reextracted: set[int] = set()  # re-extract each schedule at most once per document
    for i, j in flag_cross_grid_duplicates(schedules):
        if not text_is_ocr:
            for k in (i, j):
                sch = schedules[k]
                # 2B — re-extract ANY method member of a cross-grid duplicate, not just
                # vision. A structured/flat-text grid that came out identical to a different
                # schedule conflated the two at parse time (v9: Fresno JROTC == Teachers on
                # a born-digital page); an independent high-DPI vision re-read disambiguates
                # it. Only adopted when it materially changes (a known-wrong duplicate has
                # nothing to lose), so a correct grid is never replaced by a worse read.
                if k in reextracted:
                    continue
                reextracted.add(k)
                fixed = reextract_disambiguated(
                    client, file_name, pdf_path, sch.get("page_start"), sch.get("page_end"),
                )
                if fixed and _value_signature(fixed) != _value_signature(sch):
                    for key in ("lane_labels", "step_labels", "cells", "schedule_label",
                                "population", "validation_warnings"):
                        if key in fixed:
                            sch[key] = fixed[key]
                    sch["extraction_method"] = "vision"  # adopted a vision re-read
        if _signature_overlap(_value_signature(schedules[i]),
                              _value_signature(schedules[j])) >= 0.95:
            _add_cross_grid_warning(schedules[i], schedules[j])
            _add_cross_grid_warning(schedules[j], schedules[i])


def _is_uniform_progression(vals, min_len: int = 5) -> bool:
    """True if the numeric values form a single constant, non-zero arithmetic step."""
    nums = [v for v in vals if v is not None]
    if len(nums) < min_len:
        return False
    diffs = {round(nums[i + 1] - nums[i], 2) for i in range(len(nums) - 1)}
    return len(diffs) == 1 and 0 not in diffs


def flag_ocr_fabrication(schedules: list[dict]) -> None:
    """S-C/S-F — OCR-context checks, applied only when the document text came from OCR.
    Flags (a) a value column that is a suspiciously uniform +N progression (the signature
    of the model smoothing garbled OCR into invented numbers) and (b) implausibly large
    values (destroyed/exploded OCR), so a human reviews rather than trusting fabrications.
    Adds warnings in place."""
    for sch in schedules:
        ws = sch.setdefault("validation_warnings", [])
        for lane in (sch.get("lane_labels") or [None]):
            if _is_uniform_progression(_column_values(sch, lane)):
                msg = (f"suspicious_uniform_progression: column {lane!r} increments by a "
                       "constant every step — on OCR'd input this may be invented smoothing; "
                       "verify against the source")
                if msg not in ws:
                    ws.append(msg)
        nums = [n for n in (_cell_num(c.get("value")) for c in (sch.get("cells") or []))
                if n is not None]
        if nums and max(nums) > 500000:
            msg = ("ocr_unreliable: contains values far above a plausible salary — the OCR "
                   "of this table may be destroyed; manual review required")
            if msg not in ws:
                ws.append(msg)


def flag_cross_grid_contamination(schedules: list[dict]) -> None:
    """S-D — partial cross-grid overlap beyond whole-grid identity: a distinctive graded
    value-column that appears in TWO different schedules (v6: `old_steps` == Sign Language's
    June column; psychologists rows == Counselors tops). Flags both with a
    cross_grid_contamination warning. Complements flag_cross_grid_duplicates (whole-grid)."""
    cols = []  # (schedule_index, lane_label, value_tuple)
    for i, sch in enumerate(schedules):
        for lane in (sch.get("lane_labels") or [None]):
            vals = tuple(v for v in _column_values(sch, lane) if v is not None)
            if len(vals) >= 4 and len(set(vals)) >= 3:  # distinctive graded column
                cols.append((i, lane, vals))
    for a in range(len(cols)):
        for b in range(a + 1, len(cols)):
            ia, _, va = cols[a]
            ib, _, vb = cols[b]
            if ia != ib and va == vb:
                for k, other in ((ia, ib), (ib, ia)):
                    ws = schedules[k].setdefault("validation_warnings", [])
                    msg = (f"cross_grid_contamination: a value column matches a column in a "
                           f"different schedule (p{schedules[other].get('page_start', '?')}) — "
                           "one grid's data may be contaminated from another; verify")
                    if msg not in ws:
                        ws.append(msg)


# ── per-document pipeline ────────────────────────────────────────────────────────

def _extract_block_via_segments(
    client, file_name: str, document_id: str, pdf_path: Path, pages: list[str],
    segments: list[str], method: str, start: int, end: int,
) -> tuple[list[dict], int]:
    """Extract one salary block from TEXT segments (flat-text or pdfplumber-structured):
    extract+audit each segment, then — if a MULTI-page block comes back empty (dense-table
    JSON output overran the token cap and truncated the whole block, e.g. Chicago's 208-Day
    appendix) — retry page by page so each single page's slice fits under the cap. Returns
    (block_tables, n_failed) where n_failed counts segments whose API call raised."""
    multi = len(segments) > 1
    block_tables: list[dict] = []
    n_failed = 0
    for sub_idx, segment in enumerate(segments):
        # Single-segment blocks (the common case) keep the original cache filename so
        # already-cached documents aren't re-extracted just because splitting is supported.
        cache_path = CACHE_DIR / (
            f"{document_id}__{start}-{end}__{sub_idx:02d}.json" if multi
            else f"{document_id}__{start}-{end}.json"
        )
        tables, failed = _extract_and_audit(
            cache_path, method,
            # Structured (pdfplumber pipe-table) input is already 2-D: transcription, not
            # layout inference, so reasoning is off. Flat text keeps it on.
            lambda seg=segment: call_text_llm(client, file_name, seg, start, end,
                                              reasoning=(method != "structured"),
                                              document_id=document_id),
            lambda hinted, seg=segment: call_text_audit_llm(client, file_name, seg, start, end, hinted),
            source_text=segment,
        )
        if failed:
            # Don't cache the failure — retry this segment on the next run rather than
            # permanently locking it in as "no table".
            n_failed += 1
            continue
        for t in tables:
            if not t.get("has_table", True):
                continue
            # Segment index doubles as the panel band: for a structured read each segment IS
            # one pdfplumber grid (an x-band on a side-by-side page), so (pages, band) is a
            # stable physical address for this table. dedup_by_provenance uses it to collapse
            # re-reads of one table without merging two panels that genuinely differ.
            t.setdefault("panel_band", sub_idx)
            block_tables.append(t)
    if not block_tables and end > start and pdf_path.stat().st_size > 0:
        for pg in range(start, end + 1):
            pcache = CACHE_DIR / f"{document_id}__{pg}-{pg}__page.json"
            ptables, pfailed = _extract_and_audit(
                pcache, "text",
                lambda p=pg: call_text_llm(client, file_name, pages[p - 1], p, p),
                lambda hinted, p=pg: call_text_audit_llm(client, file_name, pages[p - 1], p, p, hinted),
                source_text=pages[pg - 1],
            )
            if not pfailed:
                block_tables.extend(t for t in ptables if t.get("has_table", True))
    return block_tables, n_failed


def document_id_for(district: str, file_name: str) -> str:
    path = PDF_ROOT / district / file_name
    doc_hash = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:8]
    return f"{slugify(district, 45)}__{slugify(Path(file_name).stem, 55)}__{doc_hash}"


def process_document(
    client, document_id: str, file_name: str, district: str, page_hint: str,
) -> tuple[list[dict], str, int, int]:
    """Returns (schedules, status, blocks_failed, total_blocks)."""
    pdf_path = PDF_ROOT / district / file_name
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        return [], "needs_dropbox_hydration", 0, 0

    text_path = TEXT_DIR / f"{document_id}.txt"
    text = extract_text(pdf_path, text_path)
    pages = text.split("\f") if text else []
    if not pages:
        return [], "no_extractable_text", 0, 0
    # Whether this document's text came from OCR (a cache/ocr_text override exists). OCR-
    # sourced grids get the anti-fabrication / garble checks and skip vision re-extraction.
    text_is_ocr = (OCR_TEXT_DIR / f"{document_id}.txt").exists()

    heading_pages = find_heading_pages(pages)
    if not heading_pages:
        heading_pages = [p for p in parse_page_hints(page_hint) if 1 <= p <= len(pages)]
    if not heading_pages:
        return [], "no_schedule_heading_found", 0, 0

    blocks = group_schedule_blocks(pages, heading_pages)
    schedules: list[dict] = []
    blocks_failed = 0
    CACHE_DIR.mkdir(exist_ok=True)

    def collect(tables: list[dict], method: str, start: int, end: int) -> None:
        for table in tables:
            if not table.get("has_table", True):
                continue
            entry = dict(table)
            entry.setdefault("extraction_method", method)
            entry.setdefault("page_start", start)
            entry.setdefault("page_end", end)
            # Carry a slice of the source page text so the writer can recover the school
            # year / effective date when the extraction didn't state one.
            entry.setdefault("_page_text", "\f".join(pages[start - 1:end])[:6000])
            schedules.append(entry)

    def suspect(tables: list[dict]) -> bool:
        # Warnings that mean flat-text/structured extraction likely lost or duplicated
        # data, so the 2-D vision path should be tried: a lane column copied across slots,
        # a table returned with far fewer cells than its step x lane grid implies, a step
        # sequence with an interior/tail GAP (a long matrix truncated at a page break — v9:
        # Albuquerque AT-3 dropped steps 33-50; Portland 183-day tables dropped a step), or
        # a header-only grid whose data row was dropped (v9: Miami section_g). Vision reads
        # the full multi-page image and recovers the missing rows. Shares the escalation
        # signal set with write_wide_grid via hard_review_warnings().
        return any(hard_review_warnings(t) for t in tables)

    def process_block(block: tuple) -> tuple:
        """Extract one heading block. Pure w.r.t. document state: returns
        (start, end, block_tables, method, n_failed) so the caller can collect in document
        order regardless of completion order. Blocks are independent — the cross-grid checks
        below deliberately run only after every block is in — so they can run concurrently.
        Concurrency itself is governed centrally in som_client, not here."""
        start, end = block
        block_text = "\f".join(pages[start - 1:end])
        # Bound the lookahead by BOTH the text's page count and the PDF's real one: those
        # two disagree whenever pdftotext emits a trailing form feed, and the lookahead is
        # the index most likely to fall in the gap.
        _npdf = pdf_page_count(pdf_path) or len(pages)
        lookahead_page = end + 1 if end + 1 <= min(len(pages), _npdf) else None
        has_pdf = pdf_path.stat().st_size > 0
        blocks_failed = 0

        # Choose this salary block's PRIMARY read:
        #   A. pdfplumber recovers a clean grid (born-digital) -> STRUCTURED: exact cell
        #      values AND positions straight from the PDF's character coordinates; trusted,
        #      no vision needed (kills flat-text reconstruction on the tables it can segment).
        #   B. otherwise -> VISION-PRIMARY: read the 2-D grid directly from the rendered page
        #      image. Reconstructing a dense multi-year/multi-lane grid from FLAT TEXT copies a
        #      fiscal-year column across other years, drops a lane, shifts rows, or truncates —
        #      and reads even CLEAN OCR into a valid-LOOKING but fabricated grid that never
        #      tripped the old text-then-escalate heuristic (v7/v8 audit: Cleveland year-column
        #      copies passed "audit confirmed"; Pittsburgh scrambled columns on readable OCR).
        #      The page image preserves the visual grid, so it is now the primary reader for
        #      every non-structured block, born-digital or scanned. Flat text is demoted to a
        #      fallback used only when vision yields nothing (or there is no usable PDF).
        structured = [] if text_is_ocr else extract_structured_grids(pdf_path, start, end)
        block_tables: list[dict] = []
        method = "text"

        if structured:
            ctx = block_text[:3500]
            segments = [
                f"PAGE CONTEXT (use ONLY for the schedule title, employee population, and "
                f"effective date/school year):\n{ctx}\n\n{_STRUCTURED_HEADER}\n{g}"
                for g in structured
            ]
            method = "structured"
            block_tables, nf = _extract_block_via_segments(
                client, file_name, document_id, pdf_path, pages, segments, method, start, end)
            blocks_failed += nf
        elif has_pdf:
            vcache = CACHE_DIR / f"{document_id}__{start}-{end}__vision.json"
            vtables, vfailed = _vision_extract_rotated(
                client, file_name, document_id, pdf_path, start, end, lookahead_page, vcache)
            vtables = [t for t in vtables if t.get("has_table", True)]
            if vfailed:
                blocks_failed += 1
            elif vtables:
                block_tables, method = vtables, "vision"

        if not block_tables:
            # Fallback flat-text: no structured grid AND vision was empty/failed (or a 0-byte
            # placeholder). Split the block's text and extract; a multi-page block that comes
            # back empty is retried page-by-page inside the helper.
            segments = split_into_subtasks(block_text)
            method = "text"
            block_tables, nf = _extract_block_via_segments(
                client, file_name, document_id, pdf_path, pages, segments, method, start, end)
            blocks_failed += nf

        # Safety net: a STRUCTURED or TEXT grid that still looks broken — a lane column copied
        # across slots, or far fewer cells than the block's dollar amounts imply (dropped/
        # truncated rows) — gets a vision re-extraction, preferred when it comes back cleaner
        # OR with more values. Vision-primary results already read the 2-D layout; not re-run.
        if block_tables and method != "vision" and has_pdf:
            undercovered = block_undercovered(block_text, block_tables)
            if suspect(block_tables) or undercovered:
                vcache = CACHE_DIR / f"{document_id}__{start}-{end}__vision.json"
                vtables, vfailed = _vision_extract_rotated(
                    client, file_name, document_id, pdf_path, start, end, lookahead_page, vcache)
                vtables = [t for t in vtables if t.get("has_table", True)]
                if not vfailed and vtables and (
                    not suspect(vtables)
                    or covered_cell_count(vtables) > covered_cell_count(block_tables)
                ):
                    block_tables, method = vtables, "vision"

        return start, end, block_tables, method, blocks_failed

    if len(blocks) > 1 and SALARY_BLOCK_CONCURRENCY > 1:
        with ThreadPoolExecutor(max_workers=min(SALARY_BLOCK_CONCURRENCY, len(blocks))) as ex:
            results = list(ex.map(process_block, blocks))
    else:
        results = [process_block(b) for b in blocks]

    for start, end, block_tables, method, nf in results:
        blocks_failed += nf
        if block_tables:
            collect(block_tables, method, start, end)

    # Drop verbatim duplicate grids (byte-identical page-split reprints / cross-year-
    # identical differentials) before the cross-grid checks and the writer, so a multi-page
    # appendix reprinted once per contract year doesn't emit the same schedule N times.
    if len(schedules) > 1:
        # Provenance first: two reads of the SAME physical region are one grid even when
        # their cell sets differ slightly, which value-signature dedup cannot see.
        schedules, n_prov = dedup_by_provenance(schedules)
        if n_prov:
            print(f"  deduped {n_prov} re-read(s) of the same page/panel region")
        schedules, n_dup = dedup_identical_schedules(schedules)
        if n_dup:
            print(f"  deduped {n_dup} identical page-split/reprint grid(s)")

    # Document-level cross-grid checks (v5: Denver's page-image teacher schedules; v6:
    # Pittsburgh's OCR'd grids contaminated across schedules). Run once all blocks are
    # collected, since they compare schedules from different heading blocks/pages.
    if pdf_path.stat().st_size > 0 and len(schedules) > 1:
        resolve_cross_grid_duplicates(client, file_name, pdf_path, schedules, text_is_ocr=text_is_ocr)
        flag_cross_grid_contamination(schedules)
    # OCR-context anti-fabrication checks (uniform-progression smoothing, exploded values).
    if text_is_ocr:
        flag_ocr_fabrication(schedules)

    return schedules, "ok", blocks_failed, len(blocks)


# ── output writers ───────────────────────────────────────────────────────────────

# The audit pass's own words when it concludes the extraction is not supported by the page.
# When it says this, the grid must NOT be published as data.
_FABRICATION_PHRASES = (
    "appears to be fabricated", "is fabricated", "not present in the provided",
    "does not appear in the source", "no tabular schedule", "not supported by the source",
    "invented", "hallucinat",
)


def _audit_says_fabricated(schedule: dict) -> str:
    """Return the audit's fabrication verdict, or "" if it did not make one.

    MEASURED: Polk County's Appendix C grid was published with its own audit note reading
    "The proposed extraction appears to be fabricated or extracted from a page not
    provided" — 17 rows of hourly rates that occur ZERO times in the 126-page source. The
    pipeline detected the fabrication correctly and then wrote it to the dataset anyway,
    because nothing consumed that verdict. Detecting a defect and publishing it regardless
    is worse than not detecting it: it launders the error through a file that looks like
    every other grid.
    """
    blob = " ".join([
        " ".join(str(x) for x in (schedule.get("audit_issues") or [])),
        " ".join(str(x) for x in (schedule.get("validation_warnings") or [])),
        str(schedule.get("notes") or ""),
    ]).lower()
    for phrase in _FABRICATION_PHRASES:
        if phrase in blob:
            return phrase
    return ""


def _data_signature(schedule: dict) -> str:
    """Hash of the grid's actual values + lane/step labels, ignoring title and provenance."""
    cells = sorted(
        f"{c.get('step_label','')}|{c.get('lane_label','')}|{c.get('value','')}"
        for c in (schedule.get("cells") or [])
    )
    return hashlib.md5("\n".join(cells).encode("utf-8")).hexdigest()


# Data signatures already written in this process, so the same grid is emitted once.
_WRITTEN_SIGNATURES: dict = {}


def write_wide_grid(file_name: str, district: str, schedule: dict) -> Path:
    """Writes to output/salary_schedule_wide/<district>/<school year>/<schedule>.csv —
    grouped by district then by the school year/effective date the table itself
    states, so every schedule for a given district-year sits in one folder."""
    district_slug = slugify(district, 60) or "unknown_district"
    # Fall back to reading the year off the page before giving up and filing under
    # unknown_year: mis-filing was the single largest measured salary defect (5 of the 10
    # failing grids in the full-census audit had 100% correct cells and only the wrong
    # folder), and the year is nearly always printed on the schedule page itself.
    year_slug = slugify(
        resolve_schedule_year(schedule, schedule.get("_page_text", "")), 40) or "unknown_year"

    # A grid the audit pass judged unsupported goes to _quarantine/, not into the dataset.
    verdict = _audit_says_fabricated(schedule)
    out_dir = (WIDE_DIR / "_quarantine" / district_slug if verdict
               else WIDE_DIR / district_slug / year_slug)
    if verdict:
        print(f"  QUARANTINED {schedule.get('schedule_label','?')!r}: audit verdict "
              f"matched {verdict!r} — not published as data")

    # Emit each distinct grid once. The page-by-page retry re-extracts a block's pages
    # individually, so the same table arrives twice under different page ranges (e.g.
    # `__p109-109`); provenance dedup keeps both because the ranges differ, and value-
    # signature dedup keeps both when the labels differ. 11 of 50 v11 files were redundant
    # copies. Signature is over VALUES and labels only, so a genuine reprint under a
    # different year still collapses to one file.
    sig = _data_signature(schedule)
    if not verdict and sig in _WRITTEN_SIGNATURES:
        return _WRITTEN_SIGNATURES[sig]

    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(schedule.get("schedule_label") or f"schedule_{schedule['page_start']}", 50)
    pdf_slug = slugify(Path(file_name).stem, 40)
    path = out_dir / f"{slug}__{pdf_slug}.csv"
    if path.exists():
        # Two distinct tables landed on the same district/year/label/pdf path — most
        # often because school_year_or_effective_date came back empty (or identical)
        # for more than one table from different pages. Disambiguate by page rather
        # than silently overwriting one table's data with another's.
        path = out_dir / f"{slug}__{pdf_slug}__p{schedule.get('page_start', 'x')}-{schedule.get('page_end', 'x')}.csv"

    lanes = schedule.get("lane_labels") or []
    steps = schedule.get("step_labels") or []
    grid: dict[tuple[str, str], str] = {}
    for cell in schedule.get("cells", []):
        grid[(cell.get("step", ""), cell.get("lane") or "")] = cell.get("value", "")

    warnings = schedule.get("validation_warnings") or []
    hard = hard_review_warnings(schedule)
    if schedule.get("audit_corrected"):
        audit_note = "audit corrected this table"
    elif schedule.get("audit_matched") is False:
        audit_note = "audit flagged unresolved issues: " + "; ".join(schedule.get("audit_issues") or [])
    elif hard:
        # The LLM audit blessed it, but a deterministic structural signal survived — do NOT
        # report "audit confirmed" (v9: Philadelphia lane/year copies passed the LLM audit).
        audit_note = "MANUAL REVIEW — unresolved structural issue(s): " + "; ".join(hard)
    else:
        audit_note = "audit confirmed"

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"# {file_name} — {schedule.get('schedule_label', '')} "
                    f"({schedule.get('school_year_or_effective_date', '')})"])
        w.writerow([f"# population: {schedule.get('population', '')} | "
                    f"is_teacher_schedule: {schedule.get('is_teacher_schedule', '')}"])
        w.writerow([f"# validation_warnings: {'; '.join(warnings) or 'none'} | {audit_note}"])
        if hard:
            w.writerow(["# MANUAL REVIEW RECOMMENDED: unresolved structural issue(s) — "
                        + "; ".join(hard)])
        elif schedule.get("extraction_method") == "vision":
            w.writerow(["# MANUAL REVIEW RECOMMENDED: extracted from page image (not "
                        "machine-readable text) — verify values, column names, and row "
                        "counts against the original PDF"])
        if lanes:
            w.writerow(["step"] + lanes)
            for step in steps:
                w.writerow([step] + [grid.get((step, lane), "") for lane in lanes])
        else:
            w.writerow(["step", "value"])
            for step in steps:
                w.writerow([step, grid.get((step, ""), "")])
    _WRITTEN_SIGNATURES[sig] = path
    return path


# ── input loading ────────────────────────────────────────────────────────────────

def load_yes_rows(max_docs: int | None) -> list[tuple[str, str, str, str]]:
    """Return (document_id, file_name, district_name, page_hint) for yes rows."""
    if not MAIN_DATASET.exists():
        sys.exit(f"Error: {MAIN_DATASET} not found — run llm_extract.py first.")
    rows = []
    with MAIN_DATASET.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # Accept any yes-prefixed answer, not just an exact "yes": the model often
            # returns a verbose yes ("Yes. Appendix A covers all bargaining unit
            # employees...") which an exact match would silently drop even though the
            # document has a salary schedule.
            if not row.get("pay_salary_schedule_001_answer", "").strip().lower().startswith("yes"):
                continue
            rows.append((
                row["document_id"], row["file_name"], row["district_name"],
                row.get("pay_salary_schedule_001_page", ""),
            ))
    return rows[:max_docs] if max_docs else rows


# ── entry point ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--district", help="Process a single PDF: district folder name")
    parser.add_argument("--file", help="Process a single PDF: file name within --district")
    parser.add_argument("--max-docs", type=int, default=None, help="Limit number of documents processed")
    args = parser.parse_args()

    # Register the request-hash cache + telemetry sink. som_client only records calls when
    # a sink is registered, so this must happen at every entry point or a real run produces
    # no cache and no telemetry (which is how the first v11 smoke test ran).
    try:
        import store
        store.get_store().start_run(notes="salary_schedule")
    except Exception as exc:      # never let instrumentation stop a run
        print(f"  [store] telemetry unavailable: {exc}")


    client = get_client()

    if args.district or args.file:
        if not (args.district and args.file):
            sys.exit("Error: --district and --file must be given together.")
        document_id = document_id_for(args.district, args.file)
        targets = [(document_id, args.file, args.district, "")]
    else:
        targets = load_yes_rows(args.max_docs)

    print(f"Processing {len(targets)} document(s) ...")

    statuses: dict[str, int] = {}
    schedule_count = 0
    corrected_count = 0
    flagged_count = 0

    for i, (document_id, file_name, district, page_hint) in enumerate(targets, start=1):
        print(f"[{i:>2}/{len(targets)}] {file_name} ...")
        schedules, status, blocks_failed, total_blocks = process_document(
            client, document_id, file_name, district, page_hint,
        )
        statuses[status] = statuses.get(status, 0) + 1
        if status != "ok":
            print(f"      {status}")
            continue
        if blocks_failed:
            print(f"      {blocks_failed}/{total_blocks} page-block(s) failed extraction/audit (will retry next run)")
        print(f"      {len(schedules)} schedule(s) found")
        for schedule in schedules:
            wide_path = write_wide_grid(file_name, district, schedule)
            schedule_count += 1
            if schedule.get("audit_corrected"):
                corrected_count += 1
                print(f"      -> {wide_path.name} [audit corrected]")
            elif schedule.get("audit_matched") is False:
                flagged_count += 1
                print(f"      -> {wide_path.name} [audit flagged, unresolved]")
            else:
                print(f"      -> {wide_path.name}")

    print(f"\n{schedule_count} schedule grid(s) -> {WIDE_DIR}")
    if corrected_count or flagged_count:
        print(f"  {corrected_count} corrected by audit, {flagged_count} flagged with unresolved issues")
    print(f"Document status summary: {statuses}")


if __name__ == "__main__":
    main()
