"""Corpus ingestion: hydrate-check -> extract text -> detect scans -> index into FTS5.

Scoped to growing the test corpus by ~50 documents, not to the full 7,000-path Dropbox tree.

THE HYDRATION CONSTRAINT, up front: of 7,328 PDF paths under the Dropbox contracts tree,
7,255 are 0-byte Dropbox Smart Sync placeholders. A 0-byte file is not an empty or corrupt
PDF -- it is a stub, and **the CLI cannot hydrate it**. `cat`, `cp` and Python `open()` all
either fail or silently read nothing; only Finder's "Make Available Offline" (or opening the
file in a GUI app) pulls the bytes down. So this script does not attempt to download
anything. It reports exactly which files need hydrating, in a form that can be pasted into
Finder, and processes whatever is actually present.

`--select N` picks a stratified sample rather than the first N alphabetically, because the
existing gold set is four documents of which two are Utah districts and two are single-
district state systems. Stratifying on state, document type and page count is what makes the
next audit generalise.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import corpus
import utils

PDF_ROOT = Path(os.environ.get("CONTRACT_PDF_ROOT", str(utils.PDF_ROOT)))
CACHE_DIR = corpus.CACHE_DIR
TEXT_DIR = CACHE_DIR / "extracted_text"

# A born-digital page carries hundreds of characters; a scanned one carries a handful of OCR
# noise or nothing. utils uses the same thresholds for its auto-OCR trigger.
SCAN_CHARS_PER_PAGE = int(os.environ.get("INGEST_SCAN_CHARS_PER_PAGE", "120"))

_HANDBOOK_RE = re.compile(r"handbook|policy|manual", re.I)
_TA_RE = re.compile(r"tentative|\bta\b|mou|memorandum|side.?letter|amendment", re.I)


def doc_type(name: str) -> str:
    if _HANDBOOK_RE.search(name):
        return "handbook"
    if _TA_RE.search(name):
        return "agreement_supplement"
    return "cba"


def is_placeholder(p: Path) -> bool:
    """0 bytes means a Dropbox Smart Sync stub, not an empty document."""
    try:
        return p.stat().st_size == 0
    except OSError:
        return True


def page_count(p: Path) -> int:
    try:
        out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True, timeout=60)
        m = re.search(r"^Pages:\s+(\d+)", out.stdout, re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def survey(root: Path = PDF_ROOT) -> dict:
    """Inventory every PDF path: hydrated or placeholder, and its stratification keys."""
    rows = []
    for p in sorted(root.rglob("*.pdf")):
        if p.name.startswith("._"):          # macOS AppleDouble junk; pdfinfo chokes on these
            continue
        district = p.parent.name
        rows.append({
            "path": p, "district": district, "file_name": p.name,
            "placeholder": is_placeholder(p),
            "size": 0 if is_placeholder(p) else p.stat().st_size,
            "doc_type": doc_type(p.name),
        })
    return {"rows": rows,
            "n": len(rows),
            "hydrated": sum(1 for r in rows if not r["placeholder"]),
            "placeholders": sum(1 for r in rows if r["placeholder"])}


def select_stratified(rows: list, n: int, already: set) -> list:
    """Pick n placeholders to hydrate, spread across district and document type.

    Round-robins over (district, doc_type) strata so a request for 50 documents does not come
    back as 50 contracts from the three districts that happen to sort first.
    """
    strata = defaultdict(list)
    for r in rows:
        if not r["placeholder"]:
            continue
        if r["file_name"] in already:
            continue
        strata[(r["district"], r["doc_type"])].append(r)
    picked, keys = [], sorted(strata)
    i = 0
    while len(picked) < n and keys:
        k = keys[i % len(keys)]
        if strata[k]:
            picked.append(strata[k].pop(0))
        else:
            keys.remove(k)
            continue
        i += 1
    return picked


def ingest_one(path: Path, district: str) -> dict:
    """Extract text for one hydrated PDF and index it. Returns a status record."""
    document_id = utils.document_id_for(district, path.name) \
        if hasattr(utils, "document_id_for") else None
    if document_id is None:
        import hashlib
        h = hashlib.sha1(str(path.relative_to(utils.ROOT)).encode()).hexdigest()[:8]
        document_id = (f"{utils.slugify(district, 45)}__"
                       f"{utils.slugify(path.stem, 55)}__{h}")
    if is_placeholder(path):
        return {"document_id": document_id, "status": "needs_hydration", "pages": 0}

    text_path = TEXT_DIR / f"{document_id}.txt"
    if not text_path.exists() or not text_path.stat().st_size:
        TEXT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftotext", "-layout", str(path), str(text_path)],
                       check=False, timeout=900)
    if not text_path.exists():
        return {"document_id": document_id, "status": "extract_failed", "pages": 0}

    text = text_path.read_text(encoding="utf-8", errors="ignore")
    pages = max(1, page_count(path))
    ocr_override = CACHE_DIR / "ocr_text" / f"{document_id}.txt"
    if ocr_override.exists() and ocr_override.stat().st_size:
        text = ocr_override.read_text(encoding="utf-8", errors="ignore")
        source = "ocr"
    elif len(text) / pages < SCAN_CHARS_PER_PAGE:
        # Flagged, not blocked. Auto-OCR in utils blocks up to AUTO_OCR_WAIT_S (4200s) per
        # document; at corpus scale that is fatal, so OCR is a separate queued pass.
        return {"document_id": document_id, "status": "needs_ocr", "pages": pages,
                "chars": len(text), "chars_per_page": round(len(text) / pages, 1)}
    else:
        source = "pdftotext"

    n = corpus.index_document(document_id, text, district=district,
                              file_name=path.name, pdf_path=str(path),
                              text_source=source)
    return {"document_id": document_id, "status": "indexed", "pages": pages,
            "chars": len(text), "page_parts": n, "source": source}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--survey", action="store_true", help="inventory the corpus tree")
    ap.add_argument("--select", type=int, metavar="N",
                    help="propose N placeholders to hydrate, stratified")
    ap.add_argument("--ingest", action="store_true",
                    help="extract + index every hydrated PDF not already indexed")
    ap.add_argument("--root", default=str(PDF_ROOT))
    args = ap.parse_args()
    root = Path(args.root)
    if not root.exists():
        print(f"corpus root not found: {root}", file=sys.stderr)
        return 2

    inv = survey(root)
    print(f"corpus root: {root}")
    print(f"  {inv['n']:,} PDF paths | {inv['hydrated']:,} hydrated | "
          f"{inv['placeholders']:,} Smart Sync placeholders (0 bytes)")

    if args.select:
        con = corpus.get_con()
        already = {r[0] for r in con.execute("SELECT file_name FROM doc")}
        picked = select_stratified(inv["rows"], args.select, already)
        print(f"\n{len(picked)} documents proposed for hydration, stratified by "
              f"(district, document type):\n")
        for r in picked:
            print(f"  {r['district'][:34]:36s} {r['doc_type'][:20]:22s} {r['file_name']}")
        out = Path("hydrate_list.txt")
        out.write_text("\n".join(str(r["path"]) for r in picked), encoding="utf-8")
        print(f"\nwrote {out}")
        print("\nThese are 0-byte Smart Sync stubs. The CLI cannot hydrate them.")
        print("In Finder, select these files -> right-click -> \"Make Available Offline\",")
        print("wait for the green check, then re-run with --ingest.")

    if args.ingest:
        con = corpus.get_con()
        indexed = {r[0] for r in con.execute("SELECT document_id FROM doc")}
        counts: dict = defaultdict(int)
        needs = []
        for r in inv["rows"]:
            if r["placeholder"]:
                counts["needs_hydration"] += 1
                continue
            res = ingest_one(r["path"], r["district"])
            counts[res["status"]] += 1
            if res["status"] == "needs_ocr":
                needs.append(res)
            elif res["status"] == "indexed" and res["document_id"] not in indexed:
                print(f"  indexed {res['document_id'][:60]:62s} "
                      f"{res['pages']:>4}p {res.get('page_parts',0):>5} parts")
        print("\nsummary: " + " | ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if needs:
            print(f"\n{len(needs)} document(s) look scanned and need OCR before indexing:")
            for d in needs[:20]:
                print(f"  {d['document_id'][:62]:64s} {d['chars_per_page']:>6} chars/page")
            print("Run the olmocr2 pass (scripts/hybrid_ocr.py) on these, then re-run --ingest.")
        corpus.rebuild_term_df(con)
        print(f"\nindex now holds {corpus.n_docs(con)} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
