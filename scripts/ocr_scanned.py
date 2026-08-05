#!/usr/bin/env python3
"""OCR the scanned documents on HPC GPUs, into the pipeline's text format.

Six of the 42 documents are image-only scans holding roughly one character per page, so
they are invisible to indexing, retrieval and extraction — 14% of districts silently absent
from every result, with nothing in the output to say so. 299 pages in total.

## Engine: olmOCR-2 on the SOM HPC GPUs

This wraps `hpc/client/vllm_http_client.py` from `yale-som-hpc/ocr-examples`, which serves
`allenai/olmOCR-2-7B-1025` under vLLM on a GPU compute node and streams pages to it over an
SSH tunnel. **PDFs never land on HPC disk**: the client reads them locally, vLLM holds the
request bytes in memory, and the text comes back to the local filesystem.

A vision-language model was chosen over Apple's on-device Vision OCR after trying both.
Apple Vision is much faster per page and matched olmOCR-2 on extracted figures, but it
returns text *fragments with bounding boxes in arbitrary order*, so using it means
reconstructing reading order by clustering fragments into lines — bespoke geometry code on
the critical path of every citation, which is a poor thing to own. olmOCR-2 returns
reading-ordered text natively and is also cleaner on prose: Apple Vision has a recognisable
f-to-t confusion ("eftective" for "effective") that olmOCR-2 does not.

## Page boundaries

The client emits `<!-- page N -->` markers; those are converted to form feeds here, matching
what `pdftotext -layout` produces. This is not cosmetic — every citation page in this
pipeline is derived from form-feed position, so one block per page is what keeps page
numbers correct.

## Prerequisites

- SSH access to the HPC login node. Set `HPC_USER` to your cluster username and `HPC_KEY`
  to the private key that authenticates you there; `HPC_HOST` overrides the default host.
- A checkout of `yale-som-hpc/ocr-examples`, passed with `--ocr-examples`, and the same
  repo present in the HPC home directory (the Slurm service script is read from there).
- `uv`, used to run the client with its inline dependencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import WORK

MANIFEST = WORK / "output" / "extraction" / "corpus_manifest.csv"
TEXT_DIR = WORK / "cache" / "extracted_text"
# The image/model pair the reference repo pins for olmOCR-2; kept identical so this
# inherits whatever compatibility testing that repo has done.
HPC_MODEL = "allenai/olmOCR-2-7B-1025"
HPC_IMAGE = "docker://vllm/vllm-openai:v0.23.0"
PAGE_MARKER = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
RENDER_DPI = 200
PAGE_CACHE = WORK / "cache" / "ocr_pages"


def render_pages(pdf: Path, out_dir: Path) -> list[Path]:
    """Render each page to PNG once, cached, so engines see identical input."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("page-*.png"))
    if existing:
        return existing
    subprocess.run(["pdftoppm", "-r", str(RENDER_DPI), "-png", str(pdf),
                    str(out_dir / "page")], check=True, capture_output=True)
    return sorted(out_dir.glob("page-*.png"))


def ocr_apple_vision(png: Path) -> str:
    """Apple's on-device Vision OCR, with reading order rebuilt from bounding boxes.

    Retained deliberately as the *second* engine for reconciliation, not as the text of
    record. It is the measured figure authority — 3 of 3 verified figures against every
    vision model's 0 of 3 — and the geometry code below is the price of that. Vision returns
    fragments with bottom-left-origin boxes in arbitrary order, so lines are rebuilt by
    vertical band and then left to right; without it the text is shuffled.
    """
    from ocrmac import ocrmac
    annotations = ocrmac.OCR(str(png), recognition_level="accurate").recognize()
    fragments = [(round(box[1] + box[3] / 2, 3), box[0], text)
                 for text, _confidence, box in annotations]
    if not fragments:
        return ""
    fragments.sort(key=lambda item: (-item[0], item[1]))
    lines: list[list] = [[fragments[0]]]
    for fragment in fragments[1:]:
        if abs(fragment[0] - lines[-1][0][0]) < 0.008:
            lines[-1].append(fragment)
        else:
            lines.append([fragment])
    return "\n".join(" ".join(text for _, _, text in sorted(line, key=lambda i: i[1]))
                     for line in lines)


