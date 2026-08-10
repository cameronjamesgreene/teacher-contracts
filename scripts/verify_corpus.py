#!/usr/bin/env python3
"""Check the local corpus against the frozen manifest, and say what is missing.

Extracted text is not in the repository — it is gitignored, regenerable, and large —
so a fresh checkout has 42 PDFs and no text at all. Everything downstream (the FTS5
index, the embeddings, every grounded quote, every page number) is derived from that
text, which makes "is my text the same text the answer keys were built against?" the
first question worth answering and the easiest one to skip.

`output/extraction/corpus_manifest.csv` records a sha256 of each PDF and of its
extracted text. This script recomputes both.

Three outcomes per document, and they mean different things:

  ok          text reproduces the manifest checksum exactly. Keys and cached results
              for this document are valid.
  needs_ocr   the PDF has no usable text layer. pdftotext cannot produce the
              manifest's text because the manifest's text came from OCR. Run
              scripts/ocr_scanned.py. This is expected for the six image-only scans.
  mismatch    text exists and differs from the manifest. This is the dangerous one:
              answers grounded against different text point at different pages, so a
              prior extraction is not comparable. Kyle measured exactly this — swapping
              OCR engines dropped a citation audit from 1.000 to 0.789 with no change
              in quality. Treat the text as part of a result's provenance.

Usage:
    python3 scripts/verify_corpus.py              # report only
    python3 scripts/verify_corpus.py --extract    # run pdftotext where text is absent
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OCR_TEXT_DIR, WORK, extract_text

MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"

# A page of a real contract carries far more than this; below it the "text" is page
# furniture from a scan. Matches the threshold load_documents() uses for text_status.
MIN_CHARS_PER_PAGE = 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(value: str) -> Path:
    """Manifest paths are repo-relative; absolute is honoured for older manifests."""
    path = Path(value)
    return path if path.is_absolute() else WORK / path


def text_source(text_path: Path) -> str:
    """Which extractor supplied this document's text — provenance, not a detail."""
    return "ocr" if (OCR_TEXT_DIR / text_path.name).exists() else "pdftotext"


def check(row: dict[str, str], do_extract: bool) -> dict[str, str]:
    pdf_path = resolve(row["source_path"])
    text_path = resolve(row["text_path"])
    result = {"document_id": row["document_id"], "district": row["district"],
              "pages": row["pdf_pages"], "source": "", "note": ""}

    if not pdf_path.exists():
        return {**result, "status": "pdf_missing", "note": str(pdf_path)}
    if sha256_file(pdf_path) != row["pdf_sha256"]:
        return {**result, "status": "pdf_changed",
                "note": "the source PDF differs from the one the manifest froze"}

    if do_extract:
        extract_text(pdf_path, text_path)      # no-op when the text is already cached

    text = ""
    if (OCR_TEXT_DIR / text_path.name).exists():
        text = (OCR_TEXT_DIR / text_path.name).read_text(encoding="utf-8", errors="ignore")
    if not text.strip() and text_path.exists():
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    result["source"] = text_source(text_path)

    if text.strip() and hashlib.sha256(text.encode("utf-8")).hexdigest() == row["text_sha256"]:
        return {**result, "status": "ok"}

    # Not a match. Distinguish "this PDF has no text layer" — expected, fixable by OCR —
    # from "the text is different", which invalidates comparisons against the keys.
    # An empty extraction is the extreme case of the former, not a separate problem:
    # pdftotext ran and the page had nothing on it to read.
    pages = int(row["pdf_pages"] or 0)
    dense = len("".join(text.split()))
    if pages and dense < pages * MIN_CHARS_PER_PAGE:
        return {**result, "status": "needs_ocr",
                "note": f"{dense} non-space chars over {pages} pages; "
                        f"no usable text layer — scripts/ocr_scanned.py"}
    if not text.strip():
        return {**result, "status": "text_missing",
                "note": "no text and no page count; run with --extract"}
    return {**result, "status": "mismatch",
            "note": f"{len(text)} chars, manifest expected {row['text_characters']}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--extract", action="store_true",
                        help="run pdftotext for documents whose text is not cached")
    parser.add_argument("--out", type=Path, help="write the per-document report as CSV")
    args = parser.parse_args()

    with args.manifest.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    results = [check(row, args.extract) for row in rows]

    by_status: dict[str, list[dict[str, str]]] = {}
    for result in results:
        by_status.setdefault(result["status"], []).append(result)

    for status in ("ok", "needs_ocr", "mismatch", "text_missing", "pdf_changed", "pdf_missing"):
        group = by_status.get(status, [])
        if not group:
            continue
        print(f"\n{status}: {len(group)}")
        if status == "ok":
            continue                            # the healthy case needs no enumeration
        for result in sorted(group, key=lambda r: r["document_id"]):
            print(f"  {result['document_id']}  ({result['pages']}pp)  {result['note']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(
                output, fieldnames=["document_id", "district", "pages", "status",
                                    "source", "note"])
            writer.writeheader()
            writer.writerows(results)
        print(f"\nreport -> {args.out}")

    ok = len(by_status.get("ok", []))
    print(f"\n{ok}/{len(results)} documents reproduce the manifest checksum")
    # Anything other than ok or needs_ocr means the corpus is not the corpus the keys
    # were built against, so fail rather than let a run proceed on that basis.
    blocking = sum(len(by_status.get(status, []))
                   for status in ("mismatch", "pdf_changed", "pdf_missing"))
    raise SystemExit(1 if blocking else 0)


if __name__ == "__main__":
    main()
