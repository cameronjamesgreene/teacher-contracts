# Task: district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__115-115

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
Document: DCPS_WTU_CBA_2023-2028.pdf

---PAGE TEXT---
                                                                  Washington Teacher's Union
                                                                    EG 09 Salary Schedule
                                                                          FY 25 - 28
                                                                                                                                                            Longevity Placements
           FY 2025 Effective October 6, 2024                     Adjustment:     2.0%                                                                   1             2            2
                                                                                                                                                    17-18 Yrs    19-20 Yrs      21+ Yrs
                                                                                                                                                     Service      Service       Service
                                                                                                                                                  BA/BS+30 & BA/BS+30 & BA/BS+30 &
Education Level                Step 1        Step 2     Step 3      Step 4      Step 5      Step 6     Step 7     Step 8     Step 9    Step 10-16    Above         Above         Above
Bachelors                    $   70,814 $      73,184 $   75,549 $     77,920 $    80,288 $   82,657 $   85,025 $   87,395 $   89,763 $    92,134 $     93,507 $      95,796 $     98,999


                                                                                                                                                            Longevity Placements
           FY 2026 Effective October 5, 2025                     Adjustment:     3.0%                                                                   1             2            2
                                                                                                                                                    17-18 Yrs    19-20 Yrs      21+ Yrs
                                                                                                                                                     Service      Service       Service
                                                                                                                                                  BA/BS+30 & BA/BS+30 & BA/BS+30 &
Education Level                Step 1        Step 2     Step 3      Step 4      Step 5      Step 6     Step 7     Step 8     Step 9    Step 10-16    Above         Above         Above
Bachelors                    $   72,938 $      75,379 $   77,816 $     80,257 $    82,697 $   85,136 $   87,576 $   90,016 $   92,456 $    94,898 $     96,313 $      98,670 $ 101,969


                                                                                                                                                            Longevity Placements
           FY 2027 Effective October 4, 2026                     Adjustment:     3.0%                                                                   1             2            2
                                                                                                                                                    17-18 Yrs    19-20 Yrs      21+ Yrs
                                                                                                                                                     Service      Service       Service
                                                                                                                                                  BA/BS+30 & BA/BS+30 & BA/BS+30 &
Education Level                Step 1        Step 2     Step 3      Step 4      Step 5      Step 6     Step 7     Step 8     Step 9    Step 10-16    Above         Above         Above
Bachelors                    $   75,126 $      77,641 $   80,150 $     82,665 $    85,178 $   87,691 $   90,203 $   92,717 $   95,230 $    97,744 $     99,202 $ 101,630 $ 105,028


                                                                                                                                                           Longevity Placements
           FY 2028 Effective October 3, 2027                     Adjustment:     4.0%                                                                  1             2            2
                                                                                                                                                   17-18 Yrs    19-20 Yrs      21+ Yrs
                                                                                                                                                    Service      Service       Service
                                                                                                                                                  BA/BS+30 & BA/BS+30 & BA/BS+30 &
Education Level                Step 1        Step 2     Step 3      Step 4      Step 5      Step 6     Step 7     Step 8     Step 9    Step 10-16   Above         Above         Above
Bachelors                    $   78,131 $      80,747 $   83,356 $     85,972 $    88,585 $   91,198 $   93,811 $   96,426 $   99,039 $ 101,654 $ 103,170 $ 105,696 $ 109,229

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__115-115.response.json`
Then re-run the script that printed this task to continue.