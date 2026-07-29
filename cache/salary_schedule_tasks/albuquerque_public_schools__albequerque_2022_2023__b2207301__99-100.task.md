# Task: albuquerque_public_schools__albequerque_2022_2023__b2207301__99-100

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
EDUCATION           BA       BA+15            BA+45           MA         MA+15        MA+45           Doctorate

  STEP        ANNUAL        ANNUAL         ANNUAL           ANNUAL      ANNUAL       ANNUAL           ANNUAL

    1          $50,000                     $50,323                      $50,647                        $50,970
                             $50,162                        $50,485                   $50,808
    2          $50,001
                             $50,163       $50,324          $50,486     $50,648       $50,809          $50,971
    3          $50,002
                             $50,164       $50,325          $50,487     $50,649       $50,810          $50,972
    4          $50,003                     $50,326                      $50,650                        $50,973
                             $50,165                        $50,488                   $50,811
    5          $50,004                     $50,327                      $50,651                        $50,974
                             $50,166                        $50,489                   $50,812
    6          $50,005                     $50,328                      $50,652                        $50,975
                             $50,167                        $50,490                   $50,813
    7          $50,006                     $50,329                      $50,653                        $50,976
                             $50,168                        $50,491                   $50,814
    8          $50,007                     $50,330                      $50,654                        $50,977
                             $50,169                        $50,492                   $50,815
    9          $50,008                     $50,331                      $50,655                        $50,978
                             $50,170                        $50,493                   $50,816
   10                                      $50,332                      $50,656                        $50,979
               $50,009       $50,171                        $50,494                   $50,817
   11          $50,010                     $50,333                      $50,657                        $50,980
                             $50,172                        $50,495                   $50,818
   12          $50,011                     $50,334                      $50,658                        $50,981
                             $50,173                        $50,496                   $50,819
   13          $50,012                     $50,335                      $50,659                        $50,982
                             $50,174                        $50,497                   $50,820
   14          $50,013                     $50,336                      $50,660                        $50,983
                             $50,175                        $50,498                   $50,821
   15          $50,014                     $50,337                      $50,661                        $50,984
                             $50,176                        $50,499                   $50,822
   16          $50,015                     $50,338                      $50,662                        $50,985
                             $50,177                        $50,500                   $50,823
   17          $50,016                     $50,339                      $50,663                        $50,986
                             $50,178                        $50,501                   $50,824
   18          $50,017                     $50,340                      $50,664                        $50,987
                             $50,179                        $50,502                   $50,825
   19          $50,018                     $50,341                      $50,665                        $50,988
                             $50,180                        $50,503                   $50,826
   20          $50,019                     $50,342                      $50,666                        $50,989
                             $50,181                        $50,504                   $50,827




                         Appendix A.2 2022-2023 Salary Matrix A2
                                                 Appendix A.2


                         2022-2023 A2 SCHEDULE:LEVEL 2 EDUCATORS
                            Based on 184 DAY/6.5 HOUR work schedule



            EDUCATION                    BA        BA+15      BA+45       MA      MA+15       MA+45     Doctorat
                                                                                                           e
              STEP                     ANNUA      ANNUA       ANNUA     ANNUA     ANNUA     ANNUA       ANNUAL
                                          L          L           L         L         L         L
                1                      $60,000    $60,240     $60,480   $60,721   $60,961   $61,201      $61,441
                2                      $60,001    $60,241     $60,481   $60,722   $60,962   $61,202      $61,442
                3                      $60,002    $60,242     $60,482   $60,723   $60,963   $61,203      $61,443
                4                      $60,003    $60,243     $60,483   $60,724   $60,964   $61,204      $61,444
                5                      $60,004    $60,244     $60,484   $60,725   $60,965   $61,205      $61,445
                6                      $60,005    $60,245     $60,485   $60,726   $60,966   $61,206      $61,446
                7                      $60,006    $60,246     $60,486   $60,727   $60,967   $61,207      $61,447


                                                      99
