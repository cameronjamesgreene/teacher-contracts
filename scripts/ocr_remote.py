"""Scan detection and OCR, both executed remotely against the SOM API.

Replaces two things that previously required a human in the loop:

  * `ingest.py` used to FLAG scanned documents and stop, leaving someone to run a separate
    olmocr2 pass by hand.
  * `ocr_som_vision.py` could OCR via the SOM API, but only for documents already staged
    into `cache/ocr_documents/` by a manual `stage_for_ocr.py` step, one page at a time
    through a hand-rolled retry loop. Its own docstring says it "is NOT the scale path".

Here detection and OCR both run as part of a normal pipeline invocation on the HPC, through
`som_client` — so they inherit the concurrency governor, the retry classification, the
request-hash cache and the telemetry, exactly like every other model call.

TWO-STAGE DETECTION, and the second stage is the point
──────────────────────────────────────────────────────
Stage 1 is a free deterministic pre-filter: run `pdftotext -layout` per page and look at the
character count. A born-digital page carries hundreds of characters; a scanned one carries a
handful of noise or nothing. This catches the obvious cases at zero API cost.

Stage 2 asks the SOM vision model about the pages the counter cannot classify. This is not
ceremony — it fixes a documented failure mode. A page with a printed heading and a scanned
TABLE (the audit's "image-only salary-schedule page", Granite p.49) has enough extracted
characters to pass any char-count threshold while its actual substance — the grid — is an
image the text layer never saw. Character counting is structurally blind to that; looking at
the page is not.

So: pages far below the floor are scanned, pages far above with normal text density are
fine, and the ambiguous band in between gets one cheap vision call that answers "is the
substantive content of this page present in the text layer, or is it an image?".

MERGE SEMANTICS
───────────────
OCR replaces a page only when it recovers materially more text than the native layer, and
the result is written to `cache/ocr_text/<document_id>.txt` — the override slot that
`utils.extract_text()` already prefers, so all three coders pick it up with no further
change. Page count is asserted rather than assumed: a misaligned override silently corrupts
every page citation in the document, which is worse than no OCR at all.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import store
from som_client import MODEL, create_with_retries, get_client

WORK = Path(__file__).resolve().parents[1]
CACHE_DIR = Path(os.environ.get("CONTRACT_CACHE_DIR", str(WORK / "cache")))
OCR_TEXT_DIR = CACHE_DIR / "ocr_text"

RENDER_DPI = int(os.environ.get("OCR_DPI", "220"))
# Below SCANNED_MAX a page is scanned; above CLEAN_MIN it is born-digital; between the two
# the model decides. The band is deliberately wide because that is exactly where the
# heading-plus-image-table pages live.
SCANNED_MAX = int(os.environ.get("OCR_SCANNED_MAX_CHARS", "60"))
CLEAN_MIN = int(os.environ.get("OCR_CLEAN_MIN_CHARS", "900"))
ADJUDICATE_CAP = int(os.environ.get("OCR_ADJUDICATE_CAP", "40"))
OCR_CONCURRENCY = int(os.environ.get("OCR_CONCURRENCY", "8"))
# A page whose OCR beats the native layer by less than this is not worth swapping in.
MIN_GAIN_CHARS = int(os.environ.get("OCR_MIN_GAIN_CHARS", "40"))
# Must fit a reasoning trace AND the verdict JSON. At 500 the reasoning alone
# overran the budget on ~half the calls, each costing a full re-generation.
ADJUDICATE_MAX_TOKENS = int(os.environ.get("OCR_ADJUDICATE_MAX_TOKENS", "2500"))

TRANSCRIBE_PROMPT = (
    "Transcribe ALL text on this page VERBATIM. Preserve line breaks, indentation, bullet "
    "structure, table rows and columns, and every number and dollar amount exactly as "
    "printed. For a salary table, keep each row on its own line with columns separated by "
    "two or more spaces so the grid structure survives. Do not summarise, paraphrase, "
    "reorder, add or omit anything. If the page is blank, return an empty string.\n"
    'Reply with JSON only: {"text": "<the verbatim transcription>"}'
)

ADJUDICATE_PROMPT = (
    "You are deciding whether a PDF page needs OCR.\n"
    "Below is the text a PDF text-extractor pulled from this page, followed by an image of "
    "the same page. Decide whether the page's SUBSTANTIVE content is present in the "
    "extracted text, or whether the substance is an IMAGE that the text layer missed.\n"
    "A page with a typed heading but whose table, schedule or body is a scan DOES need OCR: "
    "having a few extracted characters is not the same as having the content.\n"
    'Reply with JSON only: {"needs_ocr": true|false, "reason": "<one short clause>"}'
)


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def native_pages(pdf: Path) -> list:
    """Per-page text from the PDF's own text layer."""
    n = page_count(pdf)
    pages = []
    for i in range(1, n + 1):
        out = subprocess.run(
            ["pdftotext", "-layout", "-f", str(i), "-l", str(i), str(pdf), "-"],
            capture_output=True, text=True)
        pages.append(out.stdout or "")
    return pages


