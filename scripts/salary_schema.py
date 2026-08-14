#!/usr/bin/env python3
"""Target schema for salary extraction: one row per pay cell, analysis-ready.

## Why a schema at all

The current output is 431 wide CSVs carrying 131 distinct header layouts, because each
file mirrors the layout of the contract page it came from. Even at perfect cell accuracy
that is not an economic dataset - it is a faithful photocopy. Three concrete failures the
present format cannot express:

  * Albuquerque p72 prints "Matrices AT-1, AT-2 and AT-3: 184 days" above the matrix. The
    day basis never reaches the CSV, so the salaries are not comparable across districts.
  * Pittsburgh p16 carries a "Total Increase" column (9,870) beside six dated salary
    columns. Reshaped naively, a cumulative raise becomes a wage.
  * Seattle's substitute tables carry "Hourly Rate" and "Daily Rate" side by side. Both
    are pay, in different units, and nothing in the file says so.

Each is a *semantic* gap, not a transcription error. This module defines the target.

## The one column that matters most

`value_kind`. Every cell is either a pay level or something else that happened to be
printed in the table (a raise, a delta, a count). Consumers filter on
`value_kind == "salary"` and are safe by construction; nothing has to be deleted, and the
derived columns stay available for anyone who wants them.

`pay_basis` is second: annual / monthly / daily / hourly are not interchangeable, and the
corpus mixes them within a single document.

## Division of labour

Everything here is derivable WITHOUT a model except `employee_group`, `lane_type`,
`pay_basis`, `step_kind` and `days_per_year` - five small, low-cardinality judgements per
grid. See scripts/salary_pipeline.md for how those are obtained in one short call per
page, and why the numbers themselves never travel to the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

# ── controlled vocabularies ──────────────────────────────────────────────────────
# Free text gave three spellings of one group ("certified teachers", "Teachers",
# "Certified teachers"). A closed list is also what makes the model's job checkable: an
# answer outside the list is a validation failure, not a new category.
EMPLOYEE_GROUPS = (
    "teacher", "substitute_teacher", "paraprofessional", "counselor", "librarian",
    "nurse", "social_worker", "psychologist", "therapist", "interpreter",
    "administrator", "clerical", "technical", "custodial", "food_service", "other",
)
PAY_BASES = ("annual", "monthly", "biweekly", "daily", "hourly", "per_session", "stipend")
VALUE_KINDS = ("salary", "increment", "increase_delta", "differential", "unknown")
LANE_TYPES = ("education", "effective_date", "pay_grade", "tier", "basis", "none")
STEP_KINDS = ("experience_step", "grade_step", "day_range", "class_code",
              "basis_label", "longevity", "none")

_DEGREE = re.compile(r"\b(ph\.?d|doctor(ate)?|ed\.?d|m\.?a|m\.?s|masters?|b\.?a|b\.?s|"
                     r"bachelors?)\b", re.I)
_CREDITS = re.compile(r"\+\s*(\d{1,3})")
_STEP_NUM = re.compile(r"^\s*(\d{1,2})\s*[-.]?\s*$")
_GRADE_STEP = re.compile(r"pay\s*grade\s*(\d+)\s*step\s*(\d+)", re.I)
_DAY_RANGE = re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*days?", re.I)


@dataclass
class PayCell:
    """One observation: what a named group earns at one lane/step on one date."""

    # provenance - every row traces to a page and a reconstruction
    document_id: str
    district: str
    state: str
    source_pdf: str
    page_start: int
    page_end: int
    grid_id: str
    extraction_method: str          # geometry_vector | geometry_ocr | vision_fallback
    cell_verified: bool             # agreed with an independent reading of the page
    cell_agreement: float | None

    # what schedule this is
    schedule_title: str
    employee_group: str             # EMPLOYEE_GROUPS
    is_teacher: bool
    contract_year_start: int | None
    contract_year_end: int | None
    effective_date: str | None      # ISO; from a dated column header, else contract start

    # where in the schedule
    lane_raw: str                   # verbatim column header, always kept
    lane_type: str                  # LANE_TYPES
    degree: str | None              # BA | MA | PHD | None
    education_credits: int | None   # BA+45 -> 45
    step_raw: str                   # verbatim row label, always kept
    step_kind: str                  # STEP_KINDS
    step_number: int | None

    # the number
    amount: float
    pay_basis: str                  # PAY_BASES
    value_kind: str                 # VALUE_KINDS
    days_per_year: int | None       # from page prose ("Matrices AT-1...: 184 days")
    fte: float | None = None
    notes: str = ""

    def as_row(self) -> dict:
        return asdict(self)


# ── deterministic parsers: everything a model must NOT be asked for ──────────────

def parse_lane(header: str) -> tuple[str | None, int | None]:
    """'BA+45' -> ('BA', 45); 'Doctorate' -> ('PHD', None); '9/1/21' -> (None, None)."""
    if not header:
        return (None, None)
    degree = None
    found = _DEGREE.search(header)
    if found:
        token = found.group(1).lower().replace(".", "")
        if token.startswith(("phd", "doctor", "edd")):
            degree = "PHD"
        elif token.startswith(("ma", "ms", "master")):
            degree = "MA"
        elif token.startswith(("ba", "bs", "bachelor")):
            degree = "BA"
    credits = _CREDITS.search(header)
    return (degree, int(credits.group(1)) if credits else None)


def parse_step(label: str) -> tuple[str, int | None]:
    """Classify a row label and pull its number where one exists.

    The current output overloads this single column with step numbers ('1'), pay bases
    ('ANNUAL'), day ranges ('1-59 Days'), class codes ('SU3'), composites ('Pay Grade 27
    Step 01', '20 D E basis') and artifacts ('1-'). Splitting kind from number is what
    lets a consumer select experience steps without hand-written per-district rules.
    """
    text = (label or "").strip()
    if not text:
        return ("none", None)
    grade = _GRADE_STEP.search(text)
    if grade:
        return ("grade_step", int(grade.group(2)))
    if _DAY_RANGE.search(text):
        return ("day_range", None)
    plain = _STEP_NUM.match(text)
    if plain:
        return ("experience_step", int(plain.group(1)))
    if re.search(r"\bbasis\b", text, re.I):
        return ("basis_label", None)
    if re.search(r"\blongevity\b|\bcareer increment\b", text, re.I):
        return ("longevity", None)
    if re.match(r"^[A-Z]{1,3}\d", text):
        return ("class_code", None)
    leading = re.match(r"^\s*(\d{1,2})\b", text)
    return ("experience_step", int(leading.group(1))) if leading else ("class_code", None)


def classify_value(header: str, step_label: str) -> tuple[str, str | None]:
    """(value_kind, pay_basis_hint) from the column header alone.

    'Total Increase' is the case that matters: a cumulative raise printed beside six
    dated salary columns. It is real data and worth keeping, but it is not a wage, and a
    consumer filtering `value_kind == "salary"` must not receive it.
    """
    text = f"{header} {step_label}".lower()
    if re.search(r"total increase|increase|raise|adjustment|\bdelta\b|% ?incr", text):
        return ("increase_delta", None)
    if re.search(r"increment", text):
        return ("increment", None)
    if re.search(r"differential|stipend|supplement", text):
        return ("differential", "stipend")
    if re.search(r"hourly|per hour|/hr", text):
        return ("salary", "hourly")
    if re.search(r"daily|per diem|per day", text):
        return ("salary", "daily")
    if re.search(r"monthly|per month", text):
        return ("salary", "monthly")
    if re.search(r"annual|yearly|per year", text):
        return ("salary", "annual")
    return ("salary", None)


_DATE_HEADER = re.compile(
    r"^\s*(?:(\d{1,2})/(\d{1,2})/(\d{2,4})"                      # 9/1/21
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})"  # September 2011
    r"|(\d{4})\s*[-–]\s*(\d{2,4}))\s*$", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def parse_effective_date(header: str) -> str | None:
    """A dated column header -> ISO date. 72 grids use dates as lane headers and 35 use
    degree lanes; telling them apart is the corpus's central column ambiguity."""
    found = _DATE_HEADER.match(header or "")
    if not found:
        return None
    if found.group(1):
        month, day, year = int(found.group(1)), int(found.group(2)), int(found.group(3))
        year += 2000 if year < 100 else 0
        return f"{year:04d}-{month:02d}-{day:02d}"
    if found.group(4):
        return f"{int(found.group(5)):04d}-{_MONTHS[found.group(4)[:3].lower()]:02d}-01"
    return f"{int(found.group(6)):04d}-07-01"


def infer_lane_type(header: str) -> str:
    """Deterministic where it can be: dates and degree lanes are unambiguous. Anything
    else is left for the one small model call, which is the only place judgement is
    genuinely required."""
    if parse_effective_date(header):
        return "effective_date"
    degree, credits = parse_lane(header)
    if degree or credits is not None:
        return "education"
    if re.search(r"pay\s*grade|grade\s*\d", header or "", re.I):
        return "pay_grade"
    if re.search(r"\bbasis\b", header or "", re.I):
        return "basis"
    return "none"


DAYS_IN_PROSE = re.compile(
    r"(\d{3})\s*days?\b|\bbased on\s+(\d{3})\s*(?:work)?days?", re.I)


def days_from_prose(page_text: str, schedule_label: str = "") -> int | None:
    """'Matrices AT-1, AT-2 and AT-3: 184 days' -> 184.

    Prefers a sentence naming this schedule, because one page can state different day
    counts for different matrices - Albuquerque p72 gives 184 for AT-1/2/3, 184 for A-2
    and 194 for A-3/4.
    """
    if not page_text:
        return None
    lines = [ln for ln in page_text.splitlines() if DAYS_IN_PROSE.search(ln)]
    if schedule_label:
        token = schedule_label.strip().split()[-1].lower() if schedule_label.strip() else ""
        for line in lines:
            if token and token in line.lower():
                hit = DAYS_IN_PROSE.search(line)
                return int(hit.group(1) or hit.group(2))
    if lines:
        hit = DAYS_IN_PROSE.search(lines[0])
        return int(hit.group(1) or hit.group(2))
    return None