def run_apple_vision(rows: list[dict], out_dir: Path) -> list[dict]:
    """Write one page-marked markdown per document, matching the HPC client's format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for row in rows:
        pdf = Path(row["source_path"])
        if not pdf.is_absolute():
            pdf = WORK / pdf
        pages = render_pages(pdf, PAGE_CACHE / row["document_id"])
        started = time.monotonic()
        texts = []
        for png in pages:
            try:
                texts.append(ocr_apple_vision(png))
            except Exception:
                texts.append("")
        (out_dir / f"{pdf.stem}.md").write_text(
            "".join(f"<!-- page {i} -->\n{t}\n" for i, t in enumerate(texts, 1)),
            encoding="utf-8")
        reports.append({"document_id": row["document_id"], "district": row["district"],
                        "engine": "apple_vision", "pages": len(texts),
                        "characters": sum(len(t) for t in texts),
                        "seconds": round(time.monotonic() - started, 1)})
        print(f"  {row['district'][:34]:36s} {len(texts):>4}pp "
              f"{reports[-1]['characters']:>9,} chars "
              f"{reports[-1]['seconds']:>6.1f}s", flush=True)
    return reports


def scanned_documents(document_ids: list[str] | None = None) -> list[dict]:
    """Documents needing OCR, or the named ones regardless of status.

    Naming documents explicitly has to bypass the status filter: once a scan has been OCR'd
    the manifest marks it usable, and re-OCRing it — with another engine, for reconciliation —
    is a normal thing to want.
    """
    with MANIFEST.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if document_ids:
        wanted = set(document_ids)
        return [row for row in rows if row["document_id"] in wanted]
    return [row for row in rows if row["text_status"] != "usable"]


def markdown_to_pages(markdown: str) -> list[str]:
    """Split the client's output on its page markers, preserving empty pages.

    Empty pages must survive as empty blocks. Dropping them would shift every later
    page number by one and silently corrupt citations for the rest of the document.
    """
    parts = PAGE_MARKER.split(markdown)
    if len(parts) < 3:
        return [markdown.strip()]
    pages: dict[int, str] = {}
    for index in range(1, len(parts) - 1, 2):
        pages[int(parts[index])] = parts[index + 1].strip()
    return [pages.get(number, "") for number in range(1, max(pages) + 1)]


def run_client(client: Path, pdf_paths: list[Path], out_dir: Path, workers: int,
               in_flight: int, partition: str, gres: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as listing:
        listing.write("\n".join(str(path) for path in pdf_paths) + "\n")
        pdf_list = Path(listing.name)
    command = ["uv", "run", "--script", str(client),
               "--pdf-list", str(pdf_list), "--out-dir", str(out_dir),
               "--workers", str(workers), "--in-flight", str(in_flight),
               "--model", HPC_MODEL, "--image", HPC_IMAGE,
               "--partition", partition, "--gres", gres]
    environment = dict(os.environ)
    environment.setdefault("HPC_HOST", "hpc.som.yale.edu")
    # Stream rather than capture. A large document can occupy a worker for tens of
    # minutes, and swallowing the client's per-document progress lines makes a slow run
    # indistinguishable from a hung one.
    interesting = ("[done]", "[orch]", "[ready]", "[err", "SUMMARY")
    try:
        process = subprocess.Popen(command, cwd=client.parent.parent.parent,
                                   env=environment, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   bufsize=1)
        for line in process.stdout:
            if line.startswith(interesting):
                print(f"  {line.rstrip()}", flush=True)
        code = process.wait(timeout=6 * 3600)
    finally:
        pdf_list.unlink(missing_ok=True)
    if code != 0:
        raise SystemExit(f"vllm_http_client exited {code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("olmocr2", "apple_vision"), default="olmocr2",
                        help="olmocr2 runs on HPC GPUs; apple_vision runs locally and is the "
                             "second engine for reconciliation")
    parser.add_argument("--ocr-examples", type=Path,
                        help="path to a yale-som-hpc/ocr-examples checkout (olmocr2 only)")
    parser.add_argument("--document-id", action="append",
                        help="default: every document that needs OCR")
    parser.add_argument("--workers", type=int, default=2, help="parallel GPU workers")
    parser.add_argument("--in-flight", type=int, default=8, help="pages in flight per worker")
    parser.add_argument("--partition", default="gpunormal")
    parser.add_argument("--gres", default="gpu:1",
                        help="'gpu:a100:1' to insist on an A100")
    parser.add_argument("--md-dir", type=Path,
                        help="keep the raw markdown here (default: a temp dir)")
    parser.add_argument("--out-dir", type=Path,
                        help="default: cache/extracted_text, i.e. adopt into the pipeline")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    rows = scanned_documents(args.document_id)
    if not rows:
        raise SystemExit("no matching documents need OCR")

    md_dir = args.md_dir or Path(tempfile.mkdtemp(prefix="ocr-md-"))
    md_dir.mkdir(parents=True, exist_ok=True)

    if args.engine == "apple_vision":
        reports = run_apple_vision(rows, md_dir)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(reports)} documents to {md_dir}")
        return

    if not args.ocr_examples:
        raise SystemExit("--ocr-examples is required for the olmocr2 engine")
    client = args.ocr_examples / "hpc" / "client" / "vllm_http_client.py"
    if not client.exists():
        raise SystemExit(f"client not found at {client}")
    by_stem = {Path(row["source_path"]).stem: row for row in rows}
    print(f"{len(rows)} documents, {sum(int(r['pdf_pages'] or 0) for r in rows)} pages "
          f"-> olmOCR-2 on {args.partition}", flush=True)

    def source(row: dict) -> Path:
        path = Path(row["source_path"])
        return path if path.is_absolute() else WORK / path

    started = time.monotonic()
    run_client(client, [source(row) for row in rows], md_dir,
               args.workers, args.in_flight, args.partition, args.gres)
    elapsed = time.monotonic() - started

    target_dir = args.out_dir or TEXT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for markdown_path in sorted(md_dir.glob("*.md")):
        row = by_stem.get(markdown_path.stem)
        if row is None:
            print(f"  ! no manifest row for {markdown_path.name}", flush=True)
            continue
        pages = markdown_to_pages(markdown_path.read_text(encoding="utf-8"))
        (target_dir / f"{row['document_id']}.txt").write_text(
            "\f".join(pages), encoding="utf-8")
        characters = sum(len(page) for page in pages)
        reports.append({
            "document_id": row["document_id"], "district": row["district"],
            "engine": "olmocr2-hpc", "expected_pages": int(row["pdf_pages"] or 0),
            "pages": len(pages), "characters": characters,
            "chars_per_page": round(characters / max(1, len(pages))),
            "empty_pages": sum(1 for page in pages if not page.strip()),
        })
        flag = "" if reports[-1]["pages"] == reports[-1]["expected_pages"] else "  ! PAGE COUNT MISMATCH"
        print(f"  {row['district'][:34]:36s} {len(pages):>4}pp "
              f"{characters:>9,} chars{flag}", flush=True)
    print(f"total {elapsed / 60:.1f} min", flush=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