def _nonspace(s: str) -> int:
    return len(re.sub(r"\s", "", s or ""))


def render_page(pdf: Path, n: int, tmpdir: str, dpi: int = RENDER_DPI) -> Optional[Path]:
    prefix = Path(tmpdir) / f"p{n}"
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(n), "-l", str(n),
                    "-singlefile", str(pdf), str(prefix)],
                   check=False, capture_output=True)
    out = prefix.with_suffix(".png")
    return out if out.exists() else None


def _data_url(png: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")


def _vision_call(client, png: Path, prompt: str, stage: str, document_id: str,
                 max_tokens: int) -> dict:
    return create_with_retries(
        client, _stage=stage, _document_id=document_id,
        model=MODEL, max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _data_url(png)}},
        ]}],
    )


def classify_pages(client, pdf: Path, document_id: str,
                   pages: Optional[list] = None) -> dict:
    """Which pages need OCR. Returns {'scanned': [...], 'adjudicated': [...], 'clean': n}.

    Stage 1 sorts by character count; stage 2 sends only the ambiguous band to the model.
    """
    pages = pages if pages is not None else native_pages(pdf)
    scanned, ambiguous = [], []
    for i, txt in enumerate(pages, start=1):
        c = _nonspace(txt)
        if c <= SCANNED_MAX:
            scanned.append(i)
        elif c < CLEAN_MIN:
            ambiguous.append(i)

    adjudicated: list = []
    undecided: list = []
    probe: list = []
    if ambiguous:
        # Cap the vision spend: on a long document the ambiguous band can be dozens of
        # pages, and the marginal one is rarely decisive. Sample evenly across the document
        # rather than taking the first N, so a scanned appendix at the back is still seen.
        probe = ambiguous
        if len(ambiguous) > ADJUDICATE_CAP:
            step = len(ambiguous) / ADJUDICATE_CAP
            probe = [ambiguous[int(i * step)] for i in range(ADJUDICATE_CAP)]

        with tempfile.TemporaryDirectory() as td:
            def one(pno: int):
                png = render_page(pdf, pno, td)
                if png is None:
                    return (pno, None, "render_failed")
                try:
                    prompt = (ADJUDICATE_PROMPT + "\n\nEXTRACTED TEXT:\n"
                              + (pages[pno - 1] or "")[:3000])
                    r = _vision_call(client, png, prompt, "ocr_detect", document_id,
                                     ADJUDICATE_MAX_TOKENS)
                    return (pno, bool(r.get("needs_ocr")), "")
                except Exception as exc:
                    # A failed adjudication is NOT a verdict of "clean". Returning None here
                    # would make a broken vision endpoint look exactly like a document that
                    # needs no OCR, and the whole point of this stage is the pages a
                    # character count cannot judge. Surface it instead.
                    return (pno, None, type(exc).__name__)
            with ThreadPoolExecutor(max_workers=min(OCR_CONCURRENCY, len(probe))) as ex:
                verdicts = list(ex.map(one, probe))
            adjudicated = [pno for pno, need, _ in verdicts if need is True]
            undecided = [(pno, why) for pno, need, why in verdicts if need is None]

    return {"scanned": scanned, "adjudicated": sorted(adjudicated),
            "clean": len(pages) - len(scanned) - len(adjudicated),
            "n_pages": len(pages), "n_ambiguous": len(ambiguous),
            "n_probed": len(probe) if ambiguous else 0,
            "undecided": undecided}


