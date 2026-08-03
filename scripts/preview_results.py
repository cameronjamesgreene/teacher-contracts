"""Read whatever is currently in the llm_cache and write a preview CSV.

Safe to run while llm_extract.py is still running — reads cache files only,
makes zero API calls. Writes to output_v2/llm_main_dataset_preview.csv so it
never overwrites the live output file.
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_extract import (
    _FALLBACK, _write_outputs,
    read_codebook, load_documents, group_by_category, split_into_subbatches,
    build_metadata,
)
from llm_extract import CACHE_DIR
from utils import OUT_DIR, read_sample

PREVIEW_PATH = OUT_DIR / "llm_main_dataset_preview.csv"


def main() -> None:
    questions  = read_codebook()
    docs       = load_documents(read_sample())
    subbatches = split_into_subbatches(group_by_category(questions))

    results = []
    n_complete = 0
    for doc in docs:
        coded: dict[str, dict] = {}
        subbatch_count = len(subbatches)
        cached_count   = 0
        for cat, idx, _batch_qs in subbatches:
            cache_file = CACHE_DIR / f"{doc.document_id}__{cat}_{idx:02d}.json"
            if cache_file.exists():
                cached_count += 1
                coded.update(json.loads(cache_file.read_text(encoding="utf-8")))
        results.append((doc, build_metadata(doc), coded))
        status = "complete" if cached_count == subbatch_count else f"{cached_count}/{subbatch_count} subbatches"
        if cached_count == subbatch_count:
            n_complete += 1
        if cached_count > 0:
            print(f"  {doc.file_name}: {status}")

    # Build wide CSV
    meta_fields = [
        "document_id", "file_name", "district_name", "state",
        "document_type", "bargaining_unit", "start_year", "end_year",
        "effective_dates", "school_years_covered", "union_name",
        "source_document_notes",
    ]
    wide_fields = meta_fields + [
        f"{q.qid}_{suffix}"
        for q in questions
        for suffix in ("answer", "evidence", "page", "confidence")
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with PREVIEW_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=wide_fields, extrasaction="ignore")
        w.writeheader()
        for doc, metadata, coded in results:
            if not coded:
                continue  # skip docs with no cache at all
            row = dict(metadata)
            for q in questions:
                cell = {**_FALLBACK, **coded.get(q.qid, {})}
                row[f"{q.qid}_answer"]      = cell["answer"]
                row[f"{q.qid}_evidence"]    = cell["evidence"]
                row[f"{q.qid}_page"]        = cell["page"]
                row[f"{q.qid}_confidence"]  = cell["confidence"]
            w.writerow(row)

    n_rows = sum(1 for _, _, coded in results if coded)
    print(f"\n{n_rows} documents written ({n_complete} fully complete) → {PREVIEW_PATH}")


if __name__ == "__main__":
    main()
