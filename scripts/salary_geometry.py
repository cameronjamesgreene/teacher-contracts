#!/usr/bin/env python3
"""Rebuild salary tables from PDF word coordinates — headers, labels and all.

## Why this is not `verify_salary_grids.reconstruct_from_geometry`

That routine keeps only money tokens, because auditing only needs to compare numbers.
Extraction needs the column headers ("BA+45", "9/1/21") and the row labels ("Step 3",
"20 D E basis") too, since those carry the economics. This module keeps every word and
returns a full matrix.

## Why geometry rather than the model

`salary_schedule.py` already calls `extract_structured_grids()`, which recovers the true
matrix from `pdfplumber.find_tables()` — and then serialises it to a pipe-table and asks
the model to retype it. 28,241 numeric cells round-trip through Qwen that way, and UTLA
p339 shows the cost: the host had the right matrix, the emitted grid duplicated the annual
column over the monthly one and pulled `20 D / B basis` from row 33D.

`find_tables()` is also a brittle gate. It needs ruled lines or fixed tolerances, and when
it fails the current fallback is not better geometry but a rendered page image: 66 of 91
vision-path pages are born-digital, including UTLA p327, where `find_tables()` returns 0
tables and the clustering here returns a 34x5 matrix.

## The two layouts that break naive clustering

**Stacked** — Cleveland p162 prints three schedules down one page. Clustering the whole
page pools them, so row *i* of one table is not row *i* of the reconstruction.

**Side-by-side** — Philadelphia p157 prints twelve pay grades in two columns, so a single
printed LINE carries a row of Pay Grade 27 and a row of Pay Grade 28.

Both are handled by splitting into regions before building a matrix: y-gaps separate
stacked tables, and a repeated header token sequence separates side-by-side panels.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

MONEY = re.compile(r"^\$?\d{1,3}(?:,\d{3})+(?:\.\d\d)?$|^\$?\d{4,}(?:\.\d\d)?$"
                   r"|^\$?\d{1,3}\.\d\d$")
COLUMN_TOLERANCE = 12       # points; columns closer than this are one column
ROW_TOLERANCE = 4           # points; words within this vertical distance share a row
BAND_GAP = 2.2              # a vertical gap this many median line-heights ends a table
MIN_ROWS, MIN_COLS = 3, 2   # below this it is prose, not a schedule


@dataclass
class Word:
    x0: float
    x1: float
    top: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


def money_in(cell: str) -> str | None:
    """The money token inside a cell, ignoring stray glyphs that share its column.

    `MONEY` is anchored, so it only matches a cell that is *nothing but* an amount.
    Rochester p146 prints a `!` rule glyph between columns and sets `$` as a detached
    token, so a cell assembles as `"$ 37,410 !"` and the anchored match fails — which
    dropped all 178 of that page's cells and the page with them. Matching per token
    inside the cell recovers every one, and needs no tuned distance constant: a cap
    tight enough to exclude the `$` (16.9pt away) works, but degrades to 91 cells at
    18pt and to 0 at 36pt, so it is the wrong lever.
    """
    for token in (cell or "").split():
        if MONEY.match(token):
            return token
    return None


# A bare 4-digit year is shaped exactly like a salary, and `MONEY` cannot tell them
# apart. Left alone it invents columns: Milwaukee p184's "2005"/"2006" produce two
# spurious centres, and corpus-wide 453 cells carry an "amount" between 1900 and 2100,
# 429 of them labelled as salary. Years are excluded from COLUMN DETECTION only — a
# genuine four-digit salary in that range is vanishingly rare, and excluding it from
# the column vote costs nothing because its neighbours define the same column.
_YEARISH = re.compile(r"^\$?(19|20)\d{2}$")


def is_year(token: str) -> bool:
    return bool(_YEARISH.match((token or "").strip()))


@dataclass
class Table:
    page_start: int
    page_end: int
    header: list[str]
    rows: list[list[str]]              # row[0] is the label, row[1:] align to header[1:]
    groups: list[str] = field(default_factory=list)   # sub-heading in force for each row
    method: str = "geometry_vector"
    note: str = ""

    @property
    def money_cells(self) -> int:
        return sum(1 for r in self.rows for c in r[1:] if money_in(c))


def page_word_state(page) -> tuple[list[Word], str]:
    """(words, reason) where reason is "ok", "no_words", or "untrusted_coords".

    The two failure modes need telling apart, because they call for different remedies.
    A page with NO WORDS is a scan, and the remedy is an engine that reads images. A page
    with UNTRUSTED COORDS has a text layer that lies: on Cleveland — the only such document
    in 42 — pdfplumber reports word tops as low as -152 on a 655pt page, and the values do
    not match what poppler renders.

    Collapsing both to `[]` hid the difference, and left Cleveland quietly emitting 17
    cells where the legacy image-reading path finds 1,353.
    """
    try:
        raw = page.extract_words()
    except Exception:
        return ([], "no_words")
    if not raw:
        return ([], "no_words")
    if any(w["top"] < -1 or w["top"] > page.height + 1 for w in raw):
        return ([], "untrusted_coords")
    return ([Word(w["x0"], w["x1"], w["top"], w["text"].strip())
             for w in raw if w["text"].strip()], "ok")


def page_words(page) -> list[Word]:
    """Every word on the page, or [] when its coordinates are not trustworthy."""
    return page_word_state(page)[0]


def group_rows(words: list[Word]) -> list[list[Word]]:
    """Words clustered into printed lines, each sorted left to right."""
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(word.top - lines[-1][0].top) <= ROW_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def split_bands(lines: list[list[Word]]) -> list[list[list[Word]]]:
    """Split lines into vertically separated bands — one per stacked table.

    A band ends at a vertical gap much larger than the page's normal line spacing, which
    is what sits between Cleveland p162's three schedules and their titles.
    """
    if not lines:
        return []
    gaps = [lines[i + 1][0].top - lines[i][0].top for i in range(len(lines) - 1)]
    typical = statistics.median([g for g in gaps if g > 0]) if any(g > 0 for g in gaps) else 12
    bands, current = [], [lines[0]]
    for index, line in enumerate(lines[1:], start=1):
        if line[0].top - lines[index - 1][0].top > typical * BAND_GAP:
            bands.append(current)
            current = [line]
        else:
            current.append(line)
    bands.append(current)
    return bands


def column_centres(lines: list[list[Word]]) -> list[float]:
    """Column x-centres, clustered from the money tokens that define the grid."""
    xs = sorted(w.cx for line in lines for w in line
                if MONEY.match(w.text) and not is_year(w.text))
    if not xs:
        return []
    centres, cluster = [], [xs[0]]
    for x in xs[1:]:
        if x - cluster[-1] <= COLUMN_TOLERANCE:
            cluster.append(x)
        else:
            centres.append(sum(cluster) / len(cluster))
            cluster = [x]
    centres.append(sum(cluster) / len(cluster))
    return centres


def _panel_bounds(centres: list[float], band: list[list[Word]]) -> list[tuple[int, int]]:
    """Column index ranges, one per side-by-side panel.

    A panel boundary is a gap between money columns that REPEATEDLY CONTAINS non-money
    text — because that is where the next panel prints its own row labels. Philadelphia
    p157 puts twelve pay grades in two columns, and the second panel's step numbers
    ("01", "02", ...) sit in the gap; without this they are absorbed into the last column
    of panel 1 as "51,189 01".

    Width alone is not a usable signal: that gap is 54pt against a 33pt median, a ratio of
    1.6 that an ordinary wide column also reaches. Occupancy by label text is specific.
    """
    if len(centres) < 4:
        return [(0, len(centres))]
    money_lines = [line for line in band
                   if sum(1 for w in line if MONEY.match(w.text) and not is_year(w.text)) >= 2]
    if not money_lines:
        return [(0, len(centres))]
    cuts = []
    for index in range(len(centres) - 1):
        lo, hi = centres[index] + COLUMN_TOLERANCE, centres[index + 1] - COLUMN_TOLERANCE
        if hi <= lo:
            continue
        occupied = sum(1 for line in money_lines
                       if any(lo < w.cx < hi and not MONEY.match(w.text) for w in line))
        if occupied >= 0.5 * len(money_lines):
            cuts.append(index + 1)
    if not cuts:
        return [(0, len(centres))]
    bounds, start = [], 0
    for cut in cuts:
        if cut - start >= 2:
            bounds.append((start, cut))
            start = cut
    bounds.append((start, len(centres)))
    return [b for b in bounds if b[1] - b[0] >= 2] or [(0, len(centres))]


def build_table(band: list[list[Word]], page_start: int, page_end: int) -> list[Table]:
    """One band of lines -> one table, or two when the band holds side-by-side panels."""
    centres = column_centres(band)
    if len(centres) < MIN_COLS:
        return []

    panels = _panel_bounds(centres, band)

    def assign(line: list[Word], lo: int, hi: int) -> tuple[str, list[str]]:
        """(row label, cells) for one panel's column range.

        The label is the text sitting to the LEFT of this panel's first money column and
        right of the previous panel's last — which is exactly where a side-by-side layout
        prints the second panel's step number.
        """
        left_edge = centres[lo] - COLUMN_TOLERANCE
        right_edge = centres[hi - 1] + COLUMN_TOLERANCE
        prior = centres[lo - 1] + COLUMN_TOLERANCE if lo > 0 else float("-inf")
        label_parts, cells = [], [""] * (hi - lo)
        for word in line:
            if prior < word.cx < left_edge:
                label_parts.append(word.text)
                continue
            if not (left_edge <= word.cx <= right_edge):
                continue
            index = min(range(lo, hi), key=lambda i: abs(centres[i] - word.cx)) - lo
            cells[index] = (cells[index] + " " + word.text).strip() if cells[index] else word.text
        return (" ".join(label_parts).strip(), cells)

    out: list[Table] = []
    for lo, hi in panels:
        scanned = [(line, *assign(line, lo, hi)) for line in band]
        scanned = [(line, label, cells, sum(1 for c in cells if money_in(c)))
                   for line, label, cells in scanned]

        # The header is the LAST money-free line before the first data row.
        #
        # A "pick the money-free line with the most column coverage, wherever it sits"
        # rule was tried and reverted. Measured corpus-wide it looked like a clear win —
        # better on 339 of 623 panels, worse on none, mean coverage 0.584 -> 0.924 — but
        # coverage is a proxy, and maximising it selects PROSE. A full-width sentence
        # spans every column by construction, so Albuquerque p72 took its header from the
        # preamble ("are one-year | documents | that reflect | placement only.") and UTLA
        # p339 took its from a footer, both displacing a correct header. The proxy improved
        # while the answer got worse, on pages whose ground truth is established by eye.
        first_data = next((i for i, (_, _, _, money) in enumerate(scanned) if money), None)
        header_at = None
        if first_data is not None:
            for index in range(first_data - 1, -1, -1):
                if scanned[index][3] == 0 and sum(1 for c in scanned[index][2] if c) >= 1:
                    header_at = index
                    break

        body: list[list[str]] = []
        groups: list[str] = []
        header_cells: list[str] = []
        current_group = ""
        for index, (_, label, cells, money) in enumerate(scanned):
            if index == header_at:
                header_cells = cells
                continue
            if money == 0:
                text = " ".join(p for p in [label, *cells] if p).strip()
                if text:
                    # Any other text-only line is a sub-heading for the rows that follow.
                    # Philadelphia p157 stacks six pay-grade groups inside one band, each
                    # introduced by "Pay Grade 29"; without this the rows are six
                    # indistinguishable repetitions of steps 01-06.
                    current_group = text
                continue
            body.append([label] + cells)
            groups.append(current_group)
        if len(body) < MIN_ROWS:
            continue
        header = ["step"] + (header_cells if header_cells else [""] * (hi - lo))
        table = Table(page_start, page_end, header, body, groups=groups,
                      note="" if len(panels) == 1 else f"side-by-side panel {len(out) + 1}")
        if table.money_cells >= 4:
            out.append(table)
    return out


def tables_on_page(page, page_number: int) -> list[Table]:
    words = page_words(page)
    if not words:
        return []
    if sum(1 for w in words if MONEY.match(w.text) and not is_year(w.text)) < 6:
        return []
    out: list[Table] = []
    for band in split_bands(group_rows(words)):
        out.extend(build_table(band, page_number, page_number))
    return out


def tables_in_document(pdf: Path) -> list[Table]:
    """Every salary-shaped table in the document, located purely by geometry."""
    try:
        import pdfplumber
    except ImportError:
        return []
    found: list[Table] = []
    try:
        with pdfplumber.open(str(pdf)) as document:
            for number, page in enumerate(document.pages, start=1):
                found.extend(tables_on_page(page, number))
    except Exception:
        return found
    return found