def ocr_pages(client, pdf: Path, document_id: str, page_nos: list) -> dict:
    """Transcribe the given pages via the SOM vision model. Returns {page_no: text}."""
    if not page_nos:
        return {}
    out: dict = {}
    with tempfile.TemporaryDirectory() as td:
        def one(pno: int):
            png = render_page(pdf, pno, td)
            if png is None:
                return pno, None
            try:
                r = _vision_call(client, png, TRANSCRIBE_PROMPT, "ocr_page",
                                 document_id, 8000)
                return pno, str(r.get("text") or "")
            except Exception:
                return pno, None
        with ThreadPoolExecutor(max_workers=min(OCR_CONCURRENCY, len(page_nos))) as ex:
            for pno, text in ex.map(one, page_nos):
                if text is not None:
                    out[pno] = text
    return out


def build_override(client, pdf: Path, document_id: str,
                   force_pages: Optional[list] = None) -> dict:
    """Detect, OCR and write cache/ocr_text/<document_id>.txt. Returns a status record."""
    pages = native_pages(pdf)
    if not pages:
        return {"document_id": document_id, "status": "no_pages"}

    cls = ({"scanned": force_pages, "adjudicated": [], "clean": len(pages) - len(force_pages),
            "n_pages": len(pages), "n_ambiguous": 0}
           if force_pages else classify_pages(client, pdf, document_id, pages))
    targets = sorted(set(cls["scanned"]) | set(cls["adjudicated"]))
    if not targets:
        return {"document_id": document_id, "status": "no_ocr_needed", **cls}

    got = ocr_pages(client, pdf, document_id, targets)
    merged = list(pages)
    swapped = 0
    for pno, text in got.items():
        # Only adopt OCR that actually recovers more than the native layer had. This guards
        # against a vision call that returns a summary or an apology instead of a
        # transcription and would otherwise destroy a readable page.
        if _nonspace(text) > _nonspace(pages[pno - 1]) + MIN_GAIN_CHARS:
            merged[pno - 1] = text
            swapped += 1

    if swapped == 0:
        return {"document_id": document_id, "status": "ocr_no_gain",
                "targets": len(targets), **cls}

    # Assert alignment: a merged file with a different page count than the source silently
    # corrupts every page citation downstream, which is worse than shipping no override.
    if len(merged) != len(pages):
        return {"document_id": document_id, "status": "page_misalignment",
                "expected": len(pages), "got": len(merged)}

    OCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    (OCR_TEXT_DIR / f"{document_id}.txt").write_text("\f".join(merged), encoding="utf-8")
    return {"document_id": document_id, "status": "ocr_written",
            "pages_ocred": swapped, "targets": len(targets), **cls}


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Remote scan detection + OCR via the SOM API.")
    ap.add_argument("pdf")
    ap.add_argument("--document-id", default="")
    ap.add_argument("--detect-only", action="store_true")
    ap.add_argument("--pages", default="", help="comma list, skip detection")
    args = ap.parse_args()
    pdf = Path(args.pdf)
    did = args.document_id or pdf.stem
    store.get_store().start_run(notes=f"ocr_remote {pdf.name}")
    client = get_client()
    if args.detect_only:
        print(json.dumps(classify_pages(client, pdf, did), indent=2))
    else:
        forced = [int(x) for x in args.pages.split(",") if x.strip()] or None
        print(json.dumps(build_override(client, pdf, did, forced), indent=2))
