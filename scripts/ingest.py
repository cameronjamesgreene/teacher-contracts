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
from typing import Optional

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


def select_stratified(rows: list, n: int, already: set,
                      deprioritise: Optional[set] = None) -> list:
    """Pick n placeholders to hydrate, spread across district and document type.

    Round-robins over (district, doc_type) strata so a request for 50 documents does not come
    back as 50 contracts from the three districts that happen to sort first.
    """
    deprioritise = deprioritise or set()
    strata = defaultdict(list)
    for r in rows:
        if not r["placeholder"]:
            continue
        if r["file_name"] in already:
            continue
        strata[(r["district"], r["doc_type"])].append(r)
    # Districts already available elsewhere (the HPC corpus) go last: the point of adding
    # 50 documents is to BROADEN coverage, not to re-download what can already be tested.
    keys = sorted(strata, key=lambda k: (k[0] in deprioritise, k))
    picked = []
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


# ── staging folder for Dropbox hydration ──────────────────────────────────────────────────
# Dropbox Smart Sync placeholders can only be hydrated through Finder, and the 1,143 stubs
# are spread over 149 district folders, which makes "select them all and Make Available
# Offline" impractical. stage_for_hydration() copies the selected placeholders into ONE
# folder so the whole set can be hydrated with a single right-click.
#
# Copies, not moves: the originals stay exactly where they are, so if Dropbox declines to
# resolve a copied placeholder the only cost is deleting the staging folder. VERIFY ONE FILE
# before hydrating all of them (the CLI cannot tell in advance -- the placeholder xattr is a
# 2-byte flag, not a content hash).
#
# The manifest records each staged file's ORIGINAL relative path so document_ids stay
# identical to what the rest of the corpus would produce, and so the staging folder can be
# removed without losing the mapping.

STAGING_MANIFEST = "_manifest.tsv"


def stage_for_hydration(picked: list, staging: Path) -> Path:
    import shutil
    staging.mkdir(parents=True, exist_ok=True)
    lines = ["staged_name\tdistrict\toriginal_path"]
    for r in picked:
        # District is prefixed onto the filename so the flat folder stays unambiguous when
        # two districts ship a file called "handbook.pdf".
        staged = f"{utils.slugify(r['district'], 40)}__{r['file_name']}"
        dest = staging / staged
        if not dest.exists():
            shutil.copy2(r["path"], dest)
        lines.append(f"{staged}\t{r['district']}\t{r['path']}")
    (staging / STAGING_MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return staging / STAGING_MANIFEST


def ingest_staged(staging: Path) -> dict:
    """Extract + index every hydrated file in the staging folder, using each file's ORIGINAL
    path for its document_id so IDs match the rest of the corpus."""
    man = staging / STAGING_MANIFEST
    if not man.exists():
        raise SystemExit(f"no manifest at {man}; run --stage first")
    counts: dict = defaultdict(int)
    still_stubs, needs_ocr = [], []
    for line in man.read_text(encoding="utf-8").splitlines()[1:]:
        staged_name, district, original = line.split("\t")
        p = staging / staged_name
        if not p.exists():
            counts["missing"] += 1
            continue
        if is_placeholder(p):
            counts["still_placeholder"] += 1
            still_stubs.append(staged_name)
            continue
        res = ingest_one(p, district)
        counts[res["status"]] += 1
        if res["status"] == "needs_ocr":
            needs_ocr.append(res)
    return {"counts": dict(counts), "still_placeholder": still_stubs, "needs_ocr": needs_ocr}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--survey", action="store_true", help="inventory the corpus tree")
    ap.add_argument("--select", type=int, metavar="N",
                    help="propose N placeholders to hydrate, stratified")
    ap.add_argument("--ingest", action="store_true",
                    help="extract + index every hydrated PDF not already indexed")
    ap.add_argument("--stage", metavar="DIR",
                    help="copy the selected placeholders into ONE folder for hydration")
    ap.add_argument("--ingest-staged", metavar="DIR",
                    help="extract + index a hydrated staging folder")
    ap.add_argument("--skip-districts", metavar="FILE",
                    help="file of district names already present elsewhere, to deprioritise")
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
        depri = set()
        if args.skip_districts and Path(args.skip_districts).exists():
            depri = {l.strip() for l in Path(args.skip_districts).read_text().splitlines()
                     if l.strip()}
        picked = select_stratified(inv["rows"], args.select, already, depri)
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
        if args.stage:
            staging = Path(args.stage)
            man = stage_for_hydration(picked, staging)
            print(f"\nSTAGED {len(picked)} file(s) into a single folder:\n  {staging}")
            print(f"  manifest: {man}")
            print("\n  1. In Finder, right-click THAT ONE FOLDER -> \"Make Available Offline\"")
            print("  2. Check one file is no longer 0 bytes before trusting the rest")
            print(f"  3. Re-run:  python3 ingest.py --ingest-staged '{staging}'")
            print("\n  The originals are untouched -- these are copies, so if Dropbox will not")
            print("  resolve a copied placeholder, delete the folder and hydrate the district")
            print("  folders in place instead. Nothing is lost either way.")

    if args.ingest_staged:
        res = ingest_staged(Path(args.ingest_staged))
        print("\nstaged ingest: " + " | ".join(f"{k}={v}" for k, v in
                                               sorted(res["counts"].items())))
        if res["still_placeholder"]:
            print(f"\n{len(res['still_placeholder'])} file(s) are STILL 0 bytes -- Dropbox has "
                  "not hydrated them yet (or will not resolve the copy):")
            for nme in res["still_placeholder"][:10]:
                print(f"  {nme}")
        if res["needs_ocr"]:
            print(f"\n{len(res['needs_ocr'])} scanned document(s) need the olmocr2 pass:")
            for d in res["needs_ocr"][:10]:
                print(f"  {d['document_id'][:60]:62s} {d['chars_per_page']:>6} chars/page")
        corpus.rebuild_term_df(corpus.get_con())
        print(f"\nindex now holds {corpus.n_docs(corpus.get_con())} documents")

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
