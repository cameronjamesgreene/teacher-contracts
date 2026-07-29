# Task: district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__111-111

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
                                                                                              Effective October 6, 2024

                                                                                                                                                                                                                                         Longevity Placements
      FY 2025 ET 15 Salary Schedule ‐ 10 Month                         Adjustment:        2.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     64,640   $     64,863   $     66,193   $     68,637   $     71,057   $     73,495   $     76,592   $     79,664   $     82,759   $      85,827   $      88,911   $    95,088   $     102,498      N/A             N/A          N/A
Bachelors + 15            $     66,795   $     67,850   $     69,244   $     71,674   $     74,106   $     76,546   $     79,638   $     82,724   $     85,804   $      88,897   $      91,965   $    98,156   $     108,630      N/A             N/A          N/A
Bachelors + 30/Masters    $     68,950   $     70,539   $     73,621   $     76,704   $     79,780   $     82,875   $     86,705   $     90,518   $     94,356   $      98,170   $     102,011   $ 109,657     $     119,608   $ 120,981 $ 123,269 $ 126,474
Masters + 30              $     71,105   $     73,621   $     76,704   $     79,780   $     82,875   $     85,959   $     89,776   $     93,615   $     97,436   $     101,251   $     105,069   $ 112,737     $     122,753   $ 124,124 $ 126,414 $ 129,619
Masters + 60/PhD          $     75,413   $     76,704   $     79,780   $     82,875   $     85,959   $     87,299   $     92,867   $     96,700   $    100,520   $     104,348   $     108,158   $ 116,156     $     126,758   $ 128,129 $ 130,419 $ 133,623


                                                                                                                                                                                                                                         Longevity Placements
      FY 2025 ET 15 Salary Schedule ‐ 11 Month                         Adjustment:        2.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     71,105   $     71,348   $     72,814   $     75,499   $     78,163   $     80,844   $     84,252   $     87,629   $     91,035   $      94,410   $      97,804   $ 104,598     $     112,749      N/A             N/A          N/A
Bachelors + 15            $     73,473   $     74,635   $     76,169   $     78,840   $     81,517   $     84,201   $     87,602   $     90,996   $     94,387   $      97,785   $     101,162   $ 107,971     $     119,495      N/A             N/A          N/A
Bachelors + 30/Masters    $     75,846   $     77,593   $     80,984   $     84,375   $     87,760   $     91,161   $     95,375   $     99,568   $    103,794   $     107,988   $     112,212   $ 120,622     $     131,569   $ 133,078 $ 135,596 $ 139,121
Masters + 30              $     78,215   $     80,984   $     84,375   $     87,760   $     91,161   $     94,555   $     98,755   $    102,976   $    107,180   $     111,376   $     115,577   $ 124,010     $     135,029   $ 136,537 $ 139,055 $ 142,579
Masters + 60/PhD          $     82,955   $     84,375   $     87,760   $     91,161   $     94,555   $     97,948   $    102,155   $    106,371   $    110,571   $     114,784   $     118,974   $ 127,770     $     139,433   $ 140,945 $ 143,461 $ 146,985


                                                                                                                                                                                                                                         Longevity Placements
      FY 2025 ET 15 Salary Schedule ‐ 12 Month                         Adjustment:        2.0%                                                                                                                                      1              2             2
                                                                                                                                                                                                                                17‐18 Yrs     19‐20 Yrs       21+ Yrs
Education Level               Step 1         Step 2         Step 3         Step 4         Step 5         Step 6         Step 7         Step 8         Step 9         Step 10         Step 11      Step 12‐15       Step 16       Service        Service       Service
Bachelors                 $     76,605   $     76,838   $     78,260   $     80,857   $     83,438   $     86,035   $     89,334   $     92,603   $     95,897   $      99,165   $     102,452   $ 109,031     $     116,923      N/A             N/A          N/A
Bachelors + 15            $     78,899   $     80,023   $     81,508   $     84,095   $     86,686   $     89,284   $     92,576   $     95,863   $     99,144   $     102,439   $     105,705   $ 112,297     $     123,455      N/A             N/A          N/A
Bachelors + 30/Masters    $     81,192   $     82,873   $     86,168   $     89,453   $     92,729   $     96,023   $    100,080   $    104,161   $    108,254   $     112,313   $     115,333   $ 124,545     $     135,143   $ 136,517 $ 138,806 $ 142,010
Masters + 30              $     83,488   $     86,168   $     89,453   $     92,729   $     96,023   $     99,308   $    103,373   $    107,460   $    111,533   $     115,595   $     119,660   $ 127,826     $     138,495   $ 139,866 $ 142,155 $ 145,360
Masters + 60/PhD          $     88,076   $     89,453   $     92,729   $     96,023   $     99,308   $    102,600   $    106,667   $    110,747   $    114,815   $     118,892   $     122,948   $ 131,468     $     142,756   $ 144,130 $ 146,419 $ 149,623

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf__111-111.response.json`
Then re-run the script that printed this task to continue.