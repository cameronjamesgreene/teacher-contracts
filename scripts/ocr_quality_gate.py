#!/usr/bin/env python3
"""Detect OCR output that has degenerated, and cross-check figures between engines.

Vision-language OCR fails in ways classical OCR does not. Rather than misreading a glyph it
*reconstructs* the page, so on a hard layout it will smooth, transpose, loop, or invent. The
literature puts this plainly: generative OCR shifts the core risk from misrecognition to
hallucination, and hallucinated text is fluent, so it evades every spell-check-shaped
defence.

Measured on four pages of one scanned contract whose contents were verified against the PDF
by hand — a rotated salary schedule, a footnote with day counts, a page that sent one model
into a repetition loop, and a blank page:

| engine | verified figures | corrupted | hallucinations | zlib ratio |
| --- | --- | --- | --- | --- |
| olmOCR-2 | 0 of 3 | 3 of 3 | 2 | 0.156 |
| GLM-OCR | 0 of 3 | 0 of 3 | 0 | 0.018 |
| DeepSeek-OCR-2 | — | — | — | empty output |
| Apple Vision | **3 of 3** | 0 | 0 | 0.383 |

Two independent checks come out of that, and both are cheap.

**Degeneracy.** A repetition loop compresses far better than prose. GLM-OCR's output on these
pages has a zlib ratio of 0.018 against Apple Vision's 0.383 — a twenty-fold difference, not
a marginal one — and only 44% of its lines are distinct. Either signal catches a loop without
a reference text, and would have flagged the GLM run automatically.

**Numeric disagreement between engines.** No single-engine check can catch a confabulated
figure, because the output is internally consistent: a fabricated image URL passes a
verbatim-quote audit perfectly. Two engines reading the same page disagreeing about a number
is the only cheap signal available, and it is a strong one — the point is not which engine is
right but that a human should look.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import WORK

# Thresholds are set from the table above with margin, not tuned on a held-out set; they are
# meant to catch catastrophes, not to grade quality.
LOOP_RATIO = 0.10          # below this, output is compressing like a repeated string
MIN_DISTINCT_LINES = 0.60  # below this, most lines are duplicates
LENGTH_MULTIPLE = 2.5      # a page this many times the median length is suspect
_URL = re.compile(r"!\[[^\]]*\]\(https?://|\bimgur\b|\bexample\.com\b")
_FIGURE = re.compile(r"\d[\d,]*\.?\d*%?")


def pages_of(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "<!-- page" in text:
        return re.split(r"<!--\s*page\s+\d+\s*-->", text)[1:]
    return text.split("\f")


def degeneracy(pages: list[str]) -> list[dict]:
    """Flag pages that look generated rather than transcribed."""
    lengths = sorted(len(page) for page in pages if page.strip())
    median = lengths[len(lengths) // 2] if lengths else 0
    flags: list[dict] = []
    for number, page in enumerate(pages, start=1):
        body = page.strip()
        if not body:
            continue
        lines = [line.strip() for line in body.splitlines() if len(line.strip()) > 3]
        distinct = len(set(lines)) / len(lines) if lines else 1.0
        ratio = len(zlib.compress(body.encode())) / max(1, len(body))
        reasons = []
        if ratio < LOOP_RATIO:
            reasons.append(f"compresses to {ratio:.3f} of its size, a repetition loop")
        if distinct < MIN_DISTINCT_LINES:
            reasons.append(f"only {distinct:.0%} of lines are distinct")
        if median and len(body) > median * LENGTH_MULTIPLE:
            reasons.append(f"{len(body) // max(1, median)}x the median page length")
        if _URL.search(body):
            # Marked distinctly: fabricated content is disqualifying, not merely suspect.
            reasons.append("HALLUCINATION: contains a URL or image reference, "
                           "which a contract scan should not")
        if reasons:
            flags.append({"page": number, "chars": len(body),
                          "zlib_ratio": round(ratio, 4),
                          "distinct_lines": round(distinct, 3),
                          "reasons": reasons})
    return flags


def figure_disagreement(a_pages: list[str], b_pages: list[str],
                        label_a: str, label_b: str) -> list[dict]:
    """Per page, figures one engine reports and the other does not.

    Not a correctness judgement. Either engine may be right; a disagreement means the page
    needs a human eye before any number from it is coded.
    """
    rows: list[dict] = []
    for number in range(1, min(len(a_pages), len(b_pages)) + 1):
        a_figures = {f.rstrip("%") for f in _FIGURE.findall(a_pages[number - 1])}
        b_figures = {f.rstrip("%") for f in _FIGURE.findall(b_pages[number - 1])}
        if not a_figures and not b_figures:
            continue
        only_a = sorted(a_figures - b_figures)
        only_b = sorted(b_figures - a_figures)
        shared = len(a_figures & b_figures)
        union = len(a_figures | b_figures) or 1
        rows.append({"page": number, "agreement": round(shared / union, 3),
                     f"only_{label_a}": only_a[:8], f"only_{label_b}": only_b[:8],
                     "shared": shared})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", type=Path, help="extracted text or OCR markdown to check")
    parser.add_argument("--compare", type=Path,
                        help="a second engine's output for the same document")
    parser.add_argument("--label", default="a")
    parser.add_argument("--compare-label", default="b")
    parser.add_argument("--min-agreement", type=float, default=0.7,
                        help="report pages below this figure agreement")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    pages = pages_of(args.text)
    flags = degeneracy(pages)
    print(f"{args.text.name}: {len(pages)} pages, {len(flags)} flagged as degenerate")
    for flag in flags[:12]:
        print(f"  page {flag['page']:>4}  {flag['chars']:>7,} chars  "
              f"zlib {flag['zlib_ratio']:.3f}  distinct {flag['distinct_lines']:.2f}")
        for reason in flag["reasons"]:
            print(f"      - {reason}")

    report = {"text": str(args.text), "pages": len(pages), "degenerate": flags}
    if args.compare:
        other = pages_of(args.compare)
        rows = figure_disagreement(pages, other, args.label, args.compare_label)
        low = [row for row in rows if row["agreement"] < args.min_agreement]
        print(f"\nfigure agreement with {args.compare.name}: "
              f"{len(rows) - len(low)}/{len(rows)} pages at or above {args.min_agreement}")
        for row in sorted(low, key=lambda item: item["agreement"])[:12]:
            print(f"  page {row['page']:>4}  agreement {row['agreement']:.2f}  "
                  f"only {args.label}: {row[f'only_{args.label}'][:5]}  "
                  f"only {args.compare_label}: {row[f'only_{args.compare_label}'][:5]}")
        report["figure_disagreement"] = low
        report["pages_compared"] = len(rows)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
