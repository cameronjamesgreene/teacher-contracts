# Instructions for Future Agents

This folder contains design materials for a document-level extraction exercise about public-school teaching jobs. The source PDFs are in `../nctq_contracts`, organized one district per folder.

## Scope

- Do not fill out the district spreadsheet unless explicitly asked.
- Use `extraction_elements_reduced.md` as the master question bank.
- Treat each PDF as its own observation. Do not merge information across documents unless the task explicitly requests district-year aggregation.
- Store any new deliverables for this exercise in `contract_coding_CG_June_9`.

## Coding Rules

- Do not assume a policy exists. Code only what the PDF states.
- For new document-level datasets, distinguish these cases in every answer:
  - `yes` or an extracted value: the document clearly states the provision exists or provides the requested value.
  - `no`: the document clearly states the provision does not exist.
  - `not_discussed`: the topic is absent from the document.
  - `discussed_unclear`: the topic appears, but the answer is unclear or not specific enough to code.
  - `not_applicable`: the question does not apply to the document type or bargaining unit.
- For every answer other than `not_discussed`, record page number, section heading, and a verbatim supporting quote (no paraphrase) when the spreadsheet allows evidence fields. The quote must include the full clause containing the verb that governs the provision (e.g., shall, must, may, shall not, is entitled to).
- For every answer other than `not_discussed` and `not_applicable`, also code a `modality` value: `mandatory` (shall, must, will, is required to, is entitled to, shall receive/be paid/be granted), `discretionary` (may, can, is permitted/allowed/authorized to, at the discretion of), or `prohibited` (shall not, may not, is prohibited from). See `llm_agent_prompt.md` for the full coding rules and examples.
- If the PDF points to an external salary schedule, benefits guide, board policy, website, appendix, or MOU that is not included in the PDF, code only that the external source is referenced. Do not look it up unless instructed.
- If a table is split across pages, preserve the labels used by the document, such as BA, BA+30, MA, MA+45, PhD, Step 1, Career Increment, or Performance Pay.
- If a document covers multiple employee groups, code the teacher or certificated instructional unit. If teacher-specific information cannot be separated, note the broader unit.
- Watch out for clauses whose subject is an excluded classification (principals, administrators, managers, supervisors) rather than the teacher/certificated bargaining unit. Such a clause does not support a `yes` answer or any modality coding for a teacher-focused question, even if it uses the same entitlement language as a teacher provision (e.g., "School principals... are entitled to 6 weeks of vacation annually" is a management right, not a teacher right). Confirm the clause's subject before using it as evidence.
- If an answer or evidence quote includes a position, classification, or salary-schedule code or acronym (such as `ET-15`, `EG-09`, or `BA+30`) that would be unclear to a general reader, spell out or define the term using the document's own definition (e.g., from a recognition article, definitions section, or salary schedule legend) if the document gives one; if the document does not define the term, note that it is undefined.

## LLM Coding Workflow

- Use `llm_agent_prompt.md` when assigning LLM agents to code documents against the codebook.
- The prior files in `output/sample_main_dataset.csv` and `output/sample_coding_log.csv` were produced by keyword and pattern extraction. They are useful for locating candidate sections, but they are not authoritative coded data.
- LLM-coded outputs should be written separately under `output`, with names that identify the coding method, such as `llm_main_dataset.csv` and `llm_coding_log.csv`.
- Every Question ID in `extraction_elements_reduced.md` must produce five wide fields: `{question_id}_answer`, `{question_id}_evidence`, `{question_id}_page`, `{question_id}_confidence`, and `{question_id}_modality`.
- The long coding log must contain one row per document-question pair and include coder notes.
- Confidence values must be `high`, `medium`, or `low`.
- If a PDF is scanned, table-heavy, or has poor extracted text, note the limitation in `source_document_notes` and use low confidence for affected fields.
- When multiple LLM agents work in parallel, assign disjoint PDF lists and disjoint output files. Workers should not edit `AGENTS.md`, `prompt_log.md`, `extraction_elements_reduced.md`, or another worker's outputs.

## Recommended Workflow

1. Identify document type, coverage years, bargaining unit, and whether text extraction is usable.
2. Run `pdfinfo` for page count and `pdftotext -layout` for searchable text.
3. Read the full document, using `rg` over extracted text for suggested keywords and synonyms in `extraction_elements_reduced.md`.
4. Check the table of contents, appendices, salary schedules, benefits sections, leave sections, and policy cross-references.
5. Return to the PDF or extracted text for exact page numbers and short quotes.
6. Validate that the wide output has all expected fields and that the long output has one row per document per Question ID.

## Common Places to Check

- CBAs: articles titled salary, compensation, benefits, leaves, working conditions, teacher day, class size, evaluation, transfers, seniority, reduction in force, grievance, discipline, association rights, and appendices.
- Handbooks: sections titled benefits, leave, standards of conduct, technology resources, social media, drug-free workplace, complaints and grievances, safety, child abuse reporting, student discipline, and employee conduct.
- Policy manuals: personnel policies, employee welfare, professional conduct, evaluation, grievances, dismissal, safety, acceptable use, and board policy code references.
- Salary-only PDFs and tentative agreements: appendices, summary tables, settlement highlights, and redlined language may contain only a subset of elements.

## Consistency Notes

- Page numbers should match the PDF viewer page when possible. If the printed page number differs, record both or state which one is used.
- Do not convert daily, hourly, or annual pay unless the document gives enough information and the spreadsheet explicitly asks for a converted measure.
- Treat statutory restatements as discussed if the document itself states them, but note that the rule may be a state-law baseline rather than a district-negotiated benefit.
- A "likely frequent" item in the bank may still be `not_discussed` for salary-only, benefits-only, scanned, or tentative-agreement documents.
