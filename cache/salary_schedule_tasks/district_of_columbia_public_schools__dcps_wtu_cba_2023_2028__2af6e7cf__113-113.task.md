# Task: district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__113-113

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
                                                                                              Effective October 4, 2026

                                                                                                                                                                                                                                         Longevity Placements
      FY 2027 ET 15 Salary Schedule ‐ 10 Month                         Adjustment:        3.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     68,577   $     68,813   $     70,224   $     72,817   $     75,385   $     77,971   $     81,256   $     84,516   $     87,799   $      91,054   $      94,326   $ 100,879     $     108,740      N/A             N/A          N/A
Bachelors + 15            $     70,862   $     71,982   $     73,461   $     76,039   $     78,619   $     81,208   $     84,487   $     87,762   $     91,030   $      94,311   $      97,566   $ 104,133     $     115,246      N/A             N/A          N/A
Bachelors + 30/Masters    $     73,149   $     74,835   $     78,104   $     81,375   $     84,639   $     87,922   $     91,985   $     96,030   $    100,102   $     104,148   $     108,224   $ 116,335     $     126,892   $ 128,349 $ 130,776 $ 134,176
Masters + 30              $     75,436   $     78,104   $     81,375   $     84,639   $     87,922   $     91,194   $     95,244   $     99,316   $    103,369   $     107,418   $     111,468   $ 119,602     $     130,229   $ 131,683 $ 134,112 $ 137,512
Masters + 60/PhD          $     80,005   $     81,375   $     84,639   $     87,922   $     91,194   $     92,616   $     98,523   $    102,589   $    106,642   $     110,703   $     114,745   $ 123,229     $     134,478   $ 135,932 $ 138,362 $ 141,761


                                                                                                                                                                                                                                         Longevity Placements
      FY 2027 ET 15 Salary Schedule ‐ 11 Month                         Adjustment:        3.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     75,436   $     75,693   $     77,248   $     80,097   $     82,923   $     85,768   $     89,383   $     92,966   $     96,579   $     100,160   $     103,760   $ 110,968     $     119,615      N/A             N/A          N/A
Bachelors + 15            $     77,947   $     79,181   $     80,807   $     83,641   $     86,482   $     89,329   $     92,937   $     96,538   $    100,135   $     103,740   $     107,322   $ 114,547     $     126,772      N/A             N/A          N/A
Bachelors + 30/Masters    $     80,465   $     82,319   $     85,916   $     89,514   $     93,104   $     96,713   $    101,183   $    105,632   $    110,115   $     114,565   $     119,046   $ 127,968     $     139,581   $ 141,183 $ 143,854 $ 147,593
Masters + 30              $     82,978   $     85,916   $     89,514   $     93,104   $     96,713   $    100,313   $    104,770   $    109,247   $    113,707   $     118,159   $     122,616   $ 131,562     $     143,252   $ 144,852 $ 147,523 $ 151,262
Masters + 60/PhD          $     88,006   $     89,514   $     93,104   $     96,713   $    100,313   $    103,913   $    108,376   $    112,849   $    117,305   $     121,774   $     126,219   $ 135,552     $     147,924   $ 149,528 $ 152,198 $ 155,936


                                                                                                                                                                                                                                         Longevity Placements
      FY 2027 ET 15 Salary Schedule ‐ 12 Month                         Adjustment:        3.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     81,270   $     81,517   $     83,026   $     85,782   $     88,519   $     91,274   $     94,774   $     98,242   $    101,737   $     105,205   $     108,691   $ 115,671     $     124,043      N/A             N/A          N/A
Bachelors + 15            $     83,704   $     84,896   $     86,472   $     89,216   $     91,965   $     94,721   $     98,214   $    101,701   $    105,182   $     108,677   $     112,142   $ 119,136     $     130,973      N/A             N/A          N/A
Bachelors + 30/Masters    $     86,137   $     87,920   $     91,415   $     94,901   $     98,376   $    101,871   $    106,175   $    110,505   $    114,846   $     119,153   $     122,357   $ 132,130     $     143,373   $ 144,831 $ 147,259 $ 150,658
Masters + 30              $     88,572   $     91,415   $     94,901   $     98,376   $    101,871   $    105,356   $    109,668   $    114,004   $    118,325   $     122,634   $     126,948   $ 135,611     $     146,929   $ 148,384 $ 150,813 $ 154,213
Masters + 60/PhD          $     93,440   $     94,901   $     98,376   $    101,871   $    105,356   $    108,848   $    113,162   $    117,491   $    121,808   $     126,133   $     130,435   $ 139,474     $     151,450   $ 152,908 $ 155,336 $ 158,735

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__113-113.response.json`
Then re-run the script that printed this task to continue.