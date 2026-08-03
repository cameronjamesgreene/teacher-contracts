#!/usr/bin/env python3
"""Splice HPC docling (ocr-examples) OCR output into the pipeline's override slot.

Reads cache/ocr_documents/documents/<uuid>/ocr/<engine>.txt (produced by the
yale-som-hpc/ocr-examples workflow), strips docling's embedded base64 image
data-URIs -- which bloat the file ~10x but carry no text -- and writes the
cleaned markdown to cache/ocr_text/<document_id>.txt, the OCR override slot that
utils.extract_text() prefers. All three pipelines then read the OCR text with no
further change.

Usage:
  python3 splice_ocr.py                 # every staged doc that has OCR output
  python3 splice_ocr.py --uuid <uuid>   # one doc (repeatable)
  python3 splice_ocr.py --engine olmocr2   # splice a different engine's output
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
STAGE = WORK / "cache" / "ocr_documents"
DOCS = STAGE / "documents"
OCR_TEXT_DIR = WORK / "cache" / "ocr_text"

# docling embeds page figures/logos as ![...](data:image/...;base64,....)
IMG_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^)]*\)")
# olmocr2 delimits pages with "<!-- page N -->" markers, but the coding scripts were
# built for pdftotext output, which delimits pages with form-feeds (\f). Without this
# conversion the whole document reads as ONE page, so rights_score.exclude_appendices
# collapses it to empty and salary_schedule's page-block logic can't locate grids.
PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+\d+\s*-->[ \t]*\n?")


def strip_images(md: str) -> str:
    md = IMG_RE.sub("", md)
    md = PAGE_MARKER_RE.sub("\f", md)  # page markers -> form-feeds for page-based coders
    md = re.sub(r"\n{3,}", "\n\n", md)  # collapse blank lines left behind
    return md.strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uuid", action="append", help="Specific staged UUID (repeatable)")
    ap.add_argument("--engine", default="olmocr2",
                    help="Which engine's output to splice (olmocr2 is the OCR of record; "
                         "docling only for its salary-table structure)")
    args = ap.parse_args()

    uuid_map = json.loads((STAGE / "uuid_to_document_id.json").read_text(encoding="utf-8"))
    targets = args.uuid or list(uuid_map.keys())
    OCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    for u in targets:
        document_id = uuid_map.get(u)
        if not document_id:
            print(f"  ?  unknown uuid {u}")
            continue
        src = DOCS / u / "ocr" / f"{args.engine}.txt"
        if not src.exists():
            print(f"  -  {document_id}: no {args.engine}.txt yet (skip)")
            continue
        raw = src.read_text(encoding="utf-8", errors="ignore")
        cleaned = strip_images(raw)
        out = OCR_TEXT_DIR / f"{document_id}.txt"
        out.write_text(cleaned, encoding="utf-8")
        nonspace = len(re.sub(r"\s+", "", cleaned))
        imgs = raw.count("data:image")
        print(f"  ok {document_id}")
        print(f"       {len(raw):,} raw -> {len(cleaned):,} chars ({nonspace:,} non-space); "
              f"stripped {imgs} embedded image(s) -> {out.name}")


if __name__ == "__main__":
    main()
