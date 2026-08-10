#!/usr/bin/env python3
"""Drive the OCR stack end to end: engines -> arbitration -> adoption -> manifest.

The pieces existed and were run by hand, one command per engine per document, with
the adoption step (getting the reconciled text to where the pipeline reads it) done
informally. That is how the OCR text for the six scans came to exist on exactly one
machine and then stop existing: it was a build artifact nobody could rebuild. This
script is the missing step, and it is deliberately boring.

    engines           ocr_scanned.py, one markdown per document per engine
    arbitration       ocr_reconcile.py, per page, with provenance
    adoption          cache/ocr_text/<id>.txt, mirrored to the manifest's text_path
    manifest          text_sha256 / text_characters / text_status refreshed in place

## Adoption writes two files on purpose

`utils.extract_text()` treats `cache/ocr_text/<name>` as authoritative over anything
pdftotext produced, which is what makes the OCR survive someone clearing the text
cache. But `grind_retrieve.corpus()` reads the manifest's `text_path`
(`cache/extracted_text/<id>.txt`) directly. Writing only one of the two gives two
readers two different documents under one document_id, so both are written and the
ocr_text copy is the one that is authoritative if they ever diverge.

## Re-running OCR invalidates prior extractions

Answers are grounded against the extracted text; replace the text and old quotes
point at nothing. Kyle measured this — swapping engines dropped a citation audit from
1.000 to 0.789 with no change in extraction quality. So `--refresh-manifest` reports
which documents changed, and any results for those documents must be re-run rather
than compared.

Usage:
    python3 scripts/run_ocr.py --engine apple_vision --refresh-manifest
    python3 scripts/run_ocr.py --engine apple_vision --engine olmocr2 \\
        --ocr-examples ~/ocr-examples --refresh-manifest
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import OCR_TEXT_DIR, TEXT_DIR, WORK

SCRIPTS = Path(__file__).resolve().parent
MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"
MD_ROOT = WORK / "cache" / "ocr_md"
PROVENANCE_DIR = WORK / "output" / "extraction" / "ocr_provenance"
# Same rule load_documents() uses: below this a "text layer" is page furniture.
MIN_CHARS_PER_PAGE = 20


def read_manifest() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORK / path


def needs_ocr(row: dict[str, str]) -> bool:
    """True when this document has no usable text on disk right now.

    Deliberately judged from the filesystem rather than the manifest's text_status:
    once a scan has been OCR'd the manifest says `usable`, so trusting it would make
    this script a no-op on exactly the documents it exists to rebuild.
    """
    for candidate in (OCR_TEXT_DIR / f"{row['document_id']}.txt", resolve(row["text_path"])):
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            dense = len("".join(text.split()))
            pages = int(row["pdf_pages"] or 0)
            if dense >= max(1, pages) * MIN_CHARS_PER_PAGE:
                return False
    return True


def run(command: list[str]) -> None:
    print("  $ " + " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True)


def run_engine(engine: str, rows: list[dict[str, str]], ocr_examples: Path | None) -> Path:
    """Produce one markdown per document for one engine. Returns its md directory."""
    md_dir = MD_ROOT / engine
    md_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(SCRIPTS / "ocr_scanned.py"), "--engine", engine,
               "--md-dir", str(md_dir)]
    for row in rows:
        command += ["--document-id", row["document_id"]]
    if engine == "olmocr2":
        if not ocr_examples:
            raise SystemExit("olmocr2 needs --ocr-examples (a yale-som-hpc/ocr-examples "
                             "checkout) and a reachable HPC login node")
        command += ["--ocr-examples", str(ocr_examples)]
    run(command)
    return md_dir


def reconcile_document(row: dict[str, str], engines: list[str]) -> Path | None:
    """Arbitrate this document's engines into one text. Returns the adopted path."""
    stem = Path(row["file_name"]).stem
    sources = []
    for engine in engines:
        markdown = MD_ROOT / engine / f"{stem}.md"
        if markdown.exists():
            sources.append(f"{engine}={markdown}")
    if not sources:
        print(f"  ! no engine output for {row['document_id']}")
        return None

    adopted = OCR_TEXT_DIR / f"{row['document_id']}.txt"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(SCRIPTS / "ocr_reconcile.py"), "--out", str(adopted),
               "--provenance", str(PROVENANCE_DIR / f"{row['document_id']}.csv")]
    for source in sources:
        command += ["--source", source]
    run(command)

    # Mirror to the manifest's text_path so retrieval and extraction read one document.
    mirror = resolve(row["text_path"])
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(adopted.read_text(encoding="utf-8"), encoding="utf-8")
    return adopted


