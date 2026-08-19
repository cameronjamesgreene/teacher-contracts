#!/usr/bin/env python3
"""Find salary tables from the PDF's own geometry, before any model is asked anything.

## Why geometry first

`salary_schedule.py` decides which pages hold a schedule with a density rule — extend a
block while the page has enough dollar amounts. That rule cannot answer the question
that actually matters at a page break: *is this the same table continuing, or a new one
starting?* Both look like "another dense page". Getting it wrong either truncates a
table or fuses two.

The answer is in the PDF. Measured on Manchester pages 42-44, which a density rule and a
tool-calling agent both mis-segmented:

    p42   6 money columns, 13 rows, steps 1..13,  title "APPENDIX B"
    p43   6 money columns, 13 rows, unlabelled,   title "APPENDIX B (cont.)"
    p44   6 money columns, 14 rows, steps 1..14,  title "APPENDIX B (cont.)"

Page 44 restarts the step sequence, so it is a *third* annual schedule, not a
continuation — and that is arithmetic, not judgement. No model call is needed to see it.

## What this module produces

A fingerprint per page (column centres, row count, step labels, title band) and a
segmentation into regions. Each region carries the geometry that produced it, which is
worth as much as the page range:

* **expected_cells** = rows x columns. The transcription can then be *checked* rather
  than trusted — under-extraction, the top recorded defect, becomes a comparison
  instead of a guess.
* **confident** = False where the signals disagree. Those joins, and only those, are
  worth a model call (see `salary_navigate.adjudicate_join`). Everything else is free.

Scanned pages have no vector text, so they fingerprint as empty and the caller keeps
its existing vision path. This module never guesses about a page it cannot see.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# A pay amount: comma-grouped, or four-plus digits. Deliberately the same shape the
# scorer uses, so "what we expected to extract" and "what we check" cannot drift apart.
MONEY = re.compile(r"^\$?\d{1,3}(?:,\d{3})+(?:\.\d\d)?$|^\$?\d{4,}(?:\.\d\d)?$")
_CONT = re.compile(r"\b(cont(?:inued|\.)?|continued)\b", re.I)
_INT = re.compile(r"^\d{1,3}$")

COLUMN_TOLERANCE = 12      # points; two money tokens this close share a column
ROW_TOLERANCE = 3          # points; words this close vertically are one row
MIN_COLUMN_MEMBERS = 3     # a column needs this many values to be a column, not a stray
MIN_MONEY_TOKENS = 8       # below this a page is prose that happens to mention money
# A salary *schedule* is a matrix: steps down, lanes across. With fewer money columns
# than this you have a list of amounts inside prose — a coaching stipend, a credential
# differential, a mentoring payment — and measured on Albuquerque those extract badly:
# the four real matrices (4-7 columns) scored fidelity 1.000, while every 1-2 column
# region scored 0.500-0.833, with half the values not even on the page they cited.
#
# They are excluded here rather than extracted badly. Nothing is lost: the contract text
# containing them is read in full by rights_score (which chunks the whole document) and
# is indexed passage-by-passage for the 106-question extraction — pages 28, 29, 84 and 86
# of Albuquerque are already cited by pay_hardtostaff_sped_009, pay_national_board_017
# and pd_new_teacher_mentoring_001. A prose stipend is a sentence, and the sentence
# programs handle sentences better than a grid extractor does.
#
# The cost, stated: a genuine single-lane schedule (step -> one amount) is excluded too.
# That is the deliberate trade — those are rare, and reading one as prose is better than
# emitting a grid whose values are half invented.
MIN_TABLE_COLUMNS = 3
TITLE_BAND_POINTS = 90     # from the top of the page; where a schedule states its name
# Two pages' column layouts match if every column lines up within this. Generous,
# because a table redrawn on the next page shifts a few points; measured drift on
# Manchester's three schedules was ~10pt with identical structure.
LAYOUT_TOLERANCE = 20


@dataclass(frozen=True)
class PageFingerprint:
    page: int                       # 1-based PDF page
    columns: tuple[int, ...] = ()   # x-centre of each money column
    money_rows: int = 0
    money_tokens: int = 0
    steps: tuple[str, ...] = ()     # left-hand label of each money row, in order
    title: str = ""
    has_text: bool = False

    @property
    def is_table(self) -> bool:
        """A salary matrix, not a prose page that mentions money. See MIN_TABLE_COLUMNS."""
        return (self.money_tokens >= MIN_MONEY_TOKENS
                and len(self.columns) >= MIN_TABLE_COLUMNS)

    @property
    def continues(self) -> bool:
        """The page says so itself — 'Appendix B (cont.)'."""
        return bool(_CONT.search(self.title))

    def numeric_steps(self) -> list[int]:
        return [int(s) for s in self.steps if _INT.match(s.strip())]


@dataclass
class Region:
    start: int
    end: int
    columns: tuple[int, ...]
    rows: int
    confident: bool = True
    reason: str = ""
    joins: list[dict] = field(default_factory=list)   # ambiguous joins, for adjudication

    @property
    def expected_cells(self) -> int:
        return self.rows * len(self.columns)


def _cluster(values: list[float], tolerance: float) -> list[list[float]]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups


def fingerprint_page(page) -> PageFingerprint:
    """Geometry of one pdfplumber page. Empty fingerprint if it has no vector text."""
    try:
        words = page.extract_words()
    except Exception:
        return PageFingerprint(page=page.page_number)
    if not words:
        return PageFingerprint(page=page.page_number)

    money = [w for w in words if MONEY.match(w["text"].strip())]
    if len(money) < MIN_MONEY_TOKENS:
        return PageFingerprint(page=page.page_number, has_text=True,
                               money_tokens=len(money))

    centres = [(w["x0"] + w["x1"]) / 2 for w in money]
    columns = tuple(round(sum(g) / len(g)) for g in _cluster(centres, COLUMN_TOLERANCE)
                    if len(g) >= MIN_COLUMN_MEMBERS)

    leftmost_money = min(w["x0"] for w in money)
    rows: dict[int, list[dict]] = {}
    for word in words:
        rows.setdefault(round(word["top"] / ROW_TOLERANCE), []).append(word)

    steps: list[str] = []
    money_rows = 0
    for key in sorted(rows):
        row = sorted(rows[key], key=lambda w: w["x0"])
        if not any(MONEY.match(w["text"].strip()) for w in row):
            continue
        money_rows += 1
        # The step label is whatever sits left of the first money column.
        label = next((w["text"].strip() for w in row if w["x1"] < leftmost_money), "")
        steps.append(label)

    title = " ".join(w["text"] for w in words if w["top"] < TITLE_BAND_POINTS)
    return PageFingerprint(page=page.page_number, columns=columns, money_rows=money_rows,
                           money_tokens=len(money), steps=tuple(steps),
                           title=title.strip()[:160], has_text=True)


def fingerprint_document(pdf_path: Path) -> list[PageFingerprint]:
    try:
        import pdfplumber
    except ImportError:
        return []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            return [fingerprint_page(page) for page in pdf.pages]
    except Exception:
        return []


def _layout_matches(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return (len(a) == len(b) and bool(a)
            and all(abs(x - y) <= LAYOUT_TOLERANCE for x, y in zip(a, b)))


def _step_relation(previous: PageFingerprint, current: PageFingerprint) -> str:
    """'continues', 'restarts' or 'unknown' — the decisive signal at a page break."""
    before, after = previous.numeric_steps(), current.numeric_steps()
    if not before or not after:
        return "unknown"
    if after[0] <= before[-1]:
        return "restarts"
    if after[0] <= before[-1] + 2:      # allows one skipped/merged row at the break
        return "continues"
    return "unknown"


def segment(fingerprints: list[PageFingerprint]) -> list[Region]:
    """Group fingerprinted pages into table regions using only deterministic signals.

    A join is confident when the layout matches AND the step sequence or the page's own
    "(cont.)" agrees. Where they disagree — or where a page carries no step labels to
    reason about — the region is marked `confident=False` and the join recorded, so the
    caller can spend one model call on exactly that question and nothing else.
    """
    regions: list[Region] = []
    for current in fingerprints:
        if not current.is_table:
            continue
        if not regions or regions[-1].end != current.page - 1:
            regions.append(Region(current.page, current.page, current.columns,
                                  current.money_rows, reason="new table"))
            continue

        region = regions[-1]
        previous = next(f for f in fingerprints if f.page == region.end)
        layout = _layout_matches(region.columns, current.columns)
        relation = _step_relation(previous, current)

        if layout and relation == "continues":
            decision, confident, why = "join", True, "layout matches, steps continue"
        elif relation == "restarts":
            decision, confident, why = "split", True, "step sequence restarts"
        elif not layout:
            decision, confident, why = "split", True, "column layout changes"
        elif current.continues:
            # Layout matches and the page calls itself a continuation, but the steps
            # could not confirm it. Believable, not certain.
            decision, confident, why = "join", False, "layout matches, page says (cont.)"
        else:
            decision, confident, why = "split", False, "layout matches but nothing confirms it"

        if decision == "join":
            region.end = current.page
            region.rows += current.money_rows
            if not confident:
                region.confident = False
                region.joins.append({"before": previous.page, "after": current.page,
                                     "reason": why})
            region.reason = why
        else:
            new = Region(current.page, current.page, current.columns,
                         current.money_rows, confident=confident, reason=why)
            if not confident:
                new.joins.append({"before": previous.page, "after": current.page,
                                  "reason": why})
            regions.append(new)
    return regions


def split_region(region: Region, after_page: int,
                 fingerprints: list[PageFingerprint]) -> list[Region]:
    """Cut a region in two at a page break, keeping BOTH halves.

    Truncating the region instead — `region.end = after_page` — drops every page past
    the split on the floor. That silently lost Manchester's entire FY'09 schedule: the
    adjudicator correctly ruled p43 a separate table and the pipeline then emitted FY'08
    and FY'10 and nothing in between. A split must produce two regions or it is a delete.
    """
    if not region.start <= after_page < region.end:
        return [region]
    by_page = {f.page: f for f in fingerprints}

    def build(start: int, end: int) -> Region:
        rows = sum(by_page[p].money_rows for p in range(start, end + 1) if p in by_page)
        columns = by_page[start].columns if start in by_page else region.columns
        return Region(start=start, end=end, columns=columns, rows=rows,
                      confident=True, reason="split by adjudication")

    return [build(region.start, after_page), build(after_page + 1, region.end)]


def blocks_from_regions(regions: list[Region], max_block_pages: int) -> list[tuple[int, int]]:
    """Page ranges in the shape salary_schedule expects, split at its own ceiling."""
    blocks: list[tuple[int, int]] = []
    for region in regions:
        cursor = region.start
        while cursor <= region.end:
            blocks.append((cursor, min(cursor + max_block_pages - 1, region.end)))
            cursor += max_block_pages
    return blocks
