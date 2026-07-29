#!/usr/bin/env python3
"""Stage arbitrary documents for HPC OCR (olmocr2) — for docs NOT in the 40-sample.

For each `--doc "District|File.pdf"`: compute the pipeline's canonical
document_id (same formula the coding scripts use), a deterministic UUID, copy the
hydrated source PDF into the ocr-examples layout at
cache/ocr_documents/documents/<uuid>/document.pdf, merge the UUID->document_id
mapping into uuid_to_document_id.json, and write the UUIDs to
cache/ocr_documents/document-ids.new.txt for the OCR run.

The source PDF must exist (hydrated, not a 0-byte Dropbox placeholder) at
nctq_contracts/<District>/<File.pdf> — that path is what defines the document_id,
so the OCR override lands where the coding scripts will look for it.

Usage:
  python3 stage_for_ocr.py --doc "District Name|File.pdf" [--doc "..."]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from utils import PDF_ROOT, ROOT, slugify

WORK = Path(__file__).resolve().parents[1]
STAGE = WORK / "cache" / "ocr_documents"
DOCS = STAGE / "documents"


def document_id_for(district: str, file_name: str) -> str:
    path = PDF_ROOT / district / file_name
    doc_hash = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:8]
    return f"{slugify(district, 45)}__{slugify(Path(file_name).stem, 55)}__{doc_hash}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", action="append", required=True, metavar='"District|File.pdf"',
                    help="Document to stage (repeatable)")
    args = ap.parse_args()

    DOCS.mkdir(parents=True, exist_ok=True)
    umap_path = STAGE / "uuid_to_document_id.json"
    umap = json.loads(umap_path.read_text(encoding="utf-8")) if umap_path.exists() else {}

    ids: list[str] = []
    for spec in args.doc:
        if "|" not in spec:
            print(f"  ! {spec!r}: expected 'District|File.pdf'"); continue
        district, file_name = spec.split("|", 1)
        src = PDF_ROOT / district / file_name
        if not src.exists() or src.stat().st_size == 0:
            print(f"  ! {spec}: PDF missing or 0-byte placeholder at {src} — hydrate it first"); continue
        document_id = document_id_for(district, file_name)
        doc_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, document_id))
        dest = DOCS / doc_uuid / "document.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        umap[doc_uuid] = document_id
        ids.append(doc_uuid)
        print(f"  ok {district} / {file_name}")
        print(f"       document_id = {document_id}")
        print(f"       uuid        = {doc_uuid}")

    umap_path.write_text(json.dumps(umap, indent=2), encoding="utf-8")
    (STAGE / "document-ids.new.txt").write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    print(f"\nStaged {len(ids)} doc(s) -> {STAGE / 'document-ids.new.txt'}")
    print("Next: run olmocr2 on the HPC with --from-file document-ids.new.txt, then splice_ocr.py")


if __name__ == "__main__":
    main()
