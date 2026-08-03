# Contract Coding Materials

This folder contains the design files for the public-school teaching-job extraction exercise. The main output is `extraction_elements.md`, a structured question bank for later document-by-document coding of PDFs in `../nctq_contracts`.

## Files

- `extraction_elements_reduced.md`: master table of extraction questions, with IDs, categories, answer types, search hints, expected frequency, and coding notes.
- `AGENTS.md`: instructions for future AI agents that use the question bank.
- `readme.md`: this overview and sampling note.
- `prompt_log.md`: exact prompt text for the original task request, prompt-saving request, and LLM-regeneration request.
- `llm_agent_prompt.md`: reusable prompt for assigning LLM agents to answer every Question ID in `extraction_elements_reduced.md`.
- `utils.py`: shared utility module (codebook parsing, document loading, text extraction, metadata helpers) used by `llm_extract.py` and `merge_llm_parts.py`.
- `merge_llm_parts.py`: validation/merge script for LLM-coded worker part files.
- `output/llm_main_dataset.csv`: LLM-coded wide spreadsheet-ready sample dataset with one row per sampled PDF.
- `output/llm_coding_log.csv`: LLM-coded long audit log with one row per PDF-question pair.
- `output/llm_sample_dataset.xlsx`: Excel workbook containing the LLM-coded main dataset, coding log, and validation report.
- `output/llm_validation_report.txt`: row-count and schema validation report for the LLM-coded outputs.
- `output/llm_parts/`: disjoint worker outputs used to build the merged LLM-coded files.
- `output/sample_main_dataset.csv`: earlier keyword/pattern-coded wide sample dataset.
- `output/sample_coding_log.csv`: earlier keyword/pattern-coded long audit log.

## Sampling Note

I reviewed a reproducible random sample of 20 district folders, selecting two PDFs per district. Random seed: `20260528`. The sample intentionally includes collective bargaining agreements, employee handbooks, policy manuals, tentative agreements, and short settlement summaries, because later agents will encounter all of those document types.

| District | Selected PDF |
|---|---|
| Granite School District | `professional_agreement_with_gea_2020_2023.pdf` |
| Granite School District | `Granite_School_DistrictTeacher_-_GSD_GEA_Professional_Agreement_2011-2014.pdf` |
| Santa Ana Unified School District | `95.pdf` |
| Santa Ana Unified School District | `Santa_Ana_2016-2019_Contract.pdf` |
| Birmingham City Schools | `birmingham_policy_manual_2011.pdf` |
| Birmingham City Schools | `Birmingham_Policy_Manual_updated_6_2012.pdf` |
| District of Columbia Public Schools | `X_DCPS_2017_-_2019_tentative.pdf` |
| District of Columbia Public Schools | `DCPS_WTU_CBA_2023-2028.pdf` |
| Osceola County School District | `Osceola_County_2021-22_and_2022-23_Instructional_Employees_Contract_110221.pdf` |
| Osceola County School District | `Osceola_2018-19_INSTRUCTIONAL_EMPLOYEES__CONTRACT_082918.pdf` |
| Montgomery County Public Schools | `V2-Flyer-Contract-Settlement-Highlights_for-contract-vote.pdf` |
| Montgomery County Public Schools | `Montgomery_11-14.pdf` |
| Prince Georges County Public Schools | `14-05.pdf` |
| Prince Georges County Public Schools | `14.pdf` |
| Northside Independent School District | `Employee_HAndbook2012-2013.pdf` |
| Northside Independent School District | `Model_employee_handbook_2013-2014_(2)_(1).pdf` |
| West Ada School District | `84.pdf` |
| West Ada School District | `Wes_Ada_Agreement_2022-2023.pdf` |
| Cincinnati Public Schools | `Cincinnati__2017_TA_CPS__CFT.pdf` |
| Cincinnati Public Schools | `Cincinnati_0709.pdf` |
| San Francisco Unified School District | `UESF_Certificated_CBA_2023-2025_Executed.pdf` |
| San Francisco Unified School District | `94.pdf` |
| Indianapolis Public Schools | `80-07.pdf` |
| Indianapolis Public Schools | `Indianapolis_IEA_Agreement_2006_-_2007.pdf` |
| Kansas City Public Schools, MO | `aft_cert_cba_7_14_17_final_for_posting_on_web.pdf` |
| Kansas City Public Schools, MO | `KC_AFT_CERTIFED_CBA-_FINAL_DRAFT_2023-2026.pdf` |
| Aldine Independent School District | `2015-2016_Aldine_ISD_2015-16_teacher_handbook.pdf` |
| Aldine Independent School District | `2012-2013_Aldine_teacher_handbook_2012-13.pdf` |
| Pinellas County Schools | `Pinellas_PCTA_CBA_Final_04_12_22-06_30_25_including_links_920344.pdf` |
| Pinellas County Schools | `Pinellas_Agreement_-_Final_Redlined_11419(3).pdf` |
| Albuquerque Public Schools | `Albuqurque_tentative_agreement_15-16.pdf` |
| Albuquerque Public Schools | `Albequerque_2022-2023.pdf` |
| Minneapolis Public Schools | `2015-17xx_TA_Summary_01-24-2016[1].pdf` |
| Minneapolis Public Schools | `teachers_2019-2021_final_3-15-2021_signed.pdf` |
| Fresno Unified School District | `Fresno_2016-2019_CBA.pdf` |
| Fresno Unified School District | `Fresno_Tentative_Agreement_2013-2016.pdf` |
| School District of Palm Beach County | `Palm_Beach_County_CTACBAJuly2011-June2014.pdf` |
| School District of Palm Beach County | `Palm_Beach_2011-2014_CBA_w_2013-2014_modifications.pdf` |
| Garland Independent School District | `Garland_16-17_handbook.pdf` |
| Garland Independent School District | `2019-2020_employee_handbook.pdf` |

Several selected PDFs produced little or no extractable text with `pdftotext` and likely need OCR for document-level coding, including `Santa_Ana_2016-2019_Contract.pdf`, `Birmingham_Policy_Manual_updated_6_2012.pdf`, and `Wes_Ada_Agreement_2022-2023.pdf`.

## Frequency Labels

- `likely frequent`: appeared often in the sample or is a standard section in CBAs, handbooks, or salary schedules.
- `occasional`: appeared in a meaningful subset of documents or only in certain document types.
- `rare`: appeared in specialized documents, state-specific handbooks, appendices, or isolated provisions.

## How to Use

Build the spreadsheet with one row per PDF. For each question ID, enter `yes`, `no`, an extracted value, `not_discussed`, `discussed_unclear`, or `not_applicable`. Preserve page numbers, section names, and short quotes for every answer other than `not_discussed` whenever possible.

## LLM-Coded Sample Dataset

The current LLM-coded sample dataset was generated from the 40 PDFs listed above by assigning four LLM-worker batches using `llm_agent_prompt.md`, then merging the worker files with:

```bash
python3 -B merge_llm_parts.py
```

Validation from the latest LLM-coded run:

- 234 codebook questions.
- 40 sampled PDF documents.
- 948 columns in the wide dataset: 12 document metadata columns plus four fields for each Question ID.
- 9,360 rows in the coding log.
- No blank answer fields.
- No invalid confidence values.
- The Excel workbook `output/llm_sample_dataset.xlsx` contains the merged main dataset, merged coding log, and validation report.

Important caveats from the LLM workers:

- `Santa_Ana_2016-2019_Contract.pdf`, `Birmingham_Policy_Manual_updated_6_2012.pdf`, and `Wes_Ada_Agreement_2022-2023.pdf` are scanned or image-only in the available extracted text and need OCR/visual review.
- Some salary and benefits tables are table-heavy, linked, or missing from extracted text, so detail fields are coded conservatively where appropriate.
- Short tentative agreements, settlement flyers, and handbooks were coded only for what they actually state; many full-CBA fields are `not_discussed` or `discussed_unclear`.
- The output is LLM-assisted and auditable, but it should still be reviewed before publication or statistical use.

## Keyword Sample Dataset

The earlier keyword/pattern-coded sample dataset was generated from the 40 PDFs listed above using:

```bash
python3 -B utils.py
```

The script writes cached PDF text to `extracted_text` and final CSVs to `output`.

Note: `utils.py` is now a shared utility module, not a standalone runner. The keyword-coded outputs above were produced by an earlier version of this script.

Validation from the prior keyword run:

- 217 codebook questions.
- 40 sampled PDF documents.
- 880 columns in the wide dataset: 12 document metadata columns plus four fields for each Question ID.
- 8,680 rows in the coding log.
- No blank answer fields and no missing support-field columns.
- Three PDFs were flagged for OCR or visual review: `Santa_Ana_2016-2019_Contract.pdf`, `Birmingham_Policy_Manual_updated_6_2012.pdf`, and `Wes_Ada_Agreement_2022-2023.pdf`.

The generated dataset is intentionally auditable. It uses full-text keyword and pattern matching plus conservative missing-value codes, so high-value fields should be manually checked against the source PDFs before publication.
