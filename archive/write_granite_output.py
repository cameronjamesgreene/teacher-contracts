#!/usr/bin/env python3
"""Write Granite School District GEA Professional Agreement 2020-2023 coding results.
Coded manually (2-stage retrieve+audit) by Claude Code, 2026-06-09.
Appends Granite row to output/llm_main_dataset.csv and output/llm_coding_log.csv.
"""
import csv
from pathlib import Path

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

DOCUMENT_ID   = "granite_school_district__professional_agreement_with_gea_2020_2023__7844d12c"
FILE_NAME     = "professional_agreement_with_gea_2020_2023.pdf"
DISTRICT_NAME = "Granite School District"

# ── metadata ────────────────────────────────────────────────────────────────
metadata = {
    "document_id":           DOCUMENT_ID,
    "file_name":             FILE_NAME,
    "district_name":         DISTRICT_NAME,
    "state":                 "UT",
    "document_type":         "collective bargaining agreement",
    "bargaining_unit":       "teachers (all professional employees paid on teacher salary schedule and licensed by Utah State Board of Education)",
    "start_year":            "2020",
    "end_year":              "2023",
    "effective_dates":       "July 1, 2020 – June 30, 2023",
    "school_years_covered":  "2020-2023",
    "union_name":            "Granite Education Association, Inc.",
    "source_document_notes": "Appendix A (salary schedule, p.49) is image/table-only in extracted text — salary values not extractable without OCR; all articles readable; Appendix G links to external Utah Code 53G-11-5 URL; 60 pages plus appendices",
}

# ── coded answers ────────────────────────────────────────────────────────────
# Format: qid -> (answer, evidence, page, confidence, coder_notes)
coded = {
    # ── meta ─────────────────────────────────────────────────────────────────
    "meta_doc_type_001": (
        "collective bargaining agreement",
        "PROFESSIONAL AGREEMENT between THE BOARD OF EDUCATION OF GRANITE SCHOOL DISTRICT and THE GRANITE EDUCATION ASSOCIATION INCORPORATED Covering the Period July 1, 2020 through June 30, 2023 (cover page)",
        "1", "high", ""
    ),
    "meta_effective_dates_002": (
        "July 1, 2020 – June 30, 2023",
        "This Agreement shall be effective July 1, 2020 and shall continue in effect through June 30, 2023 (Art. 31.4)",
        "47", "high", ""
    ),
    "meta_bargaining_unit_003": (
        "teachers — all professional employees paid on teacher salary schedule, licensed by Utah State Board of Education",
        "Teacher shall mean all professional employees of the District who are paid on the teacher salary schedule and who are required to be and are licensed by the State Board of Education (Art. 1.1)",
        "3", "high", ""
    ),
    "meta_document_scope_004": (
        "binding agreement",
        "This Agreement shall be a part of each individual teacher's contract. (Art. 2.2); The specific provisions of this Agreement...shall supersede any policy or directive of the Board which contradicts any such provision of this Agreement. (Art. 31.1)",
        "5 (2.2); 47 (31.1)", "high", ""
    ),
    "meta_text_usability_005": (
        "partially usable",
        "All articles (Art. 1-32) and non-salary appendices fully extractable; Appendix A (salary schedule, p.49) is image/table-only — no salary values in extracted text",
        "document", "high", "OCR needed for Appendix A (salary schedule) only"
    ),
    "meta_cites_state_law_006": (
        "yes",
        "Utah Administrative Code 53G (Art. 14.1, 19.1); Utah Right to Work Law (Art. 4.1); Utah State Retirement Act (Art. 23.1); Utah Code 53G-11-5 (Appendix G); USERRA cited as federal law (Art. 7.2.1.4)",
        "3-4 (1.1); 24 (14.1); 36 (19.1); 43 (23.1); 57 (App. G)", "high", ""
    ),
    "meta_state_law_citations_007": (
        "Utah Administrative Code 53G; Utah Right to Work Law (Art. 4.1); Utah State Retirement Act (Art. 23.1); Utah Code 53G-11-5 School District and Utah Schools for the Deaf and Blind Employee Requirements (Appendix G); Administrative Memorandum Number Thirty-Five (Art. 7.3.3); Administrative Memorandum 56 — Early Retirement Incentive Program for Teachers (Art. 23.1)",
        "References distributed throughout document; e.g. 'Utah Administrative code 53G' at Art. 14.1 and 19.1; 'Utah Code 53G-11-5' at Appendix G (p.57); 'Utah State Retirement Act' at Art. 23.1",
        "multiple", "high", "Administrative Memoranda are district-level documents cited alongside state law"
    ),
    "meta_cites_federal_law_008": (
        "yes",
        "Contract teachers returning from military leave shall be granted credit on the salary schedule in accordance with the Uniformed Services Employment and Reemployment Rights Act, USERRA. (Art. 7.2.1.4)",
        "13", "high", ""
    ),
    "meta_federal_law_citations_009": (
        "Uniformed Services Employment and Reemployment Rights Act (USERRA) (Art. 7.2.1.4)",
        "Contract teachers returning from military leave shall be granted credit on the salary schedule in accordance with the Uniformed Services Employment and Reemployment Rights Act, USERRA. (Art. 7.2.1.4)",
        "13", "high", ""
    ),
    # ── pay ──────────────────────────────────────────────────────────────────
    "pay_salary_schedule_001": (
        "yes",
        "APPENDIX A Salary Schedule listed in Table of Contents (p.49); Appendix A header present in document; Art. 7.2.2.2 describes 7 lanes: A (Bachelor's), B (BA+20), C (BA+40), D (Master's), E (MA+20), F (MA+40), G (Doctorate)",
        "49", "high", "Salary schedule table is image/table-only in extracted text; actual salary values require OCR of Appendix A"
    ),
    "pay_salary_schedule_002": (
        "discussed_unclear",
        "APPENDIX A Salary Schedule covers July 2020-June 2023; salary renegotiated annually (Art. 31.5: negotiations commence April 1 each year on salary and medical insurance); specific annual amounts not readable from extracted text — Appendix A is image-only",
        "49 (App. A); 47 (Art. 31.5)", "medium", "Three-year agreement with annual salary negotiations; Appendix A likely includes one or more annual schedules but values not in extracted text; OCR needed"
    ),
    "pay_step_increment_003": (
        "yes",
        "Continuing teachers shall receive a one-step salary increment on the salary schedule for each year of successful teaching in the District until they reach the maximum step of their salary lane. Such salary increments shall be given at the beginning of each contract year by moving forward one step on the salary schedule all continuing contract teachers who successfully completed at least one-half year (.50 FTE) of contract teaching during the previous school year. (Art. 7.2.1.3)",
        "13", "high", ""
    ),
    "pay_lane_advancement_004": (
        "yes",
        "Application for lane advancement on the salary schedule must be made on the official form provided by the Human Resources office (see Appendix C). Applications must be supported by complete official transcripts of credit...Lane change will become effective on the date the completed application form, and all official documentation forms, are received by the Human Resources office. (Art. 7.2.2.3); 7 lanes: A (Bachelor's), B (BA+20), C (BA+40), D (Master's), E (MA+20), F (MA+40), G (Doctorate) (Art. 7.2.2.2)",
        "14", "high", "Lane change effective on receipt date; salary increase reflected on next payroll after cutoff; prorated for days remaining; Prior Approval credit available (Art. 7.2.2.4)"
    ),
    "pay_prior_experience_005": (
        "yes",
        "An experienced teacher shall receive full credit on the salary schedule for the first ten years of public-school teaching experience. (Art. 7.2.1.1); Salary schedule credit for teaching experience...shall be granted automatically for full-time contracted teaching in a public school. All other teaching experience shall be evaluated by the Human Resources office and the amount of credit granted shall depend upon the extent to which such experience is equivalent to public school teaching. (Art. 7.2.1.2)",
        "13", "high", "First 10 years of public school teaching credited automatically; additional credit beyond 10 years possible for shortage positions; other teaching experience evaluated by HR"
    ),
    "pay_performance_pay_006": (
        "not_discussed",
        "No performance pay, merit pay, or evaluation-based compensation described in this agreement",
        "", "high", ""
    ),
    "pay_cost_of_living_007": (
        "not_discussed",
        "No COLA percentages or specific across-the-board raise amounts stated in CBA body; Art. 31.5 provides for annual salary negotiations but specifies no amounts; salary values in Appendix A (image-only)",
        "", "high", "Salary renegotiated annually per Art. 31.5 but no percentage stated in CBA"
    ),
    "pay_extra_duty_schedule_008": (
        "discussed_unclear",
        "Teaching hours do not apply to extra duty assignments, see 'UHSAA and/or Extra Compensation Program.' (Art. 9.2); Art. 17 provides hourly pay for adult/community school teaching at teacher's current salary rate to a maximum of step six of the teacher's salary lane — not a supplemental schedule",
        "18 (Art. 9.2); 29 (Art. 17)", "medium", "UHSAA and/or Extra Compensation Program referenced but not reproduced in this PDF; no extra-duty dollar amounts or supplemental pay schedule in document"
    ),
    "pay_diff_pay_sped_009": (
        "not_discussed",
        "No special education salary differential or stipend described in this agreement",
        "", "high", ""
    ),
    "pay_diff_pay_stem_010": (
        "not_discussed",
        "No STEM, math, or science salary differential described in this agreement",
        "", "high", ""
    ),
    "pay_diff_pay_other_011": (
        "not_discussed",
        "No subject-area or school-type salary differential described in this agreement",
        "", "high", ""
    ),
    "pay_experience_credit_indistrict_012": (
        "discussed_unclear",
        "Salary schedule credit...shall be granted automatically for full-time contracted teaching in a public school. (Art. 7.2.1.2) — applies to all public school teaching without distinguishing in-district from out-of-district; no separate in-district rule",
        "13", "medium", "No distinction between in-district and out-of-district credit; same 10-year rule applies to all public school teaching"
    ),
    "pay_experience_credit_outofdistrict_013": (
        "yes",
        "Salary schedule credit for teaching experience...shall be granted automatically for full-time contracted teaching in a public school. All other teaching experience shall be evaluated by the Human Resources office and the amount of credit granted shall depend upon the extent to which such experience is equivalent to public school teaching. (Art. 7.2.1.2); Full credit for first 10 years of public-school teaching (Art. 7.2.1.1)",
        "13", "high", "Out-of-district public school teaching: full credit up to 10 years automatically; non-public or non-standard experience evaluated on equivalence basis by HR"
    ),
    "pay_experience_credit_outofstate_014": (
        "discussed_unclear",
        "An experienced teacher shall receive full credit on the salary schedule for the first ten years of public-school teaching experience. (Art. 7.2.1.1) — no distinction between in-state and out-of-state public school teaching; same rule applies",
        "13", "medium", "No separate cap or discount for out-of-state experience; same 10-year rule applies to all public school teaching regardless of state"
    ),
    "pay_experience_credit_military_public_015": (
        "yes",
        "Contract teachers returning from military leave shall be granted credit on the salary schedule in accordance with the Uniformed Services Employment and Reemployment Rights Act, USERRA. (Art. 7.2.1.4)",
        "13", "high", "Military service credit governed by USERRA; no separate public service credit rule stated"
    ),
    # ── benefits ─────────────────────────────────────────────────────────────
    "benefits_health_001": (
        "yes",
        "All teachers under contract shall be eligible for the group insurance programs provided by the board. Insurance coverage (medical, life, etc.) for eligible contract teachers (Art. 20.1, 20.1.1)",
        "40", "high", ""
    ),
    "benefits_health_contribution_002": (
        "discussed_unclear",
        "Medical insurance premiums paid by the employee reflect a percentage of the total of medical insurance and are recalibrated annually. (Art. 20.1.2); For part-time teachers: The Board will pay the percentage of premiums equal to the teacher's FTE (Art. 20.3) — implies Board pays a share for full-time teachers but no specific employer percentage or dollar amount stated",
        "40-41", "medium", "Board contribution implied by Art. 20.3 formula but no specific employer percentage stated for full-time teachers; recalibrated annually"
    ),
    "benefits_health_employee_premium_003": (
        "discussed_unclear",
        "Medical insurance premiums paid by the employee reflect a percentage of the total of medical insurance and are recalibrated annually. (Art. 20.1.2)",
        "40", "medium", "Employee pays a percentage recalibrated annually; specific amount not stated in CBA"
    ),
    "benefits_dependent_health_004": (
        "yes",
        "Insurance enrollment requires supporting documentation (marriage certificate, dependent birth certificate, etc.) (Art. 20.1.1); Art. 20.2 addresses dual medical coverage for spouses of covered employees; Art. 23.1.3 explicitly covers retirees' previously enrolled eligible spouse and dependents",
        "40-41 (Art. 20.1, 20.2); 43 (Art. 23.1.3)", "high", ""
    ),
    "benefits_health_plan_type_005": (
        "not_discussed",
        "Group medical plan referenced but plan type (HMO, PPO, high-deductible) not specified in this agreement",
        "", "high", ""
    ),
    "benefits_dental_006": (
        "yes",
        "Teachers who retire early under the provisions...may continue to enroll in the District's group medical and dental programs for five consecutive years (Art. 23.1.3) — implies dental available to active teachers; Art. 20.1.1 lists 'medical, life, etc.' under group insurance",
        "43 (Art. 23.1.3); 40 (Art. 20.1.1)", "medium", "Dental explicitly named in early retirement continuation (Art. 23.1.3); active teacher dental implied but not described separately"
    ),
    "benefits_vision_007": (
        "not_discussed",
        "Vision or optical insurance not mentioned in this agreement",
        "", "high", ""
    ),
    "benefits_life_008": (
        "yes",
        "Insurance coverage (medical, life, etc.) for eligible contract teachers (Art. 20.1.1); non-contributory life insurance programs referenced (Art. 20.3); voluntary life insurance with evidence of insurability requirements (Art. 20.1.1); retiree life insurance up to $100,000 based on final contract base salary (Art. 23.1.3)",
        "40-43", "high", "Non-contributory life insurance provided; voluntary life insurance also available; coverage amount for retirees based on final salary up to $100,000"
    ),
    "benefits_disability_009": (
        "yes",
        "Effective 1/1/93, the majority of currently employed teachers will convert to a new accumulative sick leave program, which includes the option of both short and long-term disability. (Art. 18 preamble note); Teachers who enroll in...disability coverage after their first 30 days of contract employment must complete an evidence of insurability form. (Art. 20.1.1)",
        "30 (Art. 18 note); 40 (Art. 20.1.1)", "high", "Short and long-term disability part of accumulative sick leave program effective 1/1/93; voluntary disability coverage also available through insurance enrollment"
    ),
    # ── leave ────────────────────────────────────────────────────────────────
    "leave_sick_days_001": (
        "10",
        "Ten days of sick leave will be granted annually with full pay (Art. 18.1.1.1 provisional teachers; Art. 18.1.2.2 regular contract teachers); one additional day per additional contract month beyond regular school year (Art. 18.1.1.4, 18.1.2.3)",
        "30-31", "high", ""
    ),
    "leave_sick_accrual_002": (
        "yes; provisional teachers: cumulative to 30 teaching days; regular contract teachers (new program): accumulative with no cap stated in CBA",
        "Ten days of sick leave will be granted annually with full pay, cumulative to thirty teaching days. (Art. 18.1.1.1 for provisional teachers); regular contract teachers on new program have accumulative sick leave including short/long-term disability option (Art. 18 note); old-program regular teachers: extended sick leave up to 180 days for any one illness (Art. 18.1.2.1)",
        "30-31", "high", "Three sick leave programs: provisional (cap 30 days); regular contract new program (accumulative, no stated cap); regular contract old program (extended up to 180 days per illness)"
    ),
    "leave_sick_family_003": (
        "yes",
        "Special use of sick leave will be reviewed by the principal...and granted by the appropriate Assistant Superintendent, in the event of serious illness of a member of the immediate family, or of any other person who is a member of the same household as the teacher. (Art. 18.1.3.1); after 10 days of family illness use in one year, teacher pays substitute cost (Art. 18.1.3.5)",
        "31", "high", "Requires approval; denial can be appealed to Superintendent; after 3 days verification may be required; after 10 days teacher pays substitute cost"
    ),
    "leave_personal_days_004": (
        "4",
        "Teachers are allocated four (4) personal leave days each contract year. Personal leave can be taken for any reason, at the discretion of the teacher. (Art. 18.2.1)",
        "32", "high", ""
    ),
    "leave_personal_restrictions_005": (
        "24-hour advance notice required; no personal leave day before/after school holiday or first/last week of school without principal approval; principal limits to generally 1-2 per school per day; not in connection with job action or work stoppage",
        "A minimum of one day (24 hours) notice must be given to the principal before taking personal leave, except in cases of emergency. (Art. 18.2.2); Personal Leave should not be taken the day before or after a school holiday...or during the first or last week of school. Exceptions must have the prior approval of the school principal. (Art. 18.2.3); Limitations will be placed by the principal on the number who can take Personal Leave on any given day at that school. Generally, only one or two Personal Leave days per school, per school day can be approved. (Art. 18.2.4)",
        "32", "high", ""
    ),
    "leave_personal_conversion_006": (
        "yes",
        "Teachers who take no personal leave in a contract year will receive an amount equal to three times the current Substitute B rate. Teachers who take one personal leave day in a contract year will receive an amount equal to two times the current Substitute B rate. Teachers who take two personal leave days in a contract year will receive an amount equal to the current Substitute B rate. Teachers who take three or four personal days in a contract year will receive no additional amount. (Art. 18.2.1)",
        "32", "high", "Unused personal leave converts to cash at Substitute B rate multiples: 0 days used = 3× rate; 1 day = 2× rate; 2 days = 1× rate; 3-4 days = no incentive payment"
    ),
    "leave_bereavement_days_007": (
        "up to 5",
        "Up to five (5) days of special use of sick leave will be granted by the principal in the event of a death in the immediate family as defined above. Bereavement days can be taken within a two-week window from the time of the death. (Art. 18.1.3.6)",
        "31", "high", "Drawn from sick leave bank; must be taken within 2 weeks of death"
    ),
    "leave_bereavement_relatives_008": (
        "husband, wife, father, father-in-law, stepfather, mother, mother-in-law, stepmother, daughter, daughter-in-law, stepdaughter, son, son-in-law, stepson, brother, brother-in-law, step-brother, sister, sister-in-law, step-sister, aunt, uncle, grandchildren, grandchildren-in-law, step grandchildren, grandparent, grandparent-in-law, step grandparent, or any permanent household member",
        "The immediate family is defined as husband, wife, father, father-in-law, stepfather, mother, mother-in-law, stepmother, daughter, daughter-in-law, stepdaughter, son, son-in-law, stepson, brother, brother-in-law, step brother, sister, sister-in-law, step sister, aunt, uncle, grandchildren, grandchildren-in-law, step grandchildren, grandparent, grandparent-in-law, step grandparent, or any other person who is a permanent member of the same household as the employee. (Art. 18.1.3.2)",
        "31", "high", ""
    ),
    "leave_parental_paid_009": (
        "no",
        "One-year leaves of absence without pay shall be granted for reasons of newborn care or adoption. (Art. 18.5.2); Insurance benefits will not be provided for teachers on a one-year leave of absence without pay. (Art. 18.5.5); adoption leave allows up to 10 days of accumulated sick leave (Art. 18.8) — sick leave, not separate paid parental leave",
        "34 (18.5.2); 36 (18.8)", "high", "Art. 18.5.2 explicitly unpaid; Art. 18.8 adoption leave uses accrued sick leave (not beyond sick bank); no separate paid parental/bonding leave"
    ),
    "leave_pregnancy_disability_010": (
        "discussed_unclear",
        "Art. 18 note: new accumulative sick leave program includes the option of both short and long-term disability (effective 1/1/93); Art. 18.5.3: leave without pay available for health problems; no explicit pregnancy or childbirth leave provision; disability coverage available through insurance programs (Art. 20.1.1)",
        "30 (Art. 18 note); 34 (18.5.3)", "low", "Short/long-term disability available through sick leave program; pregnancy not specifically addressed; medical leave without pay available under Art. 18.5.3"
    ),
    "leave_adoption_childcare_011": (
        "yes",
        "One-year leaves of absence without pay shall be granted for reasons of newborn care or adoption. (Art. 18.5.2); Employees who legally adopt a child who has not previously been a member of the immediate household may take up to ten days of accumulated sick leave. The adopted child must be under the age of 18. Any leave to be considered adoption leave must be taken within 30 calendar days of the day on which the child is placed in the home of the adopting parent(s). (Art. 18.8)",
        "34 (18.5.2); 36 (18.8)", "high", "Adoption: up to 10 days accrued sick leave (Art. 18.8); newborn care/adoption: one-year unpaid leave (Art. 18.5.2); unpaid leave insurance not continued (Art. 18.5.5)"
    ),
    "leave_fmla_012": (
        "not_discussed",
        "FMLA not mentioned in this agreement",
        "", "high", ""
    ),
    "leave_absence_reporting_013": (
        "discussed_unclear",
        "In the event that a substitute teacher is not provided for a contract teacher who has requested a substitute for a sick personal or sick family day prior to 6:30 a.m., the absence will result in a 'failed-to-fill.' (Art. 9.8) — implies 6:30 a.m. notification for substitute request; no formal absence reporting system or specific procedure described",
        "19-20 (Art. 9.8)", "medium", "6:30 a.m. substitute request deadline referenced in Art. 9.8; no formal absence reporting system (AESOP, etc.) named"
    ),
    # ── workload ─────────────────────────────────────────────────────────────
    "workload_work_year_days_001": (
        "discussed_unclear",
        "The days of employment within the period set out in the contract shall be designated by the Board in the official school calendar. (Art. 7.1); Teachers shall be required to work on the days specified in the official school calendar and according to the schedule of opening and closing schools as determined by the Board. (Art. 9.1)",
        "13 (7.1); 18 (9.1)", "high", "Work year defined by official school calendar; no specific number of days stated in CBA"
    ),
    "workload_workday_length_002": (
        "elementary: report 20 min before start, remain 15 min after; secondary: report 30 min before start, remain 20 min after; no total hours specified",
        "Elementary teachers shall report to work no less than 20 minutes before the regular beginning time of the school day and shall remain on duty for at least 15 minutes after the closing time of school. (Art. 9.3.1); Secondary teachers shall report to work no less than 30 minutes before the regular beginning time of the school day and shall remain on duty for at least 20 minutes after the regular closing time of school. (Art. 9.3.2)",
        "19", "high", "No total contractual hours stated; workday defined by pre/post-school duty buffers; actual length depends on school bell schedule"
    ),
    "workload_prep_guarantee_003": (
        "yes",
        "Elementary: Class-free planning and preparation time — one early-dismissal day per week (1 hr 40 min) plus 45-minute during-day blocks (Art. 10.1-10.2); Secondary: one consultation/preparation period per day per school schedule type (Art. 7.7.1-7.7.3, 9.9)",
        "18-22 (Art. 9, 10)", "high", ""
    ),
    "workload_prep_minutes_004": (
        "elementary: 510 minutes planning + 90 minutes collaboration per 4-week month (approx. 150 min/week); plus 1 hr 40 min early-dismissal time per week; secondary: 1 consultation period per day (equal to teaching period length)",
        "Total 4-week month planning time is 510 minutes (8.5 hours) and 90 minutes collaboration time (Art. 10.2 table); each teacher will be given an additional 45-minute block of time weekly (Art. 10.2); one consultation/preparation period per day (Art. 7.7.1: seven-period schedule; Art. 9.9)",
        "20-22 (Art. 10.2); 17-18 (Art. 7.7)", "high", "Elementary: complex monthly schedule — 45 min specialist-covered block during day + 100 min on weekly early-dismissal day (varies by week); secondary: period length varies by school schedule type"
    ),
    "workload_prep_protected_005": (
        "yes",
        "Planning time shall not be used for faculty meetings. (Art. 10.4); Professional learning shall not be held during planning time. (Art. 10.5)",
        "21", "high", ""
    ),
    "workload_lunch_duty_free_006": (
        "yes",
        "All teachers shall have an uninterrupted, duty-free lunch period of at least 30 minutes daily, not counting passing time, except for teachers with assigned lunch-time responsibilities. Assigned supervisory duty, or other duty, shall not exceed 10 minutes in any lunch period. (Art. 9.5)",
        "19", "high", "District funds lunch supervision program to minimize teacher lunch duties (Art. 9.5.1); teachers who voluntarily perform extra lunch duties compensated at Secondary Lunch Monitor rate"
    ),
    "workload_lunch_minutes_007": (
        "at least 30 minutes (not counting passing time)",
        "All teachers shall have an uninterrupted, duty-free lunch period of at least 30 minutes daily, not counting passing time (Art. 9.5)",
        "19", "high", ""
    ),
    "workload_meetings_limits_008": (
        "yes",
        "Faculty meetings shall not exceed two per month, except when cleared by a School Leadership and Improvement Director in collaboration with the Executive Director of the Association and/or in the event of an emergency. Faculty meetings shall not exceed one per month beginning in the 2021-2022 school year. (Art. 9.4.1); Planning time shall not be used for faculty meetings. (Art. 10.4)",
        "19 (9.4.1); 21 (10.4)", "high", "Two-per-month limit through 2020-21; one-per-month limit beginning 2021-22 per Art. 9.4.1"
    ),
    "workload_nonteaching_duties_009": (
        "yes",
        "Only in case of emergency will teachers be required to serve as substitutes (Art. 9.8); Assigned supervisory duty at lunch shall not exceed 10 minutes in any lunch period (Art. 9.5); teachers who perform extra lunch duties compensated at Secondary Lunch Monitor rate (Art. 9.5.2-9.5.3); consultation periods used for consultation, preparation, or other professional purposes (Art. 9.9)",
        "19-20", "medium", "Emergency substituting and limited lunch supervision described; broader non-teaching duty inventory not enumerated"
    ),
    # ── class size ───────────────────────────────────────────────────────────
    "class_size_limits_001": (
        "yes",
        "ARTICLE 27 — CLASS SIZE REVIEW COMMITTEE: two committees (elementary and secondary) composed of Association and Superintendent appointees; The committees shall meet as needed to review, study, and make recommendations concerning class size issues. (Art. 27.3); District provides regular class size reports to Association (Art. 27.4)",
        "45", "medium", "Review committee established; no binding numerical caps stated in CBA; committee makes recommendations only"
    ),
    "class_elementary_max_002": (
        "not_discussed",
        "No specific elementary class-size limits stated in CBA; class size review committee process only",
        "", "high", ""
    ),
    "class_secondary_max_003": (
        "not_discussed",
        "No specific secondary class-size limits stated in CBA; class size review committee process only",
        "", "high", ""
    ),
    "class_overage_remedy_004": (
        "not_discussed",
        "No overage remedy stated; class size review committee makes recommendations but no specific remedy described",
        "", "high", ""
    ),
    # ── evaluation ───────────────────────────────────────────────────────────
    "evaluation_procedure_001": (
        "yes",
        "Teachers will be evaluated under the provisions of the Utah Administrative code 53G. (Art. 14.1); Copies of all formative and summative teacher evaluations will be given to the teacher for their personal file. (Art. 14.2); Summative evaluations, or formative evaluations which could lead to corrective discipline or non-renewal, shall only be conducted by fully licensed administrative personnel. (Art. 14.3)",
        "24", "high", "Evaluation procedures governed by Utah Administrative Code 53G; CBA adds documentation rights and copy requirements"
    ),
    "evaluation_system_002": (
        "Utah Administrative Code 53G; summative and formative evaluation framework",
        "Teachers will be evaluated under the provisions of the Utah Administrative code 53G. (Art. 14.1); Art. 14.3 references summative evaluations and formative evaluations",
        "24", "high", "Full evaluation framework in Utah Admin Code 53G; CBA does not reproduce the rubric or rating system"
    ),
    "evaluation_observation_count_003": (
        "not_discussed",
        "No observation count specified in CBA; evaluation governed by Utah Administrative Code 53G",
        "", "high", ""
    ),
    "evaluation_observation_duration_004": (
        "not_discussed",
        "No observation duration specified in CBA",
        "", "high", ""
    ),
    "evaluation_ratings_005": (
        "not_discussed",
        "No rating categories named in CBA; Art. 14.3 references corrective discipline or non-renewal outcomes but no rating labels given",
        "", "high", ""
    ),
    "evaluation_student_growth_006": (
        "not_discussed",
        "No mention of student growth, test scores, or value-added measures in evaluation provisions",
        "", "high", ""
    ),
    "evaluation_improvement_plan_007": (
        "discussed_unclear",
        "When the District intends to terminate a teacher's contract during the contract term for unsatisfactory performance, the District will inform the teacher of the fact that continued employment is in question and the reasons thereof at least thirty days before issuing the termination notice. The teacher will be given an opportunity to correct any deficiencies that precipitated possible termination of contract. (Art. 19.4.1); same preliminary notice for non-renewal (Art. 19.5.1)",
        "36 (19.4.1); 37 (19.5.1)", "medium", "30-day preliminary notice with opportunity to correct deficiencies before termination/non-renewal; no formal improvement plan structure, timeline, or support steps described"
    ),
    "evaluation_consequences_008": (
        "yes",
        "Summative evaluations, or formative evaluations which could lead to corrective discipline or non-renewal, shall only be conducted by fully licensed administrative personnel. (Art. 14.3); Teachers may be suspended or dismissed for cause under the provisions of the Utah Administrative Code 53G. (Art. 19.1)",
        "24 (14.3); 36 (19.1)", "medium", "Evaluation results can lead to corrective discipline or non-renewal (Art. 14.3); no specific evaluation rating threshold stated; RIF criterion is certifications and degree/lane, not evaluation ratings"
    ),
    # ── security ─────────────────────────────────────────────────────────────
    "security_probation_001": (
        "yes",
        "Provisional Contract Teacher shall mean all regularly assigned teachers...who have not yet completed three continuous years of contract employment as a teacher in Granite School District. (Art. 1.2); Regular Contract Teacher shall mean all regularly assigned teachers...who have completed the provisional period. (Art. 1.3)",
        "3", "high", "Different hearing rights for provisional vs. regular contract teachers (Art. 19.6 vs. 19.7)"
    ),
    "security_nonrenewal_002": (
        "yes",
        "When the District intends not to renew a teacher's contract...Non-renewal notices will be delivered or mailed at least 60 calendar days prior to the end of the contract term of the individual teacher involved. (Art. 19.5.2); notice shall state reasons; right to informal hearing for provisional/career teachers (Art. 19.6) and formal hearing for regular contract teachers (Art. 19.7)",
        "37-38", "high", ""
    ),
    "security_seniority_definition_003": (
        "yes",
        "Seniority shall mean length of continuous and current employment as a teacher under contract in the District. (Art. 1.12)",
        "3", "high", "Seniority used as tie-breaker among equally qualified applicants for transfers (Art. 16.3.4) and surplus determinations (Art. 16.4.3)"
    ),
    "security_voluntary_transfer_004": (
        "yes",
        "All teachers in the District shall be eligible to apply for transfer to any specific position in another school that has been posted as a vacancy (Art. 16.2.1); Teachers desiring a transfer to a posted position must apply online (Art. 16.2.2); if two or more current District employees equally qualified, the teacher with the greatest length of continuous and current contract service in the District shall be appointed. (Art. 16.3.4)",
        "26-27", "high", "Vacancies posted online; 5-day application deadline; seniority as tie-breaker among equally qualified District employees"
    ),
    "security_involuntary_transfer_005": (
        "yes",
        "Before recommending that a teacher be declared surplus, the principal will confer with the teacher involved to discuss the proposed action and the reasons for such action. (Art. 16.4.4); No administrative transfer will be made arbitrarily, capriciously, or without a written explanation of the reason for the transfer. (Art. 16.6.3); teacher may request meeting with School Leadership Director (Art. 16.6.5)",
        "27-28", "high", "Both surplus transfers and administrative transfers must be explained in writing; teacher conference required before surplus declaration"
    ),
    "security_rif_006": (
        "yes",
        "19.9 Reduction in Force: The reduction in force process will not apply and need not be followed unless there is a district-wide reduction in force. A district-wide reduction in force occurs when the District is unable to place teachers at the end of the surplus process prior to the beginning of a new contract year. After the surplus process is complete, the Superintendent may release as many teachers as necessary. (Art. 19.9.1)",
        "39", "high", "RIF only triggered if surplus process fails to place all teachers; meeting with Association at least 10 days before final RIF action (Art. 19.9.2)"
    ),
    "security_recall_007": (
        "yes",
        "Teachers released through this process, who are not on active corrective discipline...shall be given the first right of interview for positions for which they are qualified that become available during the six months following their release. (Art. 19.9.5); If rehired under this section, teachers will be placed on the step they would have received if they had not been released.",
        "39-40", "high", "First right of interview for 6 months after release; 7-day response window to accept interview offer; placed on step they would have received"
    ),
    "security_rif_criterion_008": (
        "primary: certification/endorsement match to staffing needs; tie-breaker: most advanced degree and lane placement",
        "All unplaced teachers will be reviewed by the number of their respective endorsements and certifications according to the staffing needs of the District. Staffing needs may include but are not limited to the following: endorsements, certifications, pattern of declining enrollments in subject area, endorsements in core academic areas, ESL and gifted endorsements, extracurricular coaching endorsements and certifications... (Art. 19.9.3); If a choice must be made between two or more teachers determined by the District to be equally well qualified for the position, the teacher with the most advanced degree and lane placement according to the teacher salary schedule will be retained. (Art. 19.9.4)",
        "39", "high", "Seniority not the primary RIF criterion; certification match to staffing needs is primary; degree/lane is the tie-breaker among equally qualified teachers"
    ),
    # ── discipline ───────────────────────────────────────────────────────────
    "discipline_just_cause_001": (
        "yes",
        "Teachers may be suspended or dismissed for cause under the provisions of the Utah Administrative Code 53G. (Art. 19.1); A list of causes considered by the Board to be possible grounds for suspension or dismissal is included in the official Policies, Rules, and Regulations of the Board. (Art. 19.2)",
        "36", "high", "'For cause' standard; grounds listed in Board policies; Utah Admin Code 53G governs"
    ),
    "discipline_dismissal_002": (
        "yes",
        "Termination during contract term: 30-day preliminary notice with opportunity to correct deficiencies; written termination notice with reasons and appeal rights at least 30 days before termination (Art. 19.4); right to informal conference and formal hearing with impartial third-party hearing examiner (Art. 19.7); Board decision final and binding (Art. 19.7.4)",
        "36-39", "high", "Procedures for provisional (informal hearing Art. 19.6) and regular contract teachers (formal hearing Art. 19.7) differ"
    ),
    # ── conduct ──────────────────────────────────────────────────────────────
    "conduct_outside_employment_001": (
        "not_discussed",
        "No general outside employment restriction in this agreement; Appendix F personal leave form notes 'Personal Leave shall not be used in order to work another job at public expense' — limited to personal leave use, not a general outside employment policy",
        "", "high", "Appendix F personal leave form note restricts using personal leave for outside paid work, but no general outside employment prohibition"
    ),
    "conduct_ethics_002": (
        "not_discussed",
        "No code of ethics or standards of conduct article in this agreement",
        "", "high", ""
    ),
    "conduct_drug_alcohol_003": (
        "not_discussed",
        "No drug-free workplace policy, drug testing, or substance abuse program described; Art. 15.1 lists 'conduct involving drugs or alcohol' as documentation that permanently remains in personnel file — but no employer conduct policy",
        "", "medium", "Art. 15.1 references drugs/alcohol in personnel file retention context only; no employee conduct policy described"
    ),
    "conduct_mandatory_reporting_004": (
        "not_discussed",
        "No mandatory reporting provision described in CBA; Appendix G provides only a URL link to Utah Code 53G-11-5 (School District Employee Requirements) without reproducing content",
        "", "medium", "Appendix G links to Utah Code 53G-11-5 which may include mandatory reporting requirements; content not reproduced in document"
    ),
    "conduct_social_media_005": (
        "not_discussed",
        "No social media rules in this agreement",
        "", "high", ""
    ),
    "conduct_acceptable_use_006": (
        "not_discussed",
        "No acceptable use policy for technology, email, or network use in this agreement",
        "", "high", ""
    ),
    # ── safety ───────────────────────────────────────────────────────────────
    "safety_health_committee_001": (
        "not_discussed",
        "No safety committee or formal health and safety provisions; Art. 8 addresses teacher facilities (restrooms, lounge, parking, telephones) but no safety committee or hazard-reporting procedure",
        "", "high", ""
    ),
    "safety_assault_protection_002": (
        "yes",
        "Whenever a teacher is absent from the teacher's assignment as a result of personal injury caused by an assault arising out of and in the course of the teacher's employment, the teacher shall be paid their full salary for the period of such absence not to exceed 180 contract days, and such paid absence shall in no event be deducted from any sick or personal leave to which such teacher is entitled. (Art. 13.4); The Board agrees to reimburse the teacher the market value of any personal property damaged or destroyed as a result of assault. (Art. 13.5); civil liability insurance provided (Art. 13.3); legal counsel may be furnished (Art. 13.2)",
        "23-24", "high", ""
    ),
    "safety_student_discipline_003": (
        "yes",
        "The Board, Administration, and Association believe that educators need to be able to teach without disruptions from disorderly students and are in full support of teachers, principals, and school staff in their duties to operate safe, orderly schools and classrooms under reasonable rules governing school conduct. Appropriate disciplinary measures should be assessed to students when students make false allegations against an employee that have an affect or impact on the teacher's employment. Refer to Administrative Memo #106. (Art. 12)",
        "23", "medium", "Art. 12 provides policy statement of support; actual student discipline procedures in Administrative Memo #106 (not reproduced in CBA)"
    ),
    "safety_remove_student_004": (
        "not_discussed",
        "No explicit teacher authority to remove a student from class stated; Art. 12 (Disruptive Student Behavior) provides policy support statement but no specific removal procedure",
        "", "high", ""
    ),
}

