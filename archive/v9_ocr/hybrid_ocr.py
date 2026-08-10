#!/usr/bin/env python3
"""Per-page OCR for HYBRID documents (mostly born-digital text + a few scanned pages).

The pipeline's built-in OCR gate (utils.load_documents' text_status) is a
WHOLE-DOCUMENT test: total_chars < max(1000, pages*20). A document that is, say,
98% real text and 2% image-only pages has a huge overall character count, so it is
scored "text-native", OCR is skipped, and pdftotext returns BLANK for the scanned
pages -- that content is silently lost.

This tool works at the PAGE level:
  1. detect -- run `pdftotext -layout` page-by-page, flag pages whose text is below
     a small threshold as scanned/image-only.
  2. build  -- extract ONLY those pages into a mini-PDF, OCR just them with olmocr2
     (the engine of record), then MERGE: native `pdftotext -layout` for the text
     pages + OCR text for the scanned pages, in page order, form-feed separated.
     The result is written to the OCR override slot
     (cache/ocr_text/<document_id>.txt) that utils.extract_text() reads, so all three
     coders get a complete text layer with zero per-program change. Text pages keep
     their 100%-accurate native text; only the scanned pages are OCR'd.

Usage (run on the HPC, where olmocr2 runs):
  python3 hybrid_ocr.py detect --doc "District Name|File.pdf"
  python3 hybrid_ocr.py build  --doc "District Name|File.pdf" [--min-chars 50]

`build` needs the same olmocr2 setup the full-doc OCR uses (ocr-examples repo at
$OCR_EXAMPLES, HPC_USER, on the Yale VPN).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from utils import OCR_TEXT_DIR, PDF_ROOT, ROOT, TEXT_DIR, slugify

WORK = Path(__file__).resolve().parents[1]
HYB_ROOT = WORK / "cache" / "hybrid_ocr"
DEFAULT_MIN_CHARS = 50  # a page with fewer non-space chars is treated as scanned/blank
IMG_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^)]*\)")           # olmocr2 embedded images
PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+\d+\s*-->[ \t]*\n?")   # olmocr2 page delimiter
OCR_EXAMPLES = Path(os.environ.get("OCR_EXAMPLES", str(Path.home() / "ocr-examples")))


def document_id_for(district: str, file_name: str) -> str:
    """Identical formula to salary_schedule.document_id_for / utils.load_documents."""
    path = PDF_ROOT / district / file_name
    doc_hash = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:8]
    return f"{slugify(district, 45)}__{slugify(Path(file_name).stem, 55)}__{doc_hash}"


def nonspace(s: str) -> int:
    return len(re.sub(r"\s+", "", s or ""))


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def native_pages(pdf: Path, n: int) -> list[str]:
    """`pdftotext -layout` for each page 1..n (matches utils.extract_text's extractor),
    with the trailing form-feed stripped so pages can be re-joined cleanly."""
    pages = []
    for i in range(1, n + 1):
        r = subprocess.run(
            ["pdftotext", "-layout", "-f", str(i), "-l", str(i), str(pdf), "-"],
            capture_output=True, text=True,
        )
        pages.append(r.stdout.replace("\f", "").rstrip() + "\n")
    return pages


def scanned_indices(pages: list[str], min_chars: int) -> list[int]:
    return [i for i, t in enumerate(pages) if nonspace(t) < min_chars]


def parse_olmocr_pages(raw: str) -> list[str]:
    """Split olmocr2 output into per-page texts on its `<!-- page N -->` markers,
    stripping embedded base64 images. Returns pages in order."""
    raw = IMG_RE.sub("", raw)
    parts = PAGE_MARKER_RE.split(raw)
    # split() yields a leading fragment before the first marker (usually empty).
    # Scrub stray form-feeds inside OCR text (mirrors native_pages) so a page's text can
    # never introduce a spurious \f boundary in the merged override.
    pages = [p.replace("\f", "").strip() for p in parts]
    if pages and not pages[0]:
        pages = pages[1:]
    return pages


def merge_override(native: list[str], scanned: list[int], ocr_pages: list[str]) -> str:
    """Merge native text (text pages) + OCR text (scanned pages) into one form-feed
    separated override with EXACTLY len(native) pages, in original page order.

    Raises ValueError if olmocr2 did not return exactly one page per scanned page --
    positional alignment would otherwise silently misplace or drop pages.
    """
    if len(ocr_pages) != len(scanned):
        raise ValueError(
            f"olmocr2 returned {len(ocr_pages)} page(s) for {len(scanned)} scanned page(s)"
        )
    merged = list(native)
    for k, i in enumerate(scanned):
        ocr = ocr_pages[k].replace("\f", "").strip()
        # Use OCR only when it recovers substantially more text than pdftotext did, so a
        # sparse-but-legitimate born-digital page (logo + a short caption) keeps its exact
        # 100%-accurate native text instead of a fallible OCR re-reading.
        if nonspace(ocr) > nonspace(native[i]) + 20:
            merged[i] = ocr + "\n"
    # NO str.strip() on the joined result: form-feed is whitespace, and stripping an empty
    # leading/trailing page would delete a separator and drop a page. Keep len(native)
    # segments exactly, so downstream text.split("\f") always yields the true page count.
    return "\f".join(m.rstrip() for m in merged) + "\n"


def detect(district: str, file_name: str, min_chars: int) -> dict:
    pdf = PDF_ROOT / district / file_name
    if not pdf.exists() or pdf.stat().st_size == 0:
        raise SystemExit(f"PDF missing or 0-byte placeholder: {pdf} — hydrate it first")
    n = page_count(pdf)
    pages = native_pages(pdf, n)
    scanned = scanned_indices(pages, min_chars)
    return {
        "pages": n,
        "scanned_pages_1indexed": [i + 1 for i in scanned],
        "scanned_count": len(scanned),
        "native_pages": pages,
        "verdict": (
            "text-native (no OCR needed)" if not scanned
            else "fully scanned (whole-doc OCR)" if len(scanned) == n
            else f"HYBRID: {len(scanned)}/{n} pages need OCR"
        ),
    }


def run_olmocr(mini_pdf: Path, document_id: str) -> str:
    """OCR the mini-PDF (scanned pages only) with olmocr2 on the HPC; return raw output."""
    stage = HYB_ROOT / document_id
    docs = stage / "documents"
    u = str(uuid.uuid5(uuid.NAMESPACE_URL, document_id + "__hybrid_mini"))
    dest = docs / u / "document.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mini_pdf, dest)
    ids_file = stage / "document-ids.txt"
    ids_file.write_text(u + "\n", encoding="utf-8")

    env = dict(os.environ)
    env.setdefault("HPC_LAUNCH_TIMEOUT_S", "3600")
    cmd = [
        "uv", "run", "--script", str(OCR_EXAMPLES / "scripts" / "documents_process.py"),
        "--from-file", str(ids_file), "--documents-root", str(docs),
        "--stages", "ocr", "--engines", "olmocr2", "--use-hpc",
        "--hpc-workers", "olmocr2=1", "--hpc-in-flight", "olmocr2=8",
    ]
    print(f"  OCR-ing {mini_pdf.name} ({len(PdfReader(str(mini_pdf)).pages)} pages) with olmocr2 ...")
    subprocess.run(cmd, cwd=str(OCR_EXAMPLES), env=env, check=True)
    out = docs / u / "ocr" / "olmocr2.txt"
    if not out.exists():
        raise SystemExit(f"olmocr2 produced no output at {out}")
    return out.read_text(encoding="utf-8", errors="ignore")


def build(district: str, file_name: str, min_chars: int) -> None:
    info = detect(district, file_name, min_chars)
    document_id = document_id_for(district, file_name)
    n, scanned = info["pages"], [i - 1 for i in info["scanned_pages_1indexed"]]
    native = info["native_pages"]
    print(f"{file_name}: {n} pages — {info['verdict']}")

    if not scanned:
        print("  Nothing to OCR; the coders read the native text directly. No override written.")
        return

    # Extract the scanned pages into a mini-PDF, OCR only those.
    HYB_ROOT.mkdir(parents=True, exist_ok=True)
    mini = HYB_ROOT / f"{document_id}__scanned.pdf"
    reader = PdfReader(str(PDF_ROOT / district / file_name))
    writer = PdfWriter()
    for i in scanned:
        writer.add_page(reader.pages[i])
    with open(mini, "wb") as fh:
        writer.write(fh)

    raw = run_olmocr(mini, document_id)
    ocr_pages = parse_olmocr_pages(raw)
    try:
        override = merge_override(native, scanned, ocr_pages)
    except ValueError as e:
        raise SystemExit(
            f"  ABORT: {e}; cannot align OCR pages safely, so NO override was written "
            f"(better than a silently misaligned one). Re-OCR the whole document instead "
            f"(stage_for_ocr.py + splice_ocr.py) for {file_name}."
        )

    OCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    out = OCR_TEXT_DIR / f"{document_id}.txt"
    out.write_text(override, encoding="utf-8")
    print(f"  merged {len(scanned)} OCR'd page(s) + {n - len(scanned)} native page(s) "
          f"-> {out.name} ({nonspace(override):,} non-space chars)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["detect", "build"])
    ap.add_argument("--doc", required=True, metavar='"District|File.pdf"')
    ap.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS,
                    help=f"pages with fewer non-space chars are treated as scanned (default {DEFAULT_MIN_CHARS})")
    args = ap.parse_args()
    if "|" not in args.doc:
        raise SystemExit("--doc must be 'District Name|File.pdf'")
    district, file_name = args.doc.split("|", 1)

    if args.cmd == "detect":
        info = detect(district, file_name, args.min_chars)
        print(f"{file_name}")
        print(f"  pages: {info['pages']}")
        print(f"  verdict: {info['verdict']}")
        if info["scanned_pages_1indexed"]:
            print(f"  scanned pages (need OCR): {info['scanned_pages_1indexed']}")
    else:
        build(district, file_name, args.min_chars)


if __name__ == "__main__":
    main()