def refresh_manifest(adopted: dict[str, Path]) -> None:
    """Rewrite text_sha256 / text_characters / text_status for the OCR'd rows only."""
    rows = read_manifest()
    changed = []
    for row in rows:
        path = adopted.get(row["document_id"])
        if path is None:
            continue
        text = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != row["text_sha256"]:
            changed.append((row["document_id"], row["text_characters"], len(text)))
        row["text_sha256"] = digest
        row["text_characters"] = str(len(text))
        pages = int(row["pdf_pages"] or 0)
        dense = len("".join(text.split()))
        row["text_status"] = ("usable" if dense >= max(1, pages) * MIN_CHARS_PER_PAGE
                              else "ocr_needed")
    with MANIFEST.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nmanifest refreshed -> {MANIFEST}")
    if changed:
        print(f"  {len(changed)} document(s) now have DIFFERENT text than the manifest froze.")
        print("  Any extraction, index or answer key built on the old text is stale:")
        for document_id, before, after in changed:
            print(f"    {document_id}  {before} -> {after} chars")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", action="append", dest="engines",
                        choices=("apple_vision", "olmocr2"),
                        help="repeatable; two engines enable figure arbitration")
    parser.add_argument("--document-id", action="append", dest="document_ids",
                        help="default: every document with no usable text on disk")
    parser.add_argument("--ocr-examples", type=Path, help="checkout required by olmocr2")
    parser.add_argument("--skip-engines", action="store_true",
                        help="reuse markdown already in cache/ocr_md and only reconcile")
    parser.add_argument("--refresh-manifest", action="store_true",
                        help="update the frozen manifest to the newly adopted text")
    args = parser.parse_args()

    engines = args.engines or ["apple_vision"]
    rows = read_manifest()
    if args.document_ids:
        wanted = set(args.document_ids)
        targets = [row for row in rows if row["document_id"] in wanted]
    else:
        targets = [row for row in rows if needs_ocr(row)]
    if not targets:
        print("every document already has usable text; nothing to OCR")
        return

    print(f"{len(targets)} document(s), "
          f"{sum(int(row['pdf_pages'] or 0) for row in targets)} pages, "
          f"engines: {', '.join(engines)}")
    if len(engines) == 1:
        print("  NOTE: one engine means no figure arbitration. ocr_reconcile still applies "
              "the degeneracy\n        and fabrication gates, but a misread number has "
              "nothing to disagree with it.")

    if not args.skip_engines:
        for engine in engines:
            print(f"\n== {engine} ==")
            run_engine(engine, targets, args.ocr_examples)

    print("\n== arbitration and adoption ==")
    adopted: dict[str, Path] = {}
    for row in targets:
        print(f"\n{row['district']} / {row['file_name']}")
        path = reconcile_document(row, engines)
        if path is not None:
            adopted[row["document_id"]] = path

    if args.refresh_manifest and adopted:
        refresh_manifest(adopted)
    elif adopted:
        print(f"\n{len(adopted)} document(s) adopted. The manifest still holds the old "
              f"checksums;\nre-run with --refresh-manifest once the text looks right.")


if __name__ == "__main__":
    main()
