# Prompt Log

## 2026-05-28: Master Question Bank Request

```text
You are helping design a data-extraction exercise about public-school teaching jobs.

The ultimate goal is to create a spreadsheet in which each row is a district document, such as a collective bargaining agreement, employee handbook, salary schedule, benefits document, or district policy manual, and each column records whether and how that document addresses a specific aspect of a teaching job.

You should **not** fill out the spreadsheet. Instead, your task is to create the **master list of questions** that a later AI agent will ask of each PDF.

The PDFs are stored in the folder: nctq_contracts. They cover many U.S. public school districts and multiple years.

Please examine the PDFs carefully and identify the recurring job characteristics that appear across these documents. Each subfolder is a school district and it contains contracts/docs for multiple year. Randomly select 20 folders-districts; in each, pick two documents. Think from the perspective of a teacher deciding whether to apply for a job in a particular district. The questions should cover all aspects of the job that a prospective teacher would care about, including pay, benefits, workload, job security, rights, discipline, evaluation, leave, working conditions, amenities, and workplace rules.

Your output should be a comprehensive, structured question bank. Each question should be written so that another AI agent can answer it document-by-document and enter the answer into a spreadsheet.

For each question, provide the following fields:

1. **Question ID**
   A short unique identifier, such as `pay_salary_schedule_001`.

2. **Topic category**
   For example: compensation, benefits, leave, workload, class size, evaluation, discipline, grievance procedures, transfers, seniority, layoffs, professional development, teacher conduct, amenities, union rights, safety, etc.

3. **Question**
   A clear, specific question that can be asked of each document.

4. **Answer type**
   Indicate whether the answer should be yes/no, numeric, dollar amount, percentage, categorical, date, short text, or extracted quote.

5. **What to extract if discussed**
   Specify the exact information the later agent should collect if the document discusses the topic.

6. **Suggested keywords or sections to search**
   Include likely words, phrases, or section headings that may help locate the relevant information in the PDFs.

7. **Expected frequency across documents**
   Classify the item as likely frequent, occasional, or rare, based on how often it appears across the corpus.

8. **Notes for consistent coding**
   Include any instructions needed to avoid ambiguity, such as how to distinguish “not discussed” from “discussed but unclear,” or whether the information may appear in a separate salary schedule, benefits guide, appendix, or board policy document.

The questions should be atomic and spreadsheet-friendly. Do not combine multiple concepts into one question unless they are always reported together. For example, instead of asking “Does the district provide health, dental, and vision insurance?”, write separate questions for health insurance, dental insurance, and vision insurance.

The questions could include, but should not be limited to (or do not have to include if not appropriate), topics such as:

* Whether the document includes a teacher salary schedule
* Number of salary steps
* Number and type of education lanes
* Starting salary for BA, MA, PhD, or equivalent lanes
* Maximum salary on the schedule
* Difference in pay between Step 1 BA and Step 1 PhD
* Extra-duty pay schedules
* Coaching stipends
* Department chair, club sponsor, summer school, or other supplemental pay
* Health insurance availability
* Employer contribution to health insurance
* Dependent health insurance coverage
* Dental insurance
* Vision insurance
* Life insurance
* Disability insurance
* Retirement or pension contributions
* Sick leave
* Personal leave
* Parental leave
* Bereavement leave
* Sabbaticals
* Length of school day
* Length of school year
* Required work hours
* Guaranteed preparation time
* Lunch periods
* Duty-free lunch
* Class-size limits
* Student-teacher ratios
* Teaching load
* Number of course preparations
* Substitute coverage expectations
* Teacher evaluation procedures
* Observation requirements
* Tenure, probationary status, or continuing contract rules
* Promotion or advancement procedures
* Seniority rules
* Transfers and reassignment rules
* Vacancies and posting requirements
* Layoff and recall procedures
* Discipline and dismissal procedures
* Due-process rights
* Grievance procedures
* Arbitration rights
* Drug testing policies
* Dress code
* Codes of conduct
* Restrictions on outside employment
* Technology, email, and internet-use policies
* Academic freedom or instructional autonomy
* Curriculum requirements
* Professional development requirements
* Tuition reimbursement
* Mentoring or induction for new teachers
* Teacher supplies, classroom materials, or reimbursements
* Parking
* Teacher lounges or workspaces
* Clerical support
* Safety provisions
* Student discipline procedures
* Assault leave or protections from student violence
* Union rights
* Payroll deduction of dues
* Release time for union duties
* Labor-management committees

Add any additional questions that appear relevant based on the PDFs. The final list should be comprehensive enough that a later agent could use it to build a detailed spreadsheet comparing teaching jobs across districts.

Important coding principles:

* Do not assume a policy exists unless the document states it.
* Include questions that distinguish among: not discussed, discussed but unclear, and discussed with specific details.
* When relevant, include questions that ask the later agent to extract page numbers, section names, or short supporting quotes.
* If a topic may appear in a separate document rather than the main collective bargaining agreement, note this.
* Prioritize questions that can be answered consistently across many PDFs.
* Avoid vague questions such as “Is the job good?” or “Are benefits generous?” Instead, ask concrete questions whose answers can be coded.
* The final output should be a table, with one row per question and the fields listed above as columns.

As you are working, write an AGENTS.md file (for future agents) and a readme.md (for myself). The table should be contained and saved in a separate md file called extraction_elements.md.
```

## 2026-05-28: Prompt Logging Request

```text
please make sure you save this exact prompt where you see fit in the folder, or write a log.
```

## 2026-05-29: LLM Dataset Regeneration Request

```text
Thanks. As far as I understand, this database is generated using keyword extraction. Please do the following:

1) re-generate an AI prompt that calls for LLM agents to answer the questions listed in extraction_elements
2) run that prompt and generate the new spreadsheet.

As you go, read but also update AGENTS and prompt_log.
```

Implementation note: the reusable LLM-agent prompt generated from this request is saved as `contract_coding/llm_agent_prompt.md`.
