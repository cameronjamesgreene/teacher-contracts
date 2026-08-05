#!/usr/bin/env python3
"""Reconcile several OCR engines into one text, page by page, with provenance.

## Why this is arbitration and not voting

Majority voting is the obvious multi-engine design and it does not work here. Measured on
four hard pages of a scanned contract, pairwise agreement on the *figures* each engine
reports is 0.12–0.34 (Jaccard). Three engines therefore disagree three ways and there is no
majority to find. Worse, the correct values were found by exactly one engine: only Apple
Vision reported `195` and `202`, olmOCR-2 reported the corrupted `135` and `132`, and docling
and GLM-OCR reported neither. A vote would have discarded the only correct reading.

So engines are arbitrated by *measured reliability on a verified sample*, and disagreement is
surfaced rather than resolved by counting.

## What each engine is good for, measured

| engine | verified figures | figures found | loops | hallucinations | prose |
| --- | --- | --- | --- | --- | --- |
| Apple Vision | **3 of 3** | 229 | none | none | letter errors ("eftective") |
| olmOCR-2 | 0 of 3 | 246 | on some pages | yes | clean |
| docling | 0 of 3 | 178 | none | none | clean |
| GLM-OCR | 0 of 3 | 8 | severe | none | table fragments only |
| DeepSeek-OCR-2 | — | — | — | — | empty output |

The failures are complementary in a useful way: the deterministic engine is right about
numbers and wrong about letters, the vision model is the reverse. Numbers are what this
codebook asks for, so numbers win ties.

## The rule

Per page, in order:

1. Drop any engine whose page fails the degeneracy gate (repetition loop, duplicated lines,
   absurd length, or a URL in a contract scan).
2. If one engine survives, use it.
3. If several survive, compare their figure sets. When they agree closely, prefer the engine
   ranked best for *prose*, because both readings of the numbers are then equivalent and
   prose quality is the remaining difference. When they disagree, prefer the engine ranked
   best for *figures* and mark the page `figures_disputed`.

Every page records which engine it came from and why, so a downstream numeric answer can be
traced to an arbitration decision rather than silently inheriting one.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_quality_gate import degeneracy, pages_of
from utils import WORK

# Both orders are measured, not assumed; see the table above.
FIGURE_RANK = ["apple_vision", "olmocr2", "docling", "glm_ocr"]
PROSE_RANK = ["olmocr2", "docling", "apple_vision", "glm_ocr"]
AGREEMENT_OK = 0.75
MAX_DEGENERATE_SHARE = 0.5   # an engine failing the gate on most pages is refused outright
_FIGURE = re.compile(r"\d[\d,]*\.?\d*")


def figures(text: str) -> set[str]:
    return {value.rstrip(".").replace(",", "") for value in _FIGURE.findall(text)}


def agreement(a: str, b: str) -> float:
    first, second = figures(a), figures(b)
    if not first and not second:
        return 1.0
    return len(first & second) / max(1, len(first | second))


def rank_of(engine: str, order: list[str]) -> int:
    return order.index(engine) if engine in order else len(order)


def reconcile(sources: dict[str, list[str]]) -> tuple[list[str], list[dict]]:
    """sources: engine -> page list. Returns reconciled pages and a provenance row each."""
    flagged: dict[str, set[int]] = {}
    fabricated: dict[str, set[int]] = {}
    for engine, pages in sources.items():
        flags = degeneracy(pages)
        flagged[engine] = {flag["page"] for flag in flags}
        # A page carrying fabricated content is never usable, whatever else is available:
        # an empty page is a correct reading of a blank page, an invented URL is not.
        fabricated[engine] = {flag["page"] for flag in flags
                              if any("HALLUCINATION" in reason for reason in flag["reasons"])}
    length = max(len(pages) for pages in sources.values())
    reconciled: list[str] = []
    provenance: list[dict] = []
    for number in range(1, length + 1):
        available = {engine: pages[number - 1]
                     for engine, pages in sources.items()
                     if number <= len(pages) and pages[number - 1].strip()
                     and number not in fabricated[engine]}
        clean = {engine: text for engine, text in available.items()
                 if number not in flagged[engine]}
        pool = clean or available          # every engine degenerate: keep the best-ranked
        note = "" if clean else "all engines flagged; kept best-ranked"
        if not pool:
            # Legitimately blank, or every engine fabricated. Empty is the honest output.
            reconciled.append("")
            provenance.append({"page": number, "engine": "", "agreement": "",
                               "reason": "no usable text; blank page or all engines fabricated",
                               "disputed": 0, "dropped": ";".join(sorted(
                                   e for e in sources if number in fabricated[e]))})
            continue
        if len(pool) == 1:
            engine = next(iter(pool))
            reason = note or "only surviving engine"
            disputed = 0
            score = ""
        else:
            best_figures = min(pool, key=lambda e: rank_of(e, FIGURE_RANK))
            best_prose = min(pool, key=lambda e: rank_of(e, PROSE_RANK))
            score = round(agreement(pool[best_figures], pool[best_prose]), 3)
            if score >= AGREEMENT_OK:
                engine, disputed = best_prose, 0
                reason = note or f"figures agree ({score}); prose-preferred engine"
            else:
                engine, disputed = best_figures, 1
                reason = note or f"figures disagree ({score}); figure-preferred engine"
        reconciled.append(pool[engine])
        provenance.append({"page": number, "engine": engine, "reason": reason,
                           "agreement": score, "disputed": disputed,
                           "dropped": ";".join(sorted(set(available) - set(pool)))})
    return reconciled, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True,
                        metavar="ENGINE=PATH", help="repeatable, e.g. olmocr2=/path/doc.md")
    parser.add_argument("--out", type=Path, required=True, help="reconciled page-delimited text")
    parser.add_argument("--provenance", type=Path, help="per-page arbitration record as CSV")
    args = parser.parse_args()

    sources: dict[str, list[str]] = {}
    for item in args.source:
        engine, _, path = item.partition("=")
        file = Path(path)
        if not file.exists():
            print(f"  skipping missing {engine}={file}")
            continue
        sources[engine] = pages_of(file)
    if not sources:
        raise SystemExit("no usable sources")
    expected = max(len(pages) for pages in sources.values())
    for engine in list(sources):
        pages = sources[engine]
        # docling-serve returns one markdown blob per document with no page markers, so its
        # output cannot be aligned to PDF pages. Silently mixing it in would misattribute
        # every citation page, so it is refused rather than accepted.
        if expected > 1 and len(pages) < expected / 2:
            print(f"  {engine:14s} REFUSED: {len(pages)} block(s) for a {expected}-page "
                  f"document; output is not page-delimited")
            del sources[engine]
            continue
        # Document-level gate on the engine itself. An engine that degenerates on most of
        # its pages is not a usable fallback anywhere: letting it supply the one page the
        # others could not is how the worst reading in the set ends up in the output.
        bad = len(degeneracy(pages))
        share = bad / max(1, sum(1 for page in pages if page.strip()))
        if share > MAX_DEGENERATE_SHARE:
            print(f"  {engine:14s} REFUSED: {bad} of {len(pages)} pages degenerate "
                  f"({share:.0%}); engine is unreliable on this document")
            del sources[engine]
            continue
        print(f"  {engine:14s} {len(pages):>4} pages, {bad} degenerate")

    reconciled, provenance = reconcile(sources)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\f".join(reconciled), encoding="utf-8")

    chosen: dict[str, int] = {}
    for row in provenance:
        chosen[row["engine"] or "(none)"] = chosen.get(row["engine"] or "(none)", 0) + 1
    disputed = sum(row["disputed"] for row in provenance)
    print(f"\n{len(reconciled)} pages reconciled -> {args.out}")
    print("  pages taken from: " + ", ".join(f"{k}={v}" for k, v in sorted(chosen.items())))
    print(f"  figures disputed on {disputed} page(s) — numeric answers citing these need a check")
    if args.provenance:
        args.provenance.parent.mkdir(parents=True, exist_ok=True)
        with args.provenance.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=list(provenance[0]))
            writer.writeheader()
            writer.writerows(provenance)
        print(f"  provenance -> {args.provenance}")


if __name__ == "__main__":
    main()
