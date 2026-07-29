# Task: davis_school_district__davis_2019_2020__cc60f6a3__3-3

## Instructions
You are extracting a teacher salary schedule table from a U.S. public school district employment contract.

You will be given the text (or page image) of one or more contiguous pages. The page(s) may contain a full salary-schedule table: a grid of dollar amounts indexed by a row axis (such as step number, years of service, or a salary "level" code) and, often but not always, a column axis (such as degree/lane: BA, BA+30, MA, MA+45, Doctorate, or a classification code). Some schedules have only one axis (a single ordered list of salary levels with no separate lane dimension) — that is normal; do not invent a lane axis that is not in the document.

Preserve the exact row and column labels used in the document (e.g. "Step 1", "BA+30", "Salary Level A", "CLASS III", "14B"). If a cell has a sub-code in addition to a dollar value (e.g. "T02-14B  $66,655"), record the sub-code separately from the value.

Return ONLY a valid JSON object, no markdown fences, with this exact shape:
{
  "has_table": true | false,
  "schedule_label": "<title as written in the document>",
  "school_year_or_effective_date": "<as stated, empty string if not stated>",
  "lane_labels": ["<column labels in left-to-right order, or [] if no lane axis>"],
  "step_labels": ["<row labels in top-to-bottom order>"],
  "cells": [
    {"step": "<step label>", "lane": "<lane label, or null if no lane axis>",
     "value": "<dollar amount, digits only, no $ or commas>",
     "cell_code": "<sub-code if present, else null>"}
  ],
  "notes": "<footnotes, caveats, or empty string>",
  "confidence": "high" | "medium" | "low"
}

If the page(s) do not actually contain a salary schedule table, return
has_table=false and leave the other fields empty. Extract every cell you can
read; do not summarize, sample, or truncate the table.

## Input
Document: Davis_2019-2020.pdf
Extract the salary schedule table from the page image(s) listed below.

## Page image(s) — read each of these with your file-reading tool:
- /Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/salary_schedule_tasks/images/davis_school_district__davis_2019_2020__cc60f6a3__3-3/page-03.png
- /Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/salary_schedule_tasks/images/davis_school_district__davis_2019_2020__cc60f6a3__3-3/page-04.png

## What to do
Read the instructions and input above and the page image(s) listed. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/salary_schedule_tasks/davis_school_district__davis_2019_2020__cc60f6a3__3-3.response.json`
Then re-run the script that printed this task to continue.