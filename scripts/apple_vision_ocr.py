#!/usr/bin/env python3
"""Local AI OCR benchmark: Apple's on-device Vision neural OCR (via ocrmac).

Runs an INDEPENDENT second OCR engine on the same 3 documents the HPC docling
("SOM program") OCR'd, so docling's output can be scored against a different
modern AI OCR. Renders each page (pdftoppm 300dpi), OCRs with Apple Vision
(accurate mode), caches per page (resumable), and writes a form-feed-delimited
text file to cache/apple_vision_ocr/<document_id>.txt.

This is a benchmark/comparison engine only -- it is NOT the pipeline's OCR of
record (that's docling on the HPC).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from ocrmac import ocrmac

WORK = Path(__file__).resolve().parents[1]
STAGE = WORK / "cache" / "ocr_documents"
DOCS = STAGE / "documents"
OUT = WORK / "cache" / "apple_vision_ocr"
PAGE_CACHE = WORK / "cache" / "apple_vision_cache"


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def ocr_page(png: Path) -> str:
    # Vision origin is bottom-left; sort y descending (top first), then x ascending.
    ann = ocrmac.OCR(str(png), recognition_level="accurate").recognize()
    ann.sort(key=lambda a: (-round(a[2][1], 2), a[2][0]))
    return "\n".join(a[0] for a in ann)


def main() -> None:
    uuid_map = json.loads((STAGE / "uuid_to_document_id.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for u, did in uuid_map.items():
        pdf = DOCS / u / "document.pdf"
        if not pdf.exists() or pdf.stat().st_size == 0:
            continue
        n = page_count(pdf)
        cache = PAGE_CACHE / did
        cache.mkdir(parents=True, exist_ok=True)
        print(f"[{did}] {n} pages", flush=True)
        t0 = time.time()
        for i in range(1, n + 1):
            pc = cache / f"p{i:04d}.txt"
            if pc.exists():
                continue
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(
                    ["pdftoppm", "-png", "-r", "300", "-f", str(i), "-l", str(i),
                     str(pdf), str(Path(td) / "p")],
                    check=True,
                )
                pngs = sorted(Path(td).glob("p*.png"))
                pc.write_text(ocr_page(pngs[0]) if pngs else "", encoding="utf-8")
            if i % 25 == 0 or i == n:
                print(f"   {i}/{n}  ({(time.time() - t0) / i:.2f}s/pg)", flush=True)
        pages = [(cache / f"p{i:04d}.txt").read_text(encoding="utf-8", errors="ignore")
                 for i in range(1, n + 1)]
        (OUT / f"{did}.txt").write_text("\f".join(pages), encoding="utf-8")
        print(f"   -> {OUT / (did + '.txt')}", flush=True)


if __name__ == "__main__":
    main()
