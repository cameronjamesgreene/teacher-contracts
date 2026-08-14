# Salary extraction — target pipeline

Produces `salary_long.csv` in the shape of `scripts/salary_schema.py::PayCell`: one row per
pay cell, analysis-ready, with the day-basis and pay-basis that the current wide CSVs drop.

The organising rule is the one that took the 106-question extractor from ~86% to ~95%:
**the host owns everything determinate; the model owns only judgement.** Today salary does
the opposite — `extract_structured_grids()` recovers the exact matrix from PDF
coordinates, serialises it to a pipe-table, and asks the model to retype it under the
instruction "NEVER copy one column's values into another". Fidelity by promise. UTLA p339
is what that buys: the host had the right matrix, and the emitted grid duplicated the
annual column over the monthly one and pulled `20 D / B basis` from row 33D.

**28,241 numeric cells currently round-trip through the model. Under this design, zero do.**

## Stages

### 0 — Page → word boxes (deterministic, no API)

Vector boxes via `pdfplumber.extract_words()`; Apple Vision boxes at 300 DPI only where a
page has no text layer. One clustering routine, two box sources — the code already exists
in `verify_salary_grids.py`, where it is used to *audit* rather than to *extract*.

Guard: refuse a page whose word coordinates fall outside its own declared box. Cleveland
is the only such document in 42 (tops of −152 on a 655pt page, values that are not what
poppler renders); it falls through to vision and is marked lower-confidence rather than
silently trusted.

### 1 — Boxes → table regions (deterministic, no API)

Column clustering on x, row clustering on y, region splits on x-gaps for side-by-side
layouts, step-sequence restart for continuations. `salary_segment.py` already implements
the fingerprinting and region logic. This is the stage that must be right, because
Philadelphia p157 prints twelve pay grades in two columns and Cleveland p162 stacks three
schedules, and both are currently handled by luck.

Emits a matrix plus a row/column count, which restores the **truncation** measure v12 lost
(`expected_cells` is unpopulated for all 431 rows today, so a grid that stops early scores
perfectly).

### 2 — Parse what is parseable (deterministic, no API)

`salary_schema.py` handles: money, step numbers (`1-` → 1), degree lanes (`BA+45` → BA/45),
dated headers (`9/1/21`, `September 2011` → ISO), grade/step composites, day ranges,
`value_kind` (`Total Increase` → `increase_delta`), and `days_per_year` from page prose
("Matrices AT-1, AT-2 and AT-3: 184 days" → 184).

Measured on the real corpus this already resolves the lane type for the two dominant
families — 72 grids use dated columns, 35 use degree lanes.

### 3 — One small call per page-range (the ONLY model stage)

**216 calls for the whole corpus** (431 grids share 216 page-ranges, mean 2.0 grids/page).

Sent: column headers, up to three row labels per grid, the page's non-table prose
(truncated), and the deterministic guesses from stage 2 for confirmation.
**Never sent: the numbers.**

Asked for, per grid — five low-cardinality judgements, all from closed lists:

| field | vocabulary |
|---|---|
| `employee_group` | `EMPLOYEE_GROUPS` (16 values) |
| `lane_type` | `LANE_TYPES` (6) — only where stage 2 returned `none` |
| `pay_basis` | `PAY_BASES` (7) |
| `step_kind` | `STEP_KINDS` (7) |
| `days_per_year` | integer or null, only if the page states it |

An answer outside the vocabulary is a validation failure, not a new category — which is
what makes this checkable in a way "transcribe the table" never was.

### 4 — Join and emit (deterministic, no API)

Labels from stage 3 join onto the matrix from stage 1. Values and positions are correct by
construction because they never left the host.

### 5 — Verify (deterministic, no API)

Independent reconstruction of the page, cell-level agreement, stamped per row as
`cell_verified` / `cell_agreement`. Method-aware bands: 0.95 for vector geometry, 0.90 for
OCR (agreement with an OCR reference is bounded by the OCR's own cell accuracy).

Deduplicate on the content hash of the emitted matrix — 20 grids today are exact
duplicates, 16 of them Pittsburgh, produced from overlapping page windows.

## SOM API budget

The endpoint is the binding constraint, so the design is shaped around it.

| | today | this design |
|---|---|---|
| calls | 431 (229 with a rendered page image) | **216**, text only |
| numeric cells through the model | 28,241 | **0** |
| est. input tokens | large — full matrices + 220 DPI images | ~151k |
| est. output tokens | full matrices retyped | ~54k |

Operational settings, all learned the hard way in this pipeline:

- `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` — measured 62.3s → 9.6s
  on a real extraction prompt with identical output. Nothing here needs deliberation.
- **Concurrency 8.** The measured endpoint ceiling is ~24–32 in flight; salary and rights
  already fan out internally, and a dropped connection at 24 in-flight silently voided 41%
  of one document's windows.
- **Separate retry budgets.** `APITimeoutError` is a subclass of `APIConnectionError`;
  catching connection errors first gave timeouts a 12-attempt/30s-backoff budget and
  blocked workers for 2.1 hours per batch. Timeouts get 3 attempts, connections get 12.
- **Forced tool call** for stage 3 rather than free JSON. Tool calling is confirmed working
  on `api.som.chat` with `Qwen3.6-35B-A3B-FP8`, and a forced schema removes the parse-retry
  loop entirely.
- **Per-page cache** keyed on (document_id, page-range, prompt hash), so a re-run after a
  parser change costs only the pages whose input actually changed.

At 8 concurrent and ~10s per call, stage 3 is roughly **4–5 minutes for the whole corpus**,
against multi-hour runs today. The deterministic stages are CPU-bound and parallel-safe.

## What this does not solve

- **Lane labels were never audited.** Making labelling the model's entire job concentrates
  all remaining risk in the one component the audit has never checked. The next audit must
  verify `employee_group` / `lane_type` / `pay_basis`, or this moves error rather than
  removing it.
- **Cleveland** still needs vision, and vision-transcribed grids should never enter the
  verified tier silently.
- **Plausibility checks are not safe.** Albuquerque's Level 1 matrix really does run
  $36,000 → $36,001 → $36,002 (pinned to a statutory minimum). A monotonic-increment or
  range validator would reject a byte-perfect extraction.
