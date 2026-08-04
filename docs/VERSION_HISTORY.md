# Version history — what survives, and what does not

## The honest answer: there is NO code history for v1–v10.

`git init` was run on 2026-08-03, at the start of the v11 work. The first commit
(`d1da2c3`, "Baseline: v10 pipeline as deployed") is a snapshot of v10 as it stood that
day. Everything before it is unrecoverable: each version edited `scripts/*.py` **in place**
and was synced to the HPC by `scp`, which overwrites. There are no dated copies, no `.bak`
files, no tags, no branches. The `cache/_v6_/_v7_/_v8_bak` directories on the HPC are
CACHES, not code.

Consequences, stated plainly:

* We cannot diff v9 against v10, or reproduce any pre-v11 result.
* We cannot attribute an accuracy change to a code change for any version before v11.
* The rights polarity inversion found in the v11 audit is present in `classify_statement_type`
  as of the v10 baseline commit, but we cannot say when it was introduced.
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

## Recommended, not yet done

1. `git tag v11` at the current commit, and tag each future version at its run commit.
2. Push to a private remote. Right now the only copy of the history is this laptop; the HPC
   has the working tree but not the `.git` directory.
3. Commit the audit workbooks alongside the code that produced them (currently `output_v*/`
   is gitignored as bulk output, so the workbooks are untracked).