# ── question list (same order as codebook) ───────────────────────────────────
question_meta = [
    ("meta_doc_type_001",             "document metadata",          "What type of district document is this PDF?"),
    ("meta_effective_dates_002",      "document metadata",          "What school years or effective dates does the document cover?"),
    ("meta_bargaining_unit_003",      "document metadata",          "Which employee group or bargaining unit is covered?"),
    ("meta_document_scope_004",       "document metadata",          "Does the document state that it is binding, advisory, summary-only, or not a contract?"),
    ("meta_text_usability_005",       "document metadata",          "Is the PDF text extractable enough for reliable coding?"),
    ("meta_cites_state_law_006",      "document metadata",          "Does the document cite any state laws, statutes, or administrative codes?"),
    ("meta_state_law_citations_007",  "document metadata",          "Which state laws or statutes are cited?"),
    ("meta_cites_federal_law_008",    "document metadata",          "Does the document cite any federal laws, statutes, or regulations?"),
    ("meta_federal_law_citations_009","document metadata",          "Which federal laws or statutes are cited?"),
    ("pay_salary_schedule_001",       "compensation",               "Does the document include a teacher salary schedule or salary scale?"),
    ("pay_salary_schedule_002",       "compensation",               "What year or years does the salary schedule cover?"),
    ("pay_step_increment_003",        "compensation",               "Does the document explain annual step advancement or salary increments?"),
    ("pay_lane_advancement_004",      "compensation",               "Does the document explain requirements for moving to a higher education lane?"),
    ("pay_prior_experience_005",      "compensation",               "Does the document state how prior teaching experience is credited for salary placement?"),
    ("pay_performance_pay_006",       "compensation",               "Does the document include performance pay, merit pay, or evaluation-based compensation?"),
    ("pay_cost_of_living_007",        "compensation",               "Does the document specify across-the-board raises or COLA percentages?"),
    ("pay_extra_duty_schedule_008",   "compensation",               "Does the document include an extra-duty or supplemental pay schedule?"),
    ("pay_diff_pay_sped_009",         "compensation",               "Does the document provide additional pay, stipends, or salary differentials for special education teachers?"),
    ("pay_diff_pay_stem_010",         "compensation",               "Does the document provide additional pay, stipends, or salary differentials for teachers in STEM subjects?"),
    ("pay_diff_pay_other_011",        "compensation",               "Does the document provide additional pay, stipends, or salary differentials for teachers in high-need subjects or schools other than special education or STEM?"),
    ("pay_experience_credit_indistrict_012",  "compensation",       "Does the document specify how prior in-district teaching experience is credited for initial salary placement?"),
    ("pay_experience_credit_outofdistrict_013","compensation",      "Does the document specify how out-of-district but in-state teaching experience is credited for salary placement?"),
    ("pay_experience_credit_outofstate_014",  "compensation",       "Does the document specify how out-of-state teaching experience is credited for salary placement?"),
    ("pay_experience_credit_military_public_015","compensation",    "Does the document credit military service or other public service for salary placement?"),
    ("benefits_health_001",           "benefits",                   "Does the document state that health or medical insurance is available to teachers?"),
    ("benefits_health_contribution_002","benefits",                 "What employer contribution toward health insurance is stated?"),
    ("benefits_health_employee_premium_003","benefits",             "What employee health insurance premium or contribution is stated?"),
    ("benefits_dependent_health_004", "benefits",                   "Does the document mention dependent, spouse, family, or domestic partner health coverage?"),
    ("benefits_health_plan_type_005", "benefits",                   "What health plan types are described?"),
    ("benefits_dental_006",           "benefits",                   "Does the document state that dental insurance is available?"),
    ("benefits_vision_007",           "benefits",                   "Does the document state that vision or optical insurance is available?"),
    ("benefits_life_008",             "benefits",                   "Does the document provide district-paid or voluntary life insurance?"),
    ("benefits_disability_009",       "benefits",                   "Does the document mention short-term or long-term disability coverage?"),
    ("leave_sick_days_001",           "leave",                      "How many paid sick leave days are granted per year?"),
    ("leave_sick_accrual_002",        "leave",                      "Does sick leave accumulate or carry over, and what cap is stated?"),
    ("leave_sick_family_003",         "leave",                      "May teachers use sick leave for family illness or family care?"),
    ("leave_personal_days_004",       "leave",                      "How many paid personal leave days are granted per year?"),
    ("leave_personal_restrictions_005","leave",                     "What restrictions apply to personal leave use?"),
    ("leave_personal_conversion_006", "leave",                      "Does unused personal leave convert to sick leave, cash, or another benefit?"),
    ("leave_bereavement_days_007",    "leave",                      "How many bereavement leave days are available?"),
    ("leave_bereavement_relatives_008","leave",                     "Which relatives or household members are covered by bereavement leave?"),
    ("leave_parental_paid_009",       "leave",                      "Does the document provide paid parental, bonding, maternity, paternity, or adoption leave beyond accrued sick leave?"),
    ("leave_pregnancy_disability_010","leave",                      "Does the document address pregnancy, childbirth, or temporary disability leave?"),
    ("leave_adoption_childcare_011",  "leave",                      "Does the document provide adoption, child care, or bonding leave?"),
    ("leave_fmla_012",                "leave",                      "Does the document discuss Family and Medical Leave Act rights or equivalent family medical leave?"),
    ("leave_absence_reporting_013",   "leave",                      "Does the document specify absence reporting or substitute-request procedures for teachers?"),
    ("workload_work_year_days_001",   "workload",                   "How many teacher work days or duty days are required in the regular work year?"),
    ("workload_workday_length_002",   "workload",                   "What is the required length of the teacher workday?"),
    ("workload_prep_guarantee_003",   "workload",                   "Does the document guarantee teacher planning or preparation time?"),
    ("workload_prep_minutes_004",     "workload",                   "How much planning or preparation time is guaranteed?"),
    ("workload_prep_protected_005",   "workload",                   "Does the document restrict use of planning time for meetings, coverage, or other duties?"),
    ("workload_lunch_duty_free_006",  "workload",                   "Does the document guarantee a duty-free lunch?"),
    ("workload_lunch_minutes_007",    "workload",                   "How many minutes is the lunch period?"),
    ("workload_meetings_limits_008",  "workload",                   "Does the document limit required faculty, staff, department, or PLC meetings?"),
    ("workload_nonteaching_duties_009","workload",                  "Does the document describe non-teaching duties such as supervision, lunch duty, bus duty, hall duty, or clerical duties?"),
    ("class_size_limits_001",         "class size",                 "Does the document include class-size limits, caps, goals, or review procedures?"),
    ("class_elementary_max_002",      "class size",                 "What elementary class-size maximums or targets are stated?"),
    ("class_secondary_max_003",       "class size",                 "What middle or high school class-size maximums or targets are stated?"),
    ("class_overage_remedy_004",      "class size",                 "Does the document provide remedies when class-size limits are exceeded?"),
    ("evaluation_procedure_001",      "evaluation",                 "Does the document describe teacher evaluation procedures?"),
    ("evaluation_system_002",         "evaluation",                 "What evaluation system, framework, or model is named?"),
    ("evaluation_observation_count_003","evaluation",              "How many formal observations are required?"),
    ("evaluation_observation_duration_004","evaluation",           "Does the document specify observation duration or minimum length?"),
    ("evaluation_ratings_005",        "evaluation",                 "What rating categories or performance levels are used?"),
    ("evaluation_student_growth_006", "evaluation",                 "Does the evaluation use student growth, test scores, value-added, or student outcomes?"),
    ("evaluation_improvement_plan_007","evaluation",               "Does the document describe improvement plans, remediation plans, or professional support plans for low-rated teachers?"),
    ("evaluation_consequences_008",   "evaluation",                 "Does the document state how evaluation results are used in decisions about tenure, layoff priority, transfers, or compensation?"),
    ("security_probation_001",        "job security",               "Does the document define probationary, provisional, temporary, permanent, tenure, or continuing contract status?"),
    ("security_nonrenewal_002",       "job security",               "Does the document state nonrenewal notice, hearing, or appeal rules?"),
    ("security_seniority_definition_003","seniority",              "Does the document define seniority?"),
    ("security_voluntary_transfer_004","transfers",                 "Does the document describe voluntary transfer procedures?"),
    ("security_involuntary_transfer_005","transfers",               "Does the document describe involuntary transfer or reassignment procedures?"),
    ("security_rif_006",              "layoffs",                    "Does the document describe layoff, reduction in force, retrenchment, or staff reduction procedures?"),
    ("security_recall_007",           "layoffs",                    "Does the document provide recall or callback rights after layoff?"),
    ("security_rif_criterion_008",    "layoffs",                    "What is the primary criterion for determining the order of layoff among teachers?"),
    ("discipline_just_cause_001",     "discipline",                 "Does the document require just cause, proper cause, or cause for teacher discipline or dismissal?"),
    ("discipline_dismissal_002",      "discipline",                 "Does the document describe dismissal, termination, discharge, or contract cancellation procedures?"),
    ("conduct_outside_employment_001","teacher rights and conduct", "Does the document restrict outside employment, tutoring, or conflicts of interest?"),
    ("conduct_ethics_002",            "teacher rights and conduct", "Does the document include a code of ethics, standards of conduct, or professional responsibility rules?"),
    ("conduct_drug_alcohol_003",      "teacher rights and conduct", "Does the document include drug-free workplace, alcohol, or substance-abuse rules?"),
    ("conduct_mandatory_reporting_004","teacher rights and conduct","Does the document describe mandatory reporting of child abuse, neglect, educator misconduct, or threats?"),
    ("conduct_social_media_005",      "teacher rights and conduct", "Does the document regulate employee social media use?"),
    ("conduct_acceptable_use_006",    "teacher rights and conduct", "Does the document include acceptable-use, email, internet, or network technology rules for employees?"),
    ("safety_health_committee_001",   "safety and working conditions","Does the document include health and safety provisions or a safety committee?"),
    ("safety_assault_protection_002", "safety and working conditions","Does the document provide teacher assault protections or procedures after assault?"),
    ("safety_student_discipline_003", "safety and working conditions","Does the document describe student discipline or behavior-management procedures affecting teachers?"),
    ("safety_remove_student_004",     "safety and working conditions","Does the document state a teacher's authority to remove a student from class?"),
]

