# How to run this — two options

All commands below are run from inside `contract_coding_CG` (the folder one level
above `scripts/`); the scripts find everything else (codebook, cache, output) on
their own regardless of where they're run from. There are three pipelines, each with
an API version and a no-API ("Codex/Claude Code does it by hand") twin in `scripts/`.
Use whichever matches what you have available — they don't need to match each other
(e.g. you can run `llm_extract.py` with OpenAI and `rights_score_noapi.py` with Codex):

- `llm_extract.py` / `llm_extract_noapi.py` — codes the salary-schedule question (and
  the rest of the question bank) per document. API version calls OpenAI directly.
- `salary_schedule.py` / `salary_schedule_noapi.py` — extracts the actual step/lane
  dollar values from a document's salary table(s). API version calls the Yale SOM API.
- `rights_score.py` / `rights_score_noapi.py` — scores worker rights vs. responsibilities
  per document (see its module docstring for the method and a documented caveat about
  double-counting restated entitlements). API version also calls the Yale SOM API.

Recommended either way: test on Davis School District and Hawaii Department of
Education first (already confirmed working), then Granite School District and
DCPS (`District of Columbia Public Schools`), before running the full 40-document
batch — that lets you sanity-check a few documents' worth of output cheaply before
committing to the whole sample.

## A. Running with Codex (no API key)

Open Codex inside the `contract_coding_CG` folder and give it an instruction like:
"Run `python3 scripts/rights_score_noapi.py --doc \"Davis School District|Davis_2019-2020.pdf\"`.
When it stops and says 'agent action required,' read the task file it names, work
out the answer yourself from the document text (and any page images it lists) in the
task, write your answer as JSON to the response path it names, then re-run the same
command. Keep repeating that until it says 'All documents complete.'" — substitute
`llm_extract_noapi.py` or `salary_schedule_noapi.py` for the other two pipelines; the
loop is identical.

A few things worth telling Codex up front, since they matter for quality: (1) each
task file contains detailed instructions on the exact JSON shape expected — follow
that shape exactly, since a malformed JSON response will break the next step; (2)
for "vision" tasks (table not in the page text), it must actually open and read the
listed PNG image(s) rather than guessing from surrounding text; (3) this is a real,
careful per-document coding task, not a rubber-stamp — it should actually read the
evidence before answering, the same way the audit stage in `llm_extract.py` is
designed to catch weak answers. Per-document cost: 2 tasks for `llm_extract_noapi.py`
(one extract, one self-audit), 1 task per detected salary table for
`salary_schedule_noapi.py`, and 1 task per ~6000-character text chunk for
`rights_score_noapi.py` (a full CBA can be a dozen-plus chunks) — budget Codex's own
session time/usage accordingly, especially beyond the handful of test documents.

## B. Running with an API key

`llm_extract.py` calls OpenAI directly; `salary_schedule.py` and `rights_score.py`
both call the Yale SOM API. Different keys, set up differently:

**OpenAI** (for `llm_extract.py`): get a key from platform.openai.com (billing must
be enabled), then `export OPENAI_API_KEY=sk-...` once per session.

**Yale SOM** (for `salary_schedule.py` / `rights_score.py`): either set
`SOM_API_KEY`, or drop the key into `scripts/som_api_key.txt` (read automatically,
no env var needed). The endpoint currently serves one model, a reasoning model that
can be slow and has been observed to intermittently return "backend_unavailable" —
both scripts retry automatically, but a fully down backend will still fail after
retries; just try again later.

From inside `contract_coding_CG`:

```
python3 scripts/llm_extract.py
python3 scripts/salary_schedule.py
python3 scripts/rights_score.py --doc "Davis School District|Davis_2019-2020.pdf"
```

`llm_extract.py` codes the 40-document sample and writes `output/llm_main_dataset.csv`
and `output/llm_coding_log.csv` (results are cached per document, so it's safe to
stop and rerun). `salary_schedule.py` then reads that CSV, finds every document
where the salary-schedule question was answered "yes," and writes one grid file per
table (step rows × lane columns) under `output/salary_schedule_wide/<district>/<school year>/`
— no long/cell-per-row CSV. `rights_score.py` defaults to the same 40-document sample (or point it
at specific documents with `--doc "District|file.pdf"`, repeatable, or
`--district`/`--file`) and writes `output/rights_score_long.csv` (one row per
clause, including a `topic` tag) and `output/rights_score_summary.csv` (one row per
document). Both scripts accept `--max-docs N` to limit a full-sample run. To test
`salary_schedule.py` on just one document instead of the full batch:

```
python3 scripts/salary_schedule.py --district "Granite School District" --file "professional_agreement_with_gea_2020_2023.pdf"
python3 scripts/salary_schedule.py --district "District of Columbia Public Schools" --file "DCPS_WTU_CBA_2023-2028.pdf"
```

Either way, spot-check a handful of rows in the output CSVs against the actual PDF
before treating the results as final — none of these paths have a guarantee of
catching every transcription/classification error on their own.
