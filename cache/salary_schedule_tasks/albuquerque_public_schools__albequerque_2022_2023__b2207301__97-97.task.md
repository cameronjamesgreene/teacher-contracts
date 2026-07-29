# Task: albuquerque_public_schools__albequerque_2022_2023__b2207301__97-97

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
Document: Albequerque_2022-2023.pdf

---PAGE TEXT---
APPENDIX A – SALARY MATRICES
                          Salary matrices for the 2022-2023 school year for the
                           Albuquerque Teachers Federation Bargaining Unit

 The Albuquerque Public Schools and the Albuquerque Teachers Federation agree to the following for the
 2022-2023 school year:
       All employees on Salary Matrix AT1 will start at $50,000 base salary.
       All employees on Salary Matrix AT2 will start at $60,000 base salary.
       All employees currently placed on Salary Matrix AT3 will start at $70,000 base salary.
       All employees currently placed on Salary Matrix A-2 (Speech/Language Pathologists, Physical
       Therapist, Audiologist, Occupational Therapist, Orientation/Mobility Specialist) will be merged
       with AT1, AT2, and AT3 matrices with the guarantee of the newly established base salaries for
       each level.
       All employees currently placed on Salary Matrix A-3 (Educational Diagnosticians, School
       Psychologist, Transition Specialist/Rehabilitation Counselors, and BCBAs) will be merged with
       the AT3 matrix with the guarantee of the newly established base salary and ten (10) additional
       workdays paid through an extended contract.
       The District is committed to attracting and retaining the essential personnel (listed below) whose
       services are indispensable for meeting the needs of all students, in particular those who are at risk.
       As such, the Albuquerque Public Schools has a goal, in perpetuity, to ensure that these employees
       receive equitable raises in comparison to their teaching colleagues.
     • Audiologist
     • Orientation and Mobility Specialist
     • Counselors
     • Physical Therapist
     • Interpreters for the Deaf
     • Social Workers
     • Nurses
     • Speech and Language Pathologist
     • Occupational Therapist
     • Athletic Trainers
     • COTAs
     • PTAs
     • Diagnosticians
     • School Psychologists
     • Transition Specialist/Rehabilitation Counselors
     • BCBAs
       With this commitment, the Albuquerque Public Schools and the Albuquerque Federation agree to
       dissolve the APS/ATF Career Pathway System.
       Placement on the salary matrices will be based on the current language in Article 10, the APS/ATF
       Career Pathway System.
       The criteria for movement through the salary matrices from Level 1 to 2 and Level 2 to 3 for the
       above listed personnel will be based on a combination of PED licensure level and a minimum of
       three (3) years of successful practice at each level.
 Note: Employees can refer to article 6.A.14-16. for information about the requirements for movement to
 the next salary matrix.

 The following information applies to the salary matrices which follow.


                                                      97

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/albuquerque_public_schools__albequerque_2022_2023__b2207301__97-97.response.json`
Then re-run the script that printed this task to continue.