# OCR for the scanned documents

## The problem

Six of the 42 documents were image-only scans holding roughly one character per page. They
were invisible to indexing, retrieval and extraction — 14% of districts silently absent from
every result, with nothing in the output to say so. 299 pages in total.

## Engine: olmOCR-2 on the SOM HPC GPUs

`scripts/ocr_scanned.py` wraps `hpc/client/vllm_http_client.py` from
`yale-som-hpc/ocr-examples`, which serves `allenai/olmOCR-2-7B-1025` under vLLM on a GPU
compute node and streams pages to it over an SSH tunnel.

**PDFs never land on HPC disk.** The client reads them locally, vLLM holds request bytes in
memory only, and the text comes back to the local filesystem. That property is why this path
is usable for documents that should not be stored on shared infrastructure.

### Why not Apple Vision, which was tried first

Apple's on-device Vision OCR is dramatically faster — 3.2 minutes for all 299 pages against
44.2 minutes on HPC — and it matched olmOCR-2 on the figures extracted from identical pages
(19 of 19 on a clean amendment, 70 of 71 on a harder scan). On raw throughput it wins
outright.

It was rejected anyway, for two reasons.

1. **It does not return reading order.** Vision emits text *fragments with bounding boxes in
   arbitrary order*. Using it means clustering fragments into lines by geometry and sorting
   them — bespoke code sitting on the critical path of every citation in the project. A
   subtle bug there would shuffle text and silently break quote grounding on some layouts,
   and nothing downstream would notice. olmOCR-2 returns reading-ordered text natively, so
   that code does not need to exist.
2. **It garbles letters in a recognisable way.** Apple Vision produced "eftective" for
   "effective" and "tacilitate" for "facilitate"; olmOCR-2 got both right. Figures were
   unaffected in testing, but the pipeline matches on *verbatim quoted text*, so corrupted
   words are a live risk to citation matching, not just a cosmetic one.

The earlier four-engine benchmark in `output/ocr_test_output/` had Apple Vision ahead on
fact recall (89.5% against 81.6%) while trailing on character accuracy (94.4% against
97.0%). That was measured on three documents with a small fact set where all three
non-Apple engines scored identically, which is weak evidence for a fact-recall gap; it did
not outweigh owning geometry code.

## Result

299 pages, 44.2 minutes, 3 GPU workers with 12 documents in flight per worker. **Every
document's page count matched its PDF exactly**, which is the check that matters most.

| district | pages | characters | chars/page |
| --- | --- | --- | --- |
| Dayton | 5 | 9,612 | 1,922 |
| Fresno | 142 | 440,364 | 3,101 |
| New York City | 63 | 173,237 | 2,750 |
| Pittsburgh | 34 | 106,758 | 3,140 |
| Sacramento | 47 | 120,443 | 2,562 |
| San Bernardino | 8 | 17,871 | 2,234 |

**The corpus is now 42/42 usable**, up from 36/42, at 12,775 indexed passages. olmOCR-2
recovered noticeably more text per page than Apple Vision did on the same scans (Pittsburgh
3,140 against 2,013 chars/page), which is consistent with it reading table and multi-column
content that fragment-based OCR skips.

## End-to-end check

OCR'd text is only useful if the pipeline can cite it. Full 106-question extraction on
Pittsburgh, an OCR'd document:

| | value |
| --- | --- |
| questions answered | 40 / 106 |
| evidence verbatim | **0.975** |
| evidence contiguous | **0.975** |
| quote on the reported page | 0.950 |
| self-flagged ungrounded | 1 |

So an OCR'd document behaves like a born-digital one. The two exceptions are instructive
rather than alarming: one is the derived text-usability diagnostic, which has no quotable
clause, and the other is a passage spanning a page break, which also occurs on native
documents.

## A trap worth knowing

**Re-running OCR invalidates every prior extraction for that document.** Answers are
grounded against the extracted text, so replacing the text leaves old quotes pointing at
something that no longer exists. When Apple Vision's output was swapped for olmOCR-2's, the
earlier Apple-Vision-based answers dropped from 1.000 to 0.789 on the audit — not because
either engine got worse, but because the answers were being checked against text they were
never derived from. Re-extract after re-OCRing, and treat the OCR engine as part of a
result's provenance.

## Rerun

```sh
export HPC_USER=<your-cluster-username>
export HPC_KEY=~/.ssh/<your-hpc-key>   # private key that authenticates you to the cluster
.venv/bin/python scripts/ocr_scanned.py \
    --ocr-examples /path/to/ocr-examples --workers 3 --in-flight 12 \
    --report output/extraction/ocr_report.json
.venv/bin/python scripts/evaluate_question_extraction.py manifest --out output/extraction/corpus_manifest.csv
.venv/bin/python scripts/sqlite_vectors.py     # embed the new passages
```

Requires an `ocr-examples` checkout locally *and* in the HPC home directory, since the Slurm
service script is read from there. `--gres gpu:a100:1` insists on an A100; the default takes
any GPU. `--document-id` limits the run.

## Scale note

44 minutes for 299 pages is dominated by per-worker model load (~110 s each) and by large
documents monopolising a worker: Fresno's 142 pages alone ran for roughly half the wall
clock. The client already parallelises across documents (`--workers` GPU jobs ×
`--in-flight` documents each), so more workers would help a larger batch, but a single long
document cannot be split across workers. For a corpus-sized OCR job, raise `--workers` to
the number of GPUs available rather than increasing `--in-flight`.