8    $60,007   $60,247   $60,487   $60,728   $60,968   $61,208   $61,448
9    $60,008   $60,248   $60,488   $60,729   $60,969   $61,209   $61,449
10   $60,009   $60,249   $60,489   $60,730   $60,970   $61,210   $61,450
11   $60,010   $60,250   $60,490   $60,731   $60,971   $61,211   $61,451
12   $60,011   $60,251   $60,491   $60,732   $60,972   $61,212   $61,452
13   $60,012   $60,252   $60,492   $60,733   $60,973   $61,213   $61,453
14   $60,013   $60,253   $60,493   $60,734   $60,974   $61,214   $61,454
15   $60,014   $60,254   $60,494   $60,735   $60,975   $61,215   $61,455
16   $60,015   $60,255   $60,495   $60,736   $60,976   $61,216   $61,456
17   $60,016   $60,256   $60,496   $60,737   $60,977   $61,217   $61,457
18   $60,017   $60,257   $60,497   $60,738   $60,978   $61,218   $61,458
19   $60,018   $60,258   $60,498   $60,739   $60,979   $61,219   $61,459
20   $60,019   $60,259   $60,499   $60,740   $60,980   $61,220   $61,460
21   $60,020   $60,260   $60,500   $60,741   $60,981   $61,221   $61,461
22   $60,021   $60,261   $60,501   $60,742   $60,982   $61,222   $61,462
23   $60,022   $60,262   $60,502   $60,743   $60,983   $61,223   $61,463
24   $60,023   $60,263   $60,503   $60,744   $60,984   $61,224   $61,464
25   $60,024   $60,264   $60,504   $60,745   $60,985   $61,225   $61,465
26   $60,025   $60,265   $60,505   $60,746   $60,986   $61,226   $61,466
27   $60,026   $60,266   $60,506   $60,747   $60,987   $61,227   $61,467
28   $60,027   $60,267   $60,507   $60,748   $60,988   $61,228   $61,468
29   $60,028   $60,268   $60,508   $60,749   $60,989   $61,229   $61,469
30   $60,029   $60,269   $60,509   $60,750   $60,990   $61,230   $61,470
31   $60,030   $60,270   $60,510   $60,751   $60,991   $61,231   $62,947
32   $60,031   $60,271   $60,511   $60,752   $60,992   $61,232   $62,948
33   $60,032   $60,272   $60,512   $60,753   $60,993   $61,233   $62,949
34   $60,033   $60,273   $60,513   $60,754   $60,994   $63,553   $63,773
35   $60,034   $60,274   $60,514   $60,755   $60,995   $63,554   $63,774
36   $60,035   $60,275   $60,515   $60,756   $60,996   $63,555   $63,775
37   $60,036   $60,276   $60,516   $60,757   $60,997   $63,556   $63,776
38   $60,037   $60,277   $61,138   $60,758   $61,577   $63,557   $63,777
39   $60,038   $60,278   $61,139   $60,759   $65,016   $65,234   $65,454
40   $60,039   $61,623   $64,215   $63,230   $65,017   $71,775   $71,994
41   $60,040   $63,101   $64,216   $63,231   $67,997   $73,269   $73,489
42   $60,041   $64,577   $64,796   $63,801   $67,998   $73,270   $73,490
43   $60,042   $66,059   $69,278   $68,198   $68,414   $73,271   $73,491
44   $60,043   $66,146   $70,852   $69,743   $69,957   $73,358   $79,619

     $60,044   $70,848   $72,346   $71,209   $71,424   $73,359   $79,620
45
46   $60,045   $71,802   $73,839   $72,675   $72,890   $74,498   $79,621
47   $60,046   $71,803   $73,840   $72,676   $75,730   $80,711   $79,622
48   $60,047   $71,804   $76,735   $75,516   $77,299   $79,203   $79,623
49   $60,048   $75,019   $76,736   $77,085   $77,300   $79,204   $79,624
50   $60,049   $77,891   $76,737   $77,086   $77,301   $79,205   $79,625




                  100

---END---

## What to do
Read the instructions and input above. Produce the JSON answer they ask for, then write it — and nothing else — to:
`/Users/camerongreene/Dropbox (Personal)/1. Barbara/contracts/contract_coding_CG/cache/salary_schedule_tasks/albuquerque_public_schools__albequerque_2022_2023__b2207301__99-100.response.json`
Then re-run the script that printed this task to continue.