#!/usr/bin/env python3
"""Page-range chunking for HPC OCR at scale (wraps yale-som-hpc/ocr-examples).

docling-serve converts one whole PDF per request, so large scanned contracts
(100-300+ pages) hit timeouts, pin a single GPU worker, and fail all-or-nothing.
This splits each PDF into fixed-size page-range chunks that OCR independently
and in parallel, then reassembles them. See docs/scale_ocr_chunking.md.

Pipeline:
  split   -> cut each OCR-needed source PDF (from ocr_manifest.json) into
             <chunk-size>-page chunk PDFs, each staged as its own ocr-examples
             document under cache/ocr_documents/chunks/<chunk_uuid>/document.pdf;
             write chunk-ids.txt (feed to documents_process.py) + chunk_manifest.json
  (OCR)   -> run the normal ocr-examples workflow on chunk-ids.txt with many workers
  concat  -> gather each source doc's chunk outputs in page order, strip docling's
             embedded base64 images, and write the reassembled text to
             cache/ocr_text/<document_id>.txt (the override slot extract_text() reads)

Usage:
  python3 chunk_ocr.py split  [--chunk-size 25]
  python3 chunk_ocr.py concat [--engine docling]
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path

from pypdf import PdfReader, PdfWriter

WORK = Path(__file__).resolve().parents[1]
STAGE = WORK / "cache" / "ocr_documents"
DOCUMENTS = STAGE / "documents"          # whole-doc staging (prep_ocr_batch.py)
CHUNKS = STAGE / "chunks"                # per-chunk staging (this script)
OCR_TEXT_DIR = WORK / "cache" / "ocr_text"
MANIFEST = STAGE / "ocr_manifest.json"           # produced by prep_ocr_batch.py
CHUNK_MANIFEST = STAGE / "chunk_manifest.json"
CHUNK_IDS = STAGE / "chunk-ids.txt"

# docling embeds page figures/logos as ![...](data:image/...;base64,....)
IMG_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^)]*\)")


def chunk_uuid(parent_document_id: str, start: int, end: int) -> str:
    """Deterministic UUID for a page range, so splitting is idempotent."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{parent_document_id}#pages{start:04d}-{end:04d}"))


def do_split(chunk_size: int) -> None:
    if not MANIFEST.exists():
        raise SystemExit(f"No {MANIFEST}. Run prep_ocr_batch.py first.")
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    CHUNKS.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for e in entries:
        pid = e["document_id"]
        src = DOCUMENTS / e["uuid"] / "document.pdf"
        if not src.exists() or src.stat().st_size == 0:
            print(f"  -  {pid}: staged source pdf missing/placeholder, skip")
            continue
        reader = PdfReader(str(src))
        n = len(reader.pages)
        idx = 0
        for start in range(1, n + 1, chunk_size):
            end = min(start + chunk_size - 1, n)
            cid = chunk_uuid(pid, start, end)
            dest = CHUNKS / cid / "document.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                writer = PdfWriter()
                for p in range(start - 1, end):          # 0-indexed page slice
                    writer.add_page(reader.pages[p])
                with dest.open("wb") as fh:
                    writer.write(fh)
            manifest.append({
                "chunk_uuid": cid,
                "parent_document_id": pid,
                "chunk_index": idx,
                "page_start": start,
                "page_end": end,
                "pages": end - start + 1,
            })
            idx += 1
        print(f"  ok {pid}: {n} pages -> {idx} chunk(s) of <= {chunk_size}")

    CHUNK_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    CHUNK_IDS.write_text("\n".join(m["chunk_uuid"] for m in manifest) + ("\n" if manifest else ""),
                         encoding="utf-8")
    parents = len({m["parent_document_id"] for m in manifest})
    print(f"\n{len(manifest)} chunk(s) across {parents} document(s)")
    print(f"  chunk-ids.txt       -> documents_process.py --from-file")
    print(f"  chunk_manifest.json -> parent/page mapping for `concat`")
    print(f"  chunk PDFs          -> {CHUNKS}")


def do_concat(engine: str) -> None:
    if not CHUNK_MANIFEST.exists():
        raise SystemExit(f"No {CHUNK_MANIFEST}. Run `chunk_ocr.py split` first.")
    manifest = json.loads(CHUNK_MANIFEST.read_text(encoding="utf-8"))
    by_parent: dict[str, list[dict]] = {}
    for m in manifest:
        by_parent.setdefault(m["parent_document_id"], []).append(m)
    OCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    for pid, chunks in by_parent.items():
        chunks.sort(key=lambda c: c["chunk_index"])
        parts: list[str] = []
        missing: list[int] = []
        for c in chunks:
            src = CHUNKS / c["chunk_uuid"] / "ocr" / f"{engine}.txt"
            if not src.exists():
                missing.append(c["chunk_index"])
                parts.append("")
                continue
            md = IMG_RE.sub("", src.read_text(encoding="utf-8", errors="ignore"))
            parts.append(md.strip())
        # \f between chunks = coarse page delimiter for downstream text.split("\f")
        text = "\n\n\f\n\n".join(parts).strip() + "\n"
        out = OCR_TEXT_DIR / f"{pid}.txt"
        out.write_text(text, encoding="utf-8")
        nonspace = len(re.sub(r"\s+", "", text))
        status = "COMPLETE" if not missing else f"MISSING chunk index {missing} -- re-OCR then re-concat"
        print(f"  {pid}: {len(chunks)} chunk(s), {nonspace:,} non-space chars -> {out.name}  [{status}]")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("split", help="split source PDFs into page-range chunk PDFs")
    sp.add_argument("--chunk-size", type=int, default=25, help="pages per chunk (default 25)")
    cc = sub.add_parser("concat", help="reassemble chunk OCR outputs per source document")
    cc.add_argument("--engine", default="docling", help="which engine's output to concat")
    args = ap.parse_args()

    if args.cmd == "split":
        do_split(args.chunk_size)
    elif args.cmd == "concat":
        do_concat(args.engine)


if __name__ == "__main__":
    main()
