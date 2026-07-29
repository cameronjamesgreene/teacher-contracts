# Task: district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__112-112

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
                                                                                              Effective October 5, 2025

                                                                                                                                                                                                                                         Longevity Placements
      FY 2026 ET 15 Salary Schedule ‐ 10 Month                         Adjustment:        3.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     66,580   $     66,809   $     68,179   $     70,696   $     73,189   $     75,700   $     78,890   $     82,054   $     85,241   $      88,402   $      91,579   $    97,941   $     105,573      N/A             N/A          N/A
Bachelors + 15            $     68,799   $     69,886   $     71,321   $     73,825   $     76,329   $     78,842   $     82,027   $     85,206   $     88,379   $      91,564   $      94,724   $ 101,100     $     111,889      N/A             N/A          N/A
Bachelors + 30/Masters    $     71,018   $     72,655   $     75,829   $     79,005   $     82,174   $     85,361   $     89,306   $     93,233   $     97,187   $     101,115   $     105,072   $ 112,947     $     123,197   $ 124,611 $ 126,967 $ 130,268
Masters + 30              $     73,238   $     75,829   $     79,005   $     82,174   $     85,361   $     88,538   $     92,470   $     96,423   $    100,359   $     104,289   $     108,221   $ 116,119     $     126,436   $ 127,848 $ 130,206 $ 133,507
Masters + 60/PhD          $     77,675   $     79,005   $     82,174   $     85,361   $     88,538   $     89,918   $     95,653   $     99,601   $    103,536   $     107,478   $     111,402   $ 119,640     $     130,561   $ 131,973 $ 134,332 $ 137,632


                                                                                                                                                                                                                                         Longevity Placements
      FY 2026 ET 15 Salary Schedule ‐ 11 Month                         Adjustment:        3.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     73,238   $     73,488   $     74,998   $     77,764   $     80,507   $     83,270   $     86,780   $     90,258   $     93,766   $      97,242   $     100,738   $ 107,736     $     116,131      N/A             N/A          N/A
Bachelors + 15            $     75,677   $     76,875   $     78,454   $     81,205   $     83,963   $     86,727   $     90,230   $     93,726   $     97,218   $     100,719   $     104,196   $ 111,210     $     123,080      N/A             N/A          N/A
Bachelors + 30/Masters    $     78,122   $     79,921   $     83,413   $     86,907   $     90,393   $     93,896   $     98,236   $    102,555   $    106,908   $     111,228   $     115,579   $ 124,241     $     135,516   $ 137,071 $ 139,664 $ 143,294
Masters + 30              $     80,561   $     83,413   $     86,907   $     90,393   $     93,896   $     97,392   $    101,718   $    106,065   $    110,395   $     114,717   $     119,045   $ 127,730     $     139,079   $ 140,633 $ 143,226 $ 146,856
Masters + 60/PhD          $     85,443   $     86,907   $     90,393   $     93,896   $     97,392   $    100,886   $    105,220   $    109,562   $    113,888   $     118,227   $     122,543   $ 131,603     $     143,616   $ 145,173 $ 147,765 $ 151,395


                                                                                                                                                                                                                                         Longevity Placements
      FY 2026 ET 15 Salary Schedule ‐ 12 Month                         Adjustment:        3.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     78,903   $     79,143   $     80,607   $     83,283   $     85,941   $     88,616   $     92,014   $     95,381   $     98,774   $     102,140   $     105,525   $ 112,302     $     120,430      N/A             N/A          N/A
Bachelors + 15            $     81,266   $     82,424   $     83,953   $     86,618   $     89,286   $     91,962   $     95,354   $     98,739   $    102,118   $     105,512   $     108,876   $ 115,666     $     127,158      N/A             N/A          N/A
Bachelors + 30/Masters    $     83,628   $     85,359   $     88,753   $     92,137   $     95,511   $     98,903   $    103,083   $    107,286   $    111,501   $     115,683   $     118,793   $ 128,281     $     139,197   $ 140,612 $ 142,970 $ 146,270
Masters + 30              $     85,993   $     88,753   $     92,137   $     95,511   $     98,903   $    102,287   $    106,474   $    110,684   $    114,879   $     119,062   $     123,250   $ 131,661     $     142,649   $ 144,062 $ 146,420 $ 149,721
Masters + 60/PhD          $     90,718   $     92,137   $     95,511   $     98,903   $    102,287   $    105,678   $    109,866   $    114,069   $    118,260   $     122,459   $     126,636   $ 135,412     $     147,039   $ 148,454 $ 150,812 $ 154,111

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__112-112.response.json`
Then re-run the script that printed this task to continue.