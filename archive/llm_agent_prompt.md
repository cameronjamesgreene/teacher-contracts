# LLM Agent Prompt for Document-Level Contract Coding

Use this prompt when assigning an LLM agent to code public-school district PDFs against the question bank in `extraction_elements_reduced.md`.

```text
You are constructing a structured, document-level dataset from public-school district employment documents.

Inputs available to you:

1. Source PDFs: `nctq_contracts`
   - Each subfolder is a school district.
   - Documents may include collective bargaining agreements, employee handbooks, salary schedules, benefits documents, board policies, policy manuals, tentative agreements, settlement summaries, memoranda, or other district documents.

2. Codebook: `extraction_elements_reduced.md`
   - This table is the schema.
   - Every row has a Question ID, topic category, question, answer type, information to extract if discussed, suggested keywords, expected frequency, and coding notes.
   - Every Question ID in the codebook must be answered for every assigned PDF.

3. Optional text cache: `extracted_text`
   - You may use these files for full-text review.
   - If the cached text is sparse, garbled, or missing important tables, inspect the PDF directly or flag the document as requiring OCR/visual review.

4. Optional prior keyword output: `output/sample_main_dataset.csv` and `output/sample_coding_log.csv`
   - These files may be used only as a triage aid to find candidate sections.
   - Do not treat keyword-coded answers as authoritative.
   - Final answers must be based on the assigned PDF or its extracted text.

Assignment:

Code only the PDFs listed below and write only to the assigned output paths.

ASSIGNED PDFS:
{ASSIGNED_PDFS}

OUTPUT PATHS:
- Main wide dataset: `{MAIN_OUTPUT_PATH}`
- Long coding log: `{LOG_OUTPUT_PATH}`

Processing workflow:

Use a two-stage, category-batched pipeline for every assigned PDF.

**Step 1 — Group questions into category batches**

Each Question ID begins with a category prefix that defines its batch. Process all questions sharing the same prefix together before moving to the next prefix. The batches, in order, are:

1. `meta_*` — document metadata
2. `pay_*` — compensation
3. `benefits_*` — benefits
4. `leave_*` — leave
5. `workload_*` — workload
6. `class_*` — class size
7. `evaluation_*` — evaluation
8. `security_*` — job security, seniority, transfers, and layoffs
9. `discipline_*` — discipline
10. `conduct_*` — teacher rights and conduct
11. `safety_*` — safety and working conditions
12. `pd_*` — professional development

Do not move to the next batch until both stages below are complete for the current one.

**Stage 1 — Retrieve and Code (per batch)**

For each question in the current batch:

1. Search the document (PDF or extracted text) for every passage that is plausibly relevant to the question. Quote each passage verbatim, including its page or section reference.
2. Code the answer using *only* those retrieved passages. Do not draw on passages found for other questions or on outside knowledge. If no relevant passage was found, code `not_discussed` and leave the evidence field blank.

Record the raw retrieved passage as the `evidence` value and assign a preliminary confidence before proceeding to Stage 2.

**Stage 2 — Audit (per batch)**

After all questions in the batch have been coded in Stage 1, re-examine each answer:

1. Re-read the quoted evidence.
2. Verify that the evidence explicitly supports the coded answer under the coding rules below. Ask: "Does this passage actually say what the answer claims?" If the evidence is indirect, ambiguous, or only weakly supports the answer, revise the answer to `discussed_unclear` or `not_discussed` as appropriate.
3. Verify that the quoted evidence is verbatim (not paraphrased) and includes the verb governing the provision, and that the coded `modality` matches that verb under the deontic modality rules below.
4. Verify the agent/subject of the quoted clause against coding rule 14. If the clause's subject is an excluded classification (e.g., principals, administrators) rather than the teacher bargaining unit, revise the answer to `not_discussed` and note the issue.
5. Assign or revise the confidence rating:
   - `high`: evidence directly and unambiguously states the answer.
   - `medium`: evidence strongly suggests the answer but requires minor inference, or the relevant passage is slightly unclear.
   - `low`: evidence is indirect, partially readable, or the answer required significant inference.
6. Record any audit corrections or reasoning in the `coder notes` field.

Document metadata fields:

- `document_id`: unique ID for the PDF
- `file_name`: exact PDF file name
- `district_name`: school district name
- `state`: state abbreviation if stated or clearly inferable from the document itself; otherwise `discussed_unclear`
- `document_type`: collective bargaining agreement, employee handbook, salary schedule, benefits guide, board policy, policy manual, MOU, tentative agreement, settlement summary, other, or unclear
- `bargaining_unit`: teachers, certified staff, education association, instructional employees, all employees, administrators, other, or unclear
- `start_year`: first year covered by the document, if stated
- `end_year`: last year covered by the document, if stated
- `effective_dates`: exact effective dates, if stated
- `school_years_covered`: school years covered, if stated
- `union_name`: union or employee association name, if stated
- `source_document_notes`: brief notes on scope, missing appendices, unclear dates, scanned pages, unreadable tables, OCR problems, or apparent incompleteness

For each Question ID, create five fields in the main dataset:

- `{question_id}_answer`
- `{question_id}_evidence`
- `{question_id}_page`
- `{question_id}_confidence`
- `{question_id}_modality`

Also create a long coding log with one row per PDF-question pair and these fields:

- `document_id`
- `file_name`
- `Question ID`
- `topic category`
- `question`
- `answer`
- `evidence`
- `page number`
- `confidence`
- `modality`
- `coder notes`

Coding rules:

1. If the document clearly states that the policy, benefit, rule, right, restriction, or provision exists, code the answer as `yes` for yes/no questions, or enter the requested extracted value for numeric, monetary, percentage, date, categorical, quote, or short-text questions.
2. If the document clearly states that the policy, benefit, rule, right, restriction, or provision does not exist, code the answer as `no`.
3. If the document does not discuss the topic at all, code the answer as `not_discussed`.
4. If the document discusses the topic but does not provide enough information to answer precisely, code the answer as `discussed_unclear`.
5. If the question is not applicable to the document type or bargaining unit, code the answer as `not_applicable`.
6. If the PDF or relevant section is not readable enough to assess the question, code the answer as `discussed_unclear` or `not_discussed` only when justified by the visible/extracted text, set confidence to `low`, and explain the OCR/visual limitation in evidence or coder notes.
7. Do not infer the existence of a policy, benefit, right, restriction, or rule unless it is explicitly stated in the document.
8. Do not use outside knowledge. Base all answers only on the assigned PDF.
9. If relevant information appears in an appendix, salary schedule, benefits attachment, memorandum, side letter, or exhibit included in the PDF, use it.
10. If the document refers to another document that is not included in the PDF, note the reference but do not infer the missing content.
11. If a provision varies by year, employee type, step, lane, plan, or classification, extract the relevant variation compactly and precisely.
12. Treat statutory restatements as discussed if the document itself states them, but note when the provision appears to be a legal baseline rather than a district-specific benefit.
13. If an answer or evidence quote includes a position, classification, or salary-schedule code or acronym (such as `ET-15`, `EG-09`, or `BA+30`) that would be unclear to a general reader, spell out or define the term using the document's own definition (e.g., from a recognition article, definitions section, or salary schedule legend) if the document gives one; if the document does not define the term, note that it is undefined.
14. Watch out for clauses whose subject is not the teacher/certificated bargaining unit this codebook targets. A clause that grants a right, benefit, or duty to "principals," "administrators," "managers," "supervisors," or another excluded classification does not support a `yes` answer (or any modality coding) for a teacher-focused question, even when it uses the same entitlement language as a teacher provision. For example, "School principals... are entitled to 6 weeks of vacation annually" describes a management right, not a teacher right, and must not be used as evidence for a teacher benefits question. Confirm the clause's subject before using it as evidence; if the only relevant clause applies to an excluded classification, code `not_discussed` and note the excluded-classification clause in coder notes if it could otherwise be mistaken for relevant evidence.

Deontic modality coding:

For every answer other than `not_discussed` and `not_applicable`, also code `{question_id}_modality` based on the verb that governs the provision itself:

- `mandatory`: the provision is stated as a guaranteed entitlement or duty — shall, must, will, is required to, is entitled to, shall receive, shall be paid, shall be granted.
- `discretionary`: the provision is stated as optional or permissive — may, can, is permitted to, is allowed to, is authorized to, at the discretion of [the district/board/superintendent].
- `prohibited`: the provision is explicitly barred — shall not, may not, is prohibited from, is not permitted to.
- `not_applicable`: the answer is `no`, `not_discussed`, or `discussed_unclear`, so there is no governing clause to assess.

Code modality from the verb governing the provision the question asks about, not from verbs in surrounding eligibility, procedural, or notice clauses. If a single answer is supported by multiple clauses with different modalities (e.g., a right plus a separate condition), code the modality of the primary provision and note the secondary clause's modality in coder notes. Before coding modality, apply coding rule 14 (agent/subject check) — modality describes how a provision applies to the teacher bargaining unit, not to an excluded classification.

Numeric and monetary formatting:

- Enter dollar amounts as numbers without dollar signs or commas.
- Enter percentages as numbers without percent signs.
- Enter dates in YYYY-MM-DD format when possible.
- Enter school years as YYYY-YYYY.
- If a value is a range, enter both endpoints clearly.
- If a table contains many values, extract the value requested by the codebook and summarize the table structure in evidence or coder notes.

Text and evidence rules:

- Keep answers concise.
- Evidence must be a verbatim quote from the document, not a paraphrase. Quote the full clause containing the verb that governs the provision (e.g., shall, must, may, shall not, is entitled to), so the modality coding can be checked against the quoted text. If multiple clauses support the answer, separate quotes with `; `.
- For `not_discussed`, leave evidence blank unless a note is needed for OCR or document scope.
- For `not_applicable`, briefly state why in evidence or coder notes.
- Page should be the PDF viewer page number when available. If only printed page or section is available, identify it clearly, such as `printed p. 12`, `Article 8`, or `Appendix B`.
- Confidence must be `high`, `medium`, or `low`.
- For `quote(s)` questions, put the full sentence(s) in the `_answer` field, separating multiple quotes with `; `. The `_evidence` field may repeat the same quotes or note where each appears.

Topic-specific guidance:

- Salary schedules: identify whether a schedule is included; record the relevant schedule year; extract starting salary, maximum salary, steps, lanes, and named lanes when requested. If multiple years are shown, use the first year covered unless the codebook says otherwise and note later years.
- Benefits: distinguish availability from employer contribution. Distinguish employee-only coverage from dependent, spouse, family, or domestic partner coverage. If details are governed by a separate plan document not included in the PDF, code details as `discussed_unclear`.
- Workload: distinguish school day from teacher workday, instructional time from duty time, guaranteed preparation from aspirational planning time, and hard class-size caps from guidelines or targets.
- Rights, discipline, and grievances: distinguish informal complaints from formal grievances; record whether arbitration is binding or advisory if stated; record representation rights; distinguish discipline, dismissal, nonrenewal, suspension, layoff, and recall.

Consistency check before finishing:

1. Verify that every Question ID from `extraction_elements_reduced.md` has answer/evidence/page/confidence/modality fields in the main dataset.
2. Verify that the coding log has exactly one row per assigned PDF per Question ID.
3. Verify that every answer field is nonblank, and that every modality field is one of `mandatory`, `discretionary`, `prohibited`, or `not_applicable`.
4. Check salary, benefits, leave, appendices, exhibits, and tables for information that might have been missed.
5. Flag scanned, incomplete, missing-page, or difficult-to-read PDFs in `source_document_notes` and `coder notes`.
6. Spot-check that evidence quotes are verbatim and that no quote's subject is an excluded classification (principals, administrators, etc.) per coding rule 14.
7. Do not overwrite another worker's output files.

Return only the paths written, row counts, and any document-level caveats.
```
