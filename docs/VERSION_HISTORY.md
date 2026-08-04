# Version history — what survives, and what does not

## Corrected 2026-08-04: v10 *is* preserved on GitHub.

The `teacher-contracts` repo (github.com/cameronjamesgreene/teacher-contracts, commit
`f85690b` "first upload to git for meeting with Kyle") contains a full snapshot of the
pipeline whose `scripts/*.py` are **byte-identical to the v10 baseline** — som_client,
llm_extract, salary_schedule, rights_score and utils all match commit `d1da2c3` exactly.
So v10 code is recoverable, and a v10-vs-v11 diff is possible.

v1–v9 remain unrecoverable. The statement below applies to those.

## There is no code history for v1–v9.

`git init` was run on 2026-08-03, at the start of the v11 work. The first commit
(`d1da2c3`, "Baseline: v10 pipeline as deployed") is a snapshot of v10 as it stood that
day. Everything before it is unrecoverable: each version edited `scripts/*.py` **in place**
and was synced to the HPC by `scp`, which overwrites. There are no dated copies, no `.bak`
files, no tags, no branches. The `cache/_v6_/_v7_/_v8_bak` directories on the HPC are
CACHES, not code.

Consequences, stated plainly:

* We cannot diff v8 against v9, or reproduce any pre-v10 result. (v10 vs v11 IS diffable,
  via the teacher-contracts snapshot.)
* We cannot attribute an accuracy change to a code change for any version before v11.
* The rights polarity inversion found in the v11 audit is present in `classify_statement_type`
  in the v10 snapshot, but we still cannot say when it was introduced.
* Every audit workbook v1–v10 grades a code state that no longer exists in retrievable form.

## What DOES survive: results and audits

Reconstructed from file mtimes and the `document_id` values inside each version's CSVs.
Dates are filesystem mtimes and are approximate — Dropbox sync can rewrite them.

| version | first | last | files | docs coded | audit workbook |
|---|---|---|---|---|---|
| `output` | 2026-05-28 | 2026-07-28 | 52 | 2 | audit_report.xlsx |
| `output_v2` | 2026-07-01 | 2026-07-20 | 58 | 2 | audit_report_2.xlsx |
| `output_v3` | 2026-05-27 | 2026-07-20 | 25 | 1 | audit_report_v3_olmocr2.xlsx |
| `output_v4` | 2026-07-20 | 2026-07-20 | 32 | 1 | audit_report_v4_olmocr2.xlsx |
| `output_v5` | 2026-07-20 | 2026-07-20 | 36 | 1 | audit_report_v5_olmocr2.xlsx |
| `output_v6` | 2026-07-20 | 2026-07-21 | 85 | 3 | audit_report_v6_olmocr2.xlsx |
| `output_v7` | 2026-07-21 | 2026-07-21 | 131 | 3 | audit_report_v7_olmocr2.xlsx |
| `output_v8` | 2026-07-21 | 2026-07-22 | 64 | 1 | audit_report_v8_olmocr2.xlsx |
| `output_v9` | 2026-07-22 | 2026-08-03 | 402 | 15 | audit_report_v9.xlsx |
| `output_v10` | 2026-07-27 | 2026-07-27 | 3 | 0 | audit_report_v10 copy.xlsx |
| `output_v11` | 2026-08-04 | 2026-08-04 | 102 | 10 | audit_report_v11.xlsx |

Also surviving: `archive/` holds pre-v1 material (the original `extraction_elements.md`,
`llm_agent_prompt.md`, `merge_llm_parts.py`, and the June DCPS manual-verification
workbooks), and the HPC keeps driver scripts that were never copied down
(`run_new15.py`, `ramp_driver.py`, `run_c6.py`, `verify_v4_full.py`).

## From v11 onward

Every change is committed with the measurement that motivated it. `store.py` records
`run.git_rev` per run, and `som_client.request_cache_key` hashes the prompt version into
every cache entry, so a result can be traced to the code that produced it. That was not
true for any earlier version.

## Done 2026-08-04

1. Tagged `v11`; pushed tag to the remote.
2. Pushed the full 17-commit history to
   `github.com/cameronjamesgreene/teacher-contracts` as branch **`v11-overhaul`**.
   `main` is untouched and still holds the v10 snapshot, so the two are directly comparable.
3. Audit workbooks for every version are now force-tracked in git — previously they sat
   untracked under gitignored `output_v*/` directories and were the only surviving record of
   v1–v10 quality.

## Still recommended

* Tag each future version at the commit that produced its run, rather than reconstructing
  from mtimes afterwards.
* `teacher-contracts` tracks 9,279 `cache/*.json` files and carries a 417 MB `.git`. Those
  are regenerable API-response caches; gitignoring them would shrink the repo substantially.
  This overhaul's repo excludes them deliberately (56 tracked files).