# ── build wide row ────────────────────────────────────────────────────────────
wide_row = dict(metadata)
for qid, _topic, _q in question_meta:
    ans, ev, pg, cf, _cn = coded[qid]
    wide_row[f"{qid}_answer"]     = ans
    wide_row[f"{qid}_evidence"]   = ev
    wide_row[f"{qid}_page"]       = pg
    wide_row[f"{qid}_confidence"] = cf

# ── update llm_main_dataset.csv (preserve existing rows, replace if same doc_id) ──
main_path = OUT_DIR / "llm_main_dataset.csv"
meta_fields = list(metadata.keys())
q_fields = []
for qid, _, _ in question_meta:
    q_fields += [f"{qid}_answer", f"{qid}_evidence", f"{qid}_page", f"{qid}_confidence"]
wide_fields = meta_fields + q_fields

existing_rows = []
if main_path.exists():
    with main_path.open(encoding="utf-8") as f:
        existing_rows = [r for r in csv.DictReader(f)
                         if r.get("document_id") != DOCUMENT_ID]

all_rows = existing_rows + [wide_row]
with main_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=wide_fields)
    w.writeheader()
    w.writerows(all_rows)
print(f"Wrote {main_path}  ({len(all_rows)} rows, {len(wide_fields)} columns)")

# ── update llm_coding_log.csv ─────────────────────────────────────────────────
log_fields = ["document_id","file_name","Question ID","topic category",
              "question","answer","evidence","page number","confidence","coder notes"]
log_path = OUT_DIR / "llm_coding_log.csv"

existing_log = []
if log_path.exists():
    with log_path.open(encoding="utf-8") as f:
        existing_log = [r for r in csv.DictReader(f)
                        if r.get("document_id") != DOCUMENT_ID]

new_log_rows = []
for qid, topic, question in question_meta:
    ans, ev, pg, cf, cn = coded[qid]
    new_log_rows.append({
        "document_id":    DOCUMENT_ID,
        "file_name":      FILE_NAME,
        "Question ID":    qid,
        "topic category": topic,
        "question":       question,
        "answer":         ans,
        "evidence":       ev,
        "page number":    pg,
        "confidence":     cf,
        "coder notes":    cn,
    })

all_log = existing_log + new_log_rows
with log_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=log_fields)
    w.writeheader()
    w.writerows(all_log)
print(f"Wrote {log_path}  ({len(all_log)} rows total, {len(new_log_rows)} new Granite rows)")
