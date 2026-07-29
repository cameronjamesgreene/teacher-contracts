# Task: district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__114-114

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
                                                                                                ET‐15 Salary Schedule
                                                                                              Effective October 3, 2027

                                                                                                                                                                                                                                         Longevity Placements
      FY 2028 ET 15 Salary Schedule ‐ 10 Month                         Adjustment:        4.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     71,320   $     71,565   $     73,033   $     75,729   $     78,400   $     81,090   $     84,506   $     87,896   $     91,311   $      94,696   $      98,099   $ 104,915     $     113,089      N/A             N/A          N/A
Bachelors + 15            $     73,697   $     74,862   $     76,399   $     79,081   $     81,764   $     84,456   $     87,867   $     91,272   $     94,671   $      98,083   $     101,469   $ 108,299     $     119,855      N/A             N/A          N/A
Bachelors + 30/Masters    $     76,075   $     77,828   $     81,228   $     84,630   $     88,024   $     91,439   $     95,665   $     99,872   $    104,107   $     108,314   $     112,553   $ 120,989     $     131,968   $ 133,483 $ 136,007 $ 139,543
Masters + 30              $     78,453   $     81,228   $     84,630   $     88,024   $     91,439   $     94,842   $     99,053   $    103,288   $    107,504   $     111,714   $     115,927   $ 124,386     $     135,438   $ 136,950 $ 139,477 $ 143,013
Masters + 60/PhD          $     83,206   $     84,630   $     88,024   $     91,439   $     94,842   $     96,320   $    102,463   $    106,693   $    110,907   $     115,131   $     119,334   $ 128,159     $     139,857   $ 141,370 $ 143,896 $ 147,431


                                                                                                                                                                                                                                         Longevity Placements
      FY 2028 ET 15 Salary Schedule ‐ 11 Month                         Adjustment:        4.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     78,453   $     78,721   $     80,338   $     83,301   $     86,240   $     89,198   $     92,958   $     96,684   $    100,442   $     104,166   $     107,910   $ 115,407     $     124,400      N/A             N/A          N/A
Bachelors + 15            $     81,065   $     82,348   $     84,039   $     86,987   $     89,941   $     92,902   $     96,654   $    100,399   $    104,140   $     107,890   $     111,615   $ 119,128     $     131,843      N/A             N/A          N/A
Bachelors + 30/Masters    $     83,684   $     85,612   $     89,352   $     93,094   $     96,829   $    100,582   $    105,231   $    109,857   $    114,520   $     119,148   $     123,808   $ 133,087     $     145,165   $ 146,830 $ 149,608 $ 153,497
Masters + 30              $     86,297   $     89,352   $     93,094   $     96,829   $    100,582   $    104,326   $    108,960   $    113,617   $    118,255   $     122,885   $     127,521   $ 136,824     $     148,982   $ 150,646 $ 153,424 $ 157,312
Masters + 60/PhD          $     91,527   $     93,094   $     96,829   $    100,582   $    104,326   $    108,069   $    112,711   $    117,363   $    121,997   $     126,645   $     131,268   $ 140,974     $     153,841   $ 155,509 $ 158,286 $ 162,174


                                                                                                                                                                                                                                         Longevity Placements
      FY 2028 ET 15 Salary Schedule ‐ 12 Month                         Adjustment:        4.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     84,521   $     84,778   $     86,347   $     89,213   $     92,060   $     94,925   $     98,565   $    102,172   $    105,807   $     109,413   $     113,039   $ 120,298     $     129,005      N/A             N/A          N/A
Bachelors + 15            $     87,052   $     88,292   $     89,931   $     92,785   $     95,643   $     98,510   $    102,143   $    105,769   $    109,389   $     113,024   $     116,628   $ 123,901     $     136,212      N/A             N/A          N/A
Bachelors + 30/Masters    $     89,582   $     91,437   $     95,072   $     98,697   $    102,311   $    105,945   $    110,422   $    114,925   $    119,440   $     123,919   $     127,252   $ 137,415     $     149,108   $ 150,624 $ 153,149 $ 156,684
Masters + 30              $     92,115   $     95,072   $     98,697   $    102,311   $    105,945   $    109,570   $    114,055   $    118,565   $    123,058   $     127,540   $     132,025   $ 141,035     $     152,806   $ 154,320 $ 156,845 $ 160,381
Masters + 60/PhD          $     97,177   $     98,697   $    102,311   $    105,945   $    109,570   $    113,202   $    117,689   $    122,191   $    126,680   $     131,178   $     135,653   $ 145,053     $     157,508   $ 159,024 $ 161,549 $ 165,084

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__114-114.response.json`
Then re-run the script that printed this task to continue.