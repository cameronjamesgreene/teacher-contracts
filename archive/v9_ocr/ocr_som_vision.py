#!/usr/bin/env python3
"""OCR scanned / image-only PDFs via the Yale SOM vision LLM (existing SOM key).

Renders each page with pdftoppm, sends it to the SOM vision model for a verbatim
transcription, caches PER PAGE (so a run is resumable across SOM API
outages/rate-limits), and writes a page-delimited (\\f-separated) text file to
cache/ocr_text/<document_id>.txt -- the OCR override slot that
utils.extract_text() prefers, so all three pipelines pick it up with no further
change.

SCOPE NOTE: this is the expedient path for the handful of image-only docs in the
current 40-doc sample. It is NOT the scale path -- a single SOM endpoint at
~10s/page does not scale to thousands of districts. For that, use HPC batch OCR
(docling/olmocr2 via yale-som-hpc/ocr-examples).

Usage:
  python3 ocr_som_vision.py                      # every staged doc in ocr_manifest
  python3 ocr_som_vision.py --uuid <uuid>        # one staged doc (repeatable)
  python3 ocr_som_vision.py --uuid <uuid> --max-pages 2   # smoke test
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

import openai
from som_client import MODEL, get_client

WORK = Path(__file__).resolve().parents[1]
STAGE = WORK / "cache" / "ocr_documents"
DOCS = STAGE / "documents"
OCR_TEXT_DIR = WORK / "cache" / "ocr_text"
PAGE_CACHE = WORK / "cache" / "ocr_som_cache"

DPI = 300
MAX_TOKENS = 12000
MAX_RETRIES = 5
PROMPT = (
    "Transcribe ALL text on this page VERBATIM. Preserve line breaks, bullet and "
    "indent structure, table rows, and every number and dollar amount exactly as "
    "written. Do not summarize, paraphrase, add, or omit anything. If the page is "
    "blank, output nothing. Output ONLY the transcription, with no commentary."
)


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def render_page(pdf: Path, n: int, tmpdir: str) -> Path | None:
    prefix = Path(tmpdir) / f"p{n}"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), "-f", str(n), "-l", str(n), str(pdf), str(prefix)],
        check=True,
    )
    pngs = sorted(Path(tmpdir).glob(f"p{n}*.png"))
    return pngs[0] if pngs else None


def ocr_page(client, png: Path) -> str:
    url = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")
    last: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": url}},
                ]}],
                max_tokens=MAX_TOKENS,
                temperature=0,
            )
            choice = resp.choices[0]
            if choice.message.content is None or choice.finish_reason == "length":
                raise RuntimeError(f"truncated (finish_reason={choice.finish_reason})")
            return choice.message.content.strip()
        except Exception as exc:  # noqa: BLE001 -- transient SOM backend/ratelimit
            last = exc
            if attempt < MAX_RETRIES:
                time.sleep(60 if isinstance(exc, openai.RateLimitError) else 5 * attempt)
                continue
            raise
    raise last  # pragma: no cover


def process(client, doc_uuid: str, document_id: str, max_pages: int | None) -> int:
    pdf = DOCS / doc_uuid / "document.pdf"
    total = page_count(pdf)
    if max_pages:
        total = min(total, max_pages)
    cache = PAGE_CACHE / document_id
    cache.mkdir(parents=True, exist_ok=True)
    print(f"[{document_id}]  {total} page(s)")

    t0 = time.time()
    for i in range(1, total + 1):
        pc = cache / f"p{i:04d}.txt"
        if pc.exists():
            continue
        with tempfile.TemporaryDirectory() as td:
            png = render_page(pdf, i, td)
            if png is None:
                pc.write_text("", encoding="utf-8")
                continue
            try:
                text = ocr_page(client, png)
            except Exception as exc:  # noqa: BLE001
                # Don't cache failures -> the page retries on the next run.
                print(f"   p{i}: FAILED ({type(exc).__name__}: {exc}) -- retry next run")
                continue
        pc.write_text(text, encoding="utf-8")
        if i % 10 == 0 or i == total:
            el = time.time() - t0
            print(f"   {i}/{total} pages  ({el / i:.1f}s/pg)")

    # Assemble in page order, form-feed delimited (keeps page structure for the
    # downstream pipelines that split on \f).
    pages, missing = [], 0
    for i in range(1, total + 1):
        pc = cache / f"p{i:04d}.txt"
        if pc.exists():
            pages.append(pc.read_text(encoding="utf-8"))
        else:
            pages.append("")
            missing += 1
    OCR_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    out = OCR_TEXT_DIR / f"{document_id}.txt"
    out.write_text("\f".join(pages), encoding="utf-8")
    tag = "COMPLETE" if missing == 0 else f"PARTIAL ({missing} page(s) missing -- re-run to fill)"
    print(f"   -> wrote {out} [{tag}]")
    return missing


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uuid", action="append", help="Process a specific staged UUID (repeatable)")
    ap.add_argument("--max-pages", type=int, default=None, help="Cap pages per doc (smoke test)")
    args = ap.parse_args()

    uuid_map = json.loads((STAGE / "uuid_to_document_id.json").read_text(encoding="utf-8"))
    targets = args.uuid or list(uuid_map.keys())
    targets = [u for u in targets if (DOCS / u / "document.pdf").exists()]
    if not targets:
        raise SystemExit("No staged (hydrated) documents to process. Run prep_ocr_batch.py first.")

    client = get_client()
    total_missing = 0
    for u in targets:
        total_missing += process(client, u, uuid_map[u], args.max_pages)
    print(f"\nDone. {len(targets)} doc(s) processed. Pages still missing: {total_missing}"
          + ("" if total_missing == 0 else " -- re-run to fill (SOM API retries)."))


if __name__ == "__main__":
    main()
