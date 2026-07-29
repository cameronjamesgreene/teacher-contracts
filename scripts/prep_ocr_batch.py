#!/usr/bin/env python3
"""Prepare the HPC OCR batch staging for scanned / image-only sample documents.

Re-derives the OCR work-list from the same text_status heuristic the pipeline
uses (see utils.load_documents), then lays out each OCR-needed document the way
the yale-som-hpc/ocr-examples repo expects:

    cache/ocr_documents/
      documents/<uuid>/document.pdf     # copied from the hydrated source PDF
      document-ids.txt                  # UUIDs that are READY to run now
      uuid_to_document_id.json          # UUID -> our document_id (for splice-back)
      ocr_manifest.json                 # full status table (all OCR-needed docs)

A document is READY only when its source PDF is hydrated locally (not a 0-byte
Dropbox "online-only" placeholder). This script is idempotent -- re-run it after
hydrating more PDFs and it will copy the newly available ones and grow
document-ids.txt. Documents that already have an OCR override in cache/ocr_text/
are treated as done and dropped from the work-list.

Run from the scripts/ directory:  python3 prep_ocr_batch.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from utils import OCR_TEXT_DIR, PDF_ROOT, ROOT, TEXT_DIR, WORK, read_sample, slugify

STAGE = WORK / "cache" / "ocr_documents"
DOCS = STAGE / "documents"


def document_id_for(district: str, file_name: str) -> str:
    """Identical formula to utils.load_documents / salary_schedule.document_id_for."""
    path = PDF_ROOT / district / file_name
    doc_hash = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:8]
    return f"{slugify(district, 45)}__{slugify(Path(file_name).stem, 55)}__{doc_hash}"


def page_count(path: Path) -> int | None:
    try:
        proc = subprocess.run(["pdfinfo", str(path)], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return None
    match = re.search(r"^Pages:\s+(\d+)", proc.stdout, re.M)
    return int(match.group(1)) if match else None


def needs_ocr(chars: int, pages: int | None) -> bool:
    """Mirror of the text_status thin-text test in utils.load_documents."""
    if pages and chars < max(1000, pages * 20):
        return True
    return chars < 1000


def main() -> None:
    sample = read_sample()
    STAGE.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    ready_uuids: list[str] = []
    uuid_map: dict[str, str] = {}

    for district, file_name in sample:
        document_id = document_id_for(district, file_name)

        # Already OCR'd (override present and non-empty) -> nothing to do.
        override = OCR_TEXT_DIR / f"{document_id}.txt"
        if override.exists() and override.read_text(encoding="utf-8", errors="ignore").strip():
            continue

        cache_txt = TEXT_DIR / f"{document_id}.txt"
        text = cache_txt.read_text(encoding="utf-8", errors="ignore") if cache_txt.exists() else ""
        chars = len(re.sub(r"\s+", "", text))
        src = PDF_ROOT / district / file_name
        pdf_bytes = src.stat().st_size if src.exists() else 0
        pages = page_count(src) if pdf_bytes > 0 else (text.count("\f") + 1 if text else None)

        if not needs_ocr(chars, pages):
            continue

        doc_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, document_id))
        uuid_map[doc_uuid] = document_id
        hydrated = pdf_bytes > 0

        if hydrated:
            dest = DOCS / doc_uuid / "document.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if (not dest.exists()) or dest.stat().st_size != pdf_bytes:
                shutil.copy2(src, dest)
            ready_uuids.append(doc_uuid)

        manifest.append({
            "district": district,
            "file_name": file_name,
            "document_id": document_id,
            "uuid": doc_uuid,
            "pages": pages,
            "pdf_bytes": pdf_bytes,
            "hydrated": hydrated,
            "ready": hydrated,
            "cached_pdftotext_chars": chars,
        })

    (STAGE / "document-ids.txt").write_text(
        "\n".join(ready_uuids) + ("\n" if ready_uuids else ""), encoding="utf-8")
    (STAGE / "uuid_to_document_id.json").write_text(
        json.dumps(uuid_map, indent=2), encoding="utf-8")
    (STAGE / "ocr_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"OCR-needed documents: {len(manifest)}   |   READY to run now: {len(ready_uuids)}\n")
    print(f"{'READY?':<7}{'pages':>6}{'pdf':>12}   district / file")
    print("-" * 78)
    for m in sorted(manifest, key=lambda x: (not x["ready"], -(x["pages"] or 0))):
        pdf = f"{m['pdf_bytes'] / 1e6:.2f} MB" if m["pdf_bytes"] else "0B (hydrate)"
        print(f"{'YES' if m['ready'] else 'no':<7}{str(m['pages']):>6}{pdf:>12}   {m['district']} / {m['file_name']}")

    print(f"\nStaging dir: {STAGE}")
    print(f"  document-ids.txt   -> {len(ready_uuids)} ready UUID(s) — pass this to the HPC OCR run")
    print(f"  ocr_manifest.json  -> full work-list ({len(manifest)} docs) with status")
    print(f"  uuid_to_document_id.json -> UUID -> document_id map (for splicing OCR text back)")

    not_ready = [m for m in manifest if not m["ready"]]
    if not_ready:
        print("\nNOT-READY docs (0-byte Dropbox placeholders). In Finder, right-click each PDF")
        print("below -> 'Make Available Offline', wait for the solid green check, then re-run this script:")
        for m in not_ready:
            print(f"  - {PDF_ROOT / m['district'] / m['file_name']}")


if __name__ == "__main__":
    main()
