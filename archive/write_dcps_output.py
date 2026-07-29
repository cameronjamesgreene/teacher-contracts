#!/usr/bin/env python3
"""Write DCPS WTU CBA 2023-2028 coding results to CSV output files.
Coded manually (2-stage retrieve+audit) by Claude Code, 2026-06-09.
"""
import csv
from pathlib import Path

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

DOCUMENT_ID   = "district_of_columbia_public_schools__dcps_wtu_cba_2023_2028__2af6e7cf"
FILE_NAME     = "DCPS_WTU_CBA_2023-2028.pdf"
DISTRICT_NAME = "District of Columbia Public Schools"

# ── metadata ────────────────────────────────────────────────────────────────
metadata = {
    "document_id":            DOCUMENT_ID,
    "file_name":              FILE_NAME,
    "district_name":          DISTRICT_NAME,
    "state":                  "DC",
    "document_type":          "collective bargaining agreement",
    "bargaining_unit":        "teachers (ET-15, ET-15/11, ET-15/12, EG-09 — classroom teachers, counselors, librarians, therapists, coaches, and other certificated staff)",
    "start_year":             "2023",
    "end_year":               "2028",
    "effective_dates":        "October 1, 2023 – September 30, 2028",
    "school_years_covered":   "2023-2028",
    "union_name":             "Washington Teachers' Union, Local #6, American Federation of Teachers, AFL-CIO",
    "source_document_notes":  "text_status=usable; full text extractable including salary schedule tables; 112 pages; includes FY2024-FY2028 ET-15 and EG-09 salary schedules and two MOAs",
}

# ── coded answers ────────────────────────────────────────────────────────────
# Format: qid -> (answer, evidence, page, confidence, coder_notes)
coded = {
    # ── meta ─────────────────────────────────────────────────────────────────
    "meta_doc_type_001": (
        "collective bargaining agreement",
        "COLLECTIVE BARGAINING AGREEMENT BETWEEN THE WASHINGTON TEACHERS' UNION LOCAL #6 OF THE AMERICAN FEDERATION OF TEACHERS AND THE DISTRICT OF COLUMBIA PUBLIC SCHOOLS OCTOBER 1, 2023 – SEPTEMBER 30, 2028",
        "1", "high", ""
    ),
    "meta_effective_dates_002": (
        "October 1, 2023 – September 30, 2028",
        "This Agreement shall be effective as of the date of DC Council approval, and shall remain in full force and effect until the 30th day of September 2028. (Art. 42.1)",
        "102", "high", ""
    ),
    "meta_bargaining_unit_003": (
        "teachers (ET-15, ET-15/11, ET-15/12, and EG-09 employees including classroom teachers, counselors, librarians, therapists, and other certificated staff)",
        "DCPS recognizes the WTU as the sole and exclusive bargaining representative...for employees in the occupational bargaining units and job classifications defined in this article, and collectively referred to in this Agreement as 'Teachers.' (Art. 1.1)",
        "5", "high", ""
    ),
    "meta_document_scope_004": (
        "binding agreement",
        "This Agreement shall remain in full force and effect until the 30th day of September 2028. (Art. 42.1); grievances subject to binding arbitration (Art. 6.4.3.3)",
        "102", "high", ""
    ),
    "meta_text_usability_005": (
        "usable",
        "Full text extracted including all articles and salary schedule tables; all articles readable",
        "document", "high", ""
    ),
    "meta_cites_state_law_006": (
        "yes",
        "D.C. Code § 38-174 (Chancellor); D.C. Code § 1-617.18 (evaluation non-negotiable); D.C. Code § 1-624.2 (workers comp); Title 5 DCMR (multiple sections); DCMR Chapter 25 (student discipline); D.C. Code 22-3201 through 22-3217 (controlled substances)",
        "multiple", "high", "DC law/code treated as state law given DC quasi-state status"
    ),
    "meta_state_law_citations_007": (
        "D.C. Code § 38-174; D.C. Code § 1-631.05; D.C. Code § 1-617.18; D.C. Code § 1-624.2; D.C. Code § 1-613.3(m); D.C. Code 22-3201 through 22-3217; D.C. Code 33-601 through 33-603; D.C. Code § 1-612.03(p); D.C. Official Code 1-611.06(d); Title 5 DCMR (various chapters including Chapter 14 and Chapter 25); 5 DCMR Sections 1306.8-1306.13",
        "Scattered throughout document; e.g. 'D.C. Code § 1-617.18' at Art. 15.1; 'Title 5, DCMR Chapter 25' at Art. 18.1.1; 'D.C. Code § 1-624.2' at Art. 17.4.7",
        "multiple", "high", ""
    ),
    "meta_cites_federal_law_008": (
        "yes",
        "Family and Medical Leave Act of 1993 (Art. 17.7); 20 U.S.C. § 6316(b)(8)(B)(iii) No Child Left Behind Act (Art. 2.9.1.1); Individuals with Disabilities Education Act (Art. 23.13.2.1); Internal Revenue Code § 414(h)(2) (Art. 38.8); IRC § 401(a) (Art. 37.7.2)",
        "multiple", "high", ""
    ),
    "meta_federal_law_citations_009": (
        "Family and Medical Leave Act of 1993 (as amended); District of Columbia Family and Medical Leave Act of 1990; 20 U.S.C. § 6316(b)(8)(B)(iii) (No Child Left Behind Act); Individuals with Disabilities Education Act (IDEA); Internal Revenue Code § 414(h)(2); Internal Revenue Code § 401(a)",
        "Teachers shall receive benefits as provided in the Family and Medical Leave Act of 1993, as amended, and as provided in the District of Columbia Family and Medical Leave Act of 1990. (Art. 17.7)",
        "multiple", "high", ""
    ),
    # ── pay ──────────────────────────────────────────────────────────────────
    "pay_salary_schedule_001": (
        "yes",
        "Table of Contents lists: FY 2024 ET 15 SALARY SCHEDULE (p.107); FY 2025 ET 15 SALARY SCHEDULE (p.108); FY 2026-2028 schedules (pp.109-111); FY 2024–2028 EG 09 SALARY SCHEDULE (p.112); salary tables present in extracted text",
        "107-112", "high", ""
    ),
    "pay_salary_schedule_002": (
        "FY2025 (effective October 6, 2024; 2.0% adjustment); FY2026 (effective October 5, 2025; 3.0%); FY2027 (effective October 4, 2026; 3.0%); FY2028 (effective October 3, 2027; 4.0%); ET-15 10-month, 11-month, 12-month and EG-09 schedules; no FY2024 salary schedule included — FY2024 compensation handled by retroactive 4.0% bonus (Art. 36.2.3)",
        "FY 2025 ET 15 Salary Schedule - 10 Month, Adjustment: 2.0%, Effective October 6, 2024; FY 2028 ET 15 Salary Schedule, Effective October 3, 2027, Adjustment: 4.0%; EG 09 Salary Schedule FY 25-28 (salary schedule headers, p.107-112)",
        "107-112", "high", "FY2024 not a separate schedule; covered by retroactive bonus provision at Art. 36.2.3 (p.92)"
    ),
    "pay_step_increment_003": (
        "yes",
        "Teachers who receive an evaluation score of Minimally Effective shall be held on their current salary step. Such Teachers who earn an evaluation scored of Effective or higher shall be immediately moved to the next step. (Art. 36.6.1-36.6.2)",
        "94", "high", ""
    ),
    "pay_lane_advancement_004": (
        "discussed_unclear",
        "Salary schedule shows five education lanes (Bachelors, Bachelors+15, Bachelors+30/Masters, Masters+30, Masters+60/PhD) but no explicit rules for lane advancement (credits required, prior approval, deadline, effective date) appear in the CBA text; Art. 38.6 addresses initial salary placement only",
        "107-112 (schedule); 99 (Art. 38.6)", "medium", "Lane structure visible in schedule; advancement rules not stated in CBA body"
    ),
    "pay_prior_experience_005": (
        "yes",
        "Teachers shall receive a service credit of up to nine (9) years for: each year of comparable, satisfactory, full-time service in another school system, as determined by DCPS; and each year of work in another field deemed applicable to education, as determined by DCPS. (Art. 36.7)",
        "94", "high", ""
    ),
    "pay_performance_pay_006": (
        "yes",
        "DCPS shall implement an individual performance-based pay and/or bonus system in the fall of 2010 in collaboration with the WTU that results in Teachers in the system being among the highest compensated educators in the nation. (Art. 36.3); The individual performance-based pay system shall be on a voluntary 'qualify-in' basis, with the qualifications including student growth for tested and non-tested grades and subjects and not requiring permanent status Teachers to relinquish their tenure. (Art. 36.4)",
        "93-94", "high", "System is voluntary ('qualify-in'); criteria include student growth and other measures agreed upon by DCPS and WTU"
    ),
    "pay_cost_of_living_007": (
        "FY2025: 2; FY2026: 3; FY2027: 3; FY2028: 4; FY2024: 4.0 retroactive bonus",
        "DCPS shall provide the following base salary raises for the following years: FY2025 2% FY2026 3% FY2027 3% FY2028 4% (Art. 36.2.1); For the 2023-2024 fiscal year, all DCPS employees...shall be paid retroactively a bonus of 4.0%. (Art. 36.2.3)",
        "92", "high", "Raises effective October 1 of each FY; FY2024 paid as one-time bonus not base increase"
    ),
    "pay_extra_duty_schedule_008": (
        "yes",
        "Extra-duty pay shall remain at the levels in effect as of the 2021-2022 school year until changes are mutually agreed to by the Parties. (Art. 36.9); ARTICLE 27 - EXTRA DUTY PAY ACTIVITIES listed in Table of Contents at p. 88",
        "88 (Art. 27); 94 (Art. 36.9)", "high", "Specific 2021-22 extra-duty pay schedule not reproduced in this PDF; referenced as continuing"
    ),
    "pay_diff_pay_sped_009": (
        "yes",
        "For the 2022-2023 and 2023-2024 school years, WTU bargaining unit members in 'hard to fill' positions shall receive a $1,500 retention bonus. Hard to fill positions are defined as Social Worker, Psychologist, Special Education, Math/Science, World Languages, Speech Pathologist, Occupational Therapist, Physical Therapist, and ESL/ESL Itinerant. (Art. 36.2.4); WTU bargaining unit members taking on Special Education Designee, LEA Representative, and Case Manager duties will receive an annual stipend of $1,500 (Art. 36.2.5)",
        "92", "high", "Retention bonus and stipend applied to 2022-23 and 2023-24 school years per explicit Art. 36.2.4-36.2.5; not extended beyond 2023-24 in this CBA"
    ),
    "pay_diff_pay_stem_010": (
        "yes",
        "For the 2022-2023 and 2023-2024 school years, WTU bargaining unit members in 'hard to fill' positions shall receive a $1,500 retention bonus. Hard to fill positions are defined as Social Worker, Psychologist, Special Education, Math/Science, World Languages, Speech Pathologist, Occupational Therapist, Physical Therapist, and ESL/ESL Itinerant. (Art. 36.2.4)",
        "92", "high", "Math/Science listed as hard-to-fill; $1,500 retention bonus for 2022-23 and 2023-24 school years; no STEM extension beyond 2023-24 stated"
    ),
    "pay_diff_pay_other_011": (
        "yes",
        "For the 2022-2023 and 2023-2024 school years, WTU bargaining unit members in 'hard to fill' positions shall receive a $1,500 retention bonus. Hard to fill positions are defined as Social Worker, Psychologist, Special Education, Math/Science, World Languages, Speech Pathologist, Occupational Therapist, Physical Therapist, and ESL/ESL Itinerant. (Art. 36.2.4)",
        "92", "high", "Covers World Languages and ESL/ESL Itinerant (non-SPED, non-STEM); $1,500 retention bonus for 2022-23 and 2023-24 school years; also includes Social Worker and Psychologist; see pay_diff_pay_sped_009 and pay_diff_pay_stem_010 for overlapping categories"
    ),
    "pay_experience_credit_indistrict_012": (
        "discussed_unclear",
        "salary placement shall be granted for each year of satisfactory service in a full-time, equivalent position in or outside DCPS, in an educational program of recognized standing as determined by DCPS, except that salary placement shall be limited to nine (9) years. (Art. 38.6) — does not distinguish in-district from out-of-district credit",
        "99", "medium", "One rule applies to all prior service without distinguishing source"
    ),
    "pay_experience_credit_outofdistrict_013": (
        "discussed_unclear",
        "Teachers shall receive a service credit of up to nine (9) years for: each year of comparable, satisfactory, full-time service in another school system, as determined by DCPS (Art. 36.7) — applies broadly; no separate in-state vs. out-of-district rule",
        "94", "medium", "One rule applies to all out-of-DCPS service regardless of geography"
    ),
    "pay_experience_credit_outofstate_014": (
        "discussed_unclear",
        "Teachers shall receive a service credit of up to nine (9) years for: each year of comparable, satisfactory, full-time service in another school system, as determined by DCPS (Art. 36.7) — no distinction between in-state and out-of-state",
        "94", "medium", "No cap differential for out-of-state vs. in-state"
    ),
    "pay_experience_credit_military_public_015": (
        "discussed_unclear",
        "each year of work in another field deemed applicable to education, as determined by DCPS (Art. 36.7.2) — broad language may include military/public service but military service is not explicitly stated as creditable for salary placement; Art. 17.5.5 covers military leave rights only",
        "94", "low", "Military leave rights covered (Art. 17.5.5) but salary credit for military service not explicitly confirmed"
    ),
    # ── benefits ─────────────────────────────────────────────────────────────
    "benefits_health_001": (
        "not_discussed",
        "Article 37 (Benefits) covers only optical plan, dental plan, legal services plan, and pension; no health/medical insurance provision in this CBA; DC government employees receive health coverage through DCHR separate from this CBA",
        "", "high", ""
    ),
    "benefits_health_contribution_002": (
        "not_discussed", "", "", "high", ""
    ),
    "benefits_health_employee_premium_003": (
        "not_discussed", "", "", "high", ""
    ),
    "benefits_dependent_health_004": (
        "not_discussed", "", "", "high", ""
    ),
    "benefits_health_plan_type_005": (
        "not_discussed", "", "", "high", ""
    ),
    "benefits_dental_006": (
        "yes",
        "DCPS agrees to contribute the following amounts per month, per Teacher, towards a dental insurance plan to be contracted by the WTU: Self $45.87 / Family $87.57 (FY2024); increasing through FY2028 (Art. 37.3)",
        "98", "high", "WTU contracts the plan; DCPS contributes fixed monthly amounts per schedule"
    ),
    "benefits_vision_007": (
        "yes",
        "DCPS agrees to contribute the following amounts per month, per Teacher, towards an optical insurance plan to be contracted by the WTU: Self/Family $21.62 (1/1/2024-12/31/2024); increasing through 12/31/2028 (Art. 37.2)",
        "97", "high", "Labeled 'optical' plan; self/family coverage combined in single contribution tier"
    ),
    "benefits_life_008": (
        "not_discussed",
        "No life insurance provision in Article 37 or elsewhere in this CBA",
        "", "high", ""
    ),
    "benefits_disability_009": (
        "not_discussed",
        "No disability insurance described; workers' compensation referenced at Art. 17.4.7 (D.C. Code § 1-624.2) but that is workers' comp, not a disability insurance plan",
        "", "high", ""
    ),
    # ── leave ────────────────────────────────────────────────────────────────
    "leave_sick_days_001": (
        "12 days (10-month ET-15); 15 days (12-month ET-15/12 and EG-09); 13.5 days (11-month ET-15/11)",
        "Twelve (12) days (96 hours) of sick leave are posted at the beginning of each school year for ten (10) month teachers. (Art. 17.1.1); Fifteen days (15) days (120 hours) of sick leave are posted at the beginning of each school year for twelve (12) month Teachers (Art. 17.1.3); Thirteen and one half (13.5) days for eleven (11) month teachers (Art. 17.1.4)",
        "49", "high", ""
    ),
    "leave_sick_accrual_002": (
        "yes; unused sick leave carries forward year to year; no maximum accumulation cap stated in CBA",
        "Unused sick leave shall be carried forward from year to year. (Art. 17.1.1); All unused and unreturned sick leave shall be carried forward from year to year. (Art. 17.1.11.4)",
        "49-50", "high", "Sick leave buy-back option available for perfect attendance (Art. 17.1.11)"
    ),
    "leave_sick_family_003": (
        "yes",
        "Four (4) sick leave days may be used for general leave. (Art. 17.1.1); A Teacher who is granted an extended leave of absence for maternity/paternity purposes may elect to use her accrued sick leave at the time she begins the extended leave of absence from duty. (Art. 17.5.2); FMLA rights referenced at Art. 17.7",
        "49 (17.1.1); 53 (17.5.2)", "medium", "Family care leave listed as qualifying reason for extended leave (Art. 17.5.1.2)"
    ),
    "leave_personal_days_004": (
        "discussed_unclear",
        "Four (4) sick leave days may be used for general leave. General leave shall not be cumulative. (Art. 17.1.1) — no separate personal leave category; 4 general leave days drawn from the 12-day sick leave bank",
        "49", "medium", "General leave is carved from sick leave, not a separate personal leave bank"
    ),
    "leave_personal_restrictions_005": (
        "general leave shall not be cumulative; request must be given to supervisor at least one day prior to absence; no reason requirement stated",
        "General leave shall not be cumulative. (Art. 17.1.1); A request for the use of general or annual leave shall be given to the Supervisor or his/her designee at least one (1) day prior to the expected absence. (Art. 17.2.2)",
        "49 (17.1.1); 51 (17.2.2)", "medium", ""
    ),
    "leave_personal_conversion_006": (
        "no",
        "General leave shall not be cumulative. (Art. 17.1.1) — general leave unused at year-end does not convert; no conversion to sick leave or cash stated for general/personal leave",
        "49", "medium", "Sick leave itself has a buy-back option (Art. 17.1.11) but not general leave"
    ),
    "leave_bereavement_days_007": (
        "4",
        "Teachers shall be granted up to a total of four (4) days of leave (in addition to sick leave) during each school year without loss of pay or benefits for funeral or bereavement purposes. (Art. 17.3.1)",
        "51", "high", "Additional sick leave may be used if more days needed (Art. 17.3.2); unused bereavement leave expires at year end (Art. 17.3.3)"
    ),
    "leave_bereavement_relatives_008": (
        "not_discussed",
        "Art. 17.3.1 grants 4 bereavement days but does not define covered relatives or household members",
        "", "high", ""
    ),
    "leave_parental_paid_009": (
        "yes",
        "A Teacher 'Maternity/Paternity Leave Bank' shall be operated under guidelines approved by DCPS and the WTU. (Art. 17.1.12.3); Teachers shall not be required to exhaust all their accrued sick leave days and may instead retain up to ten sick leave days in their accrued sick leave balance, before being eligible to use the Maternity/Paternity Leave Bank (Art. 17.1.12.6)",
        "50", "medium", "Leave bank funded by donations from retiring teachers' excess leave; mechanics governed by separate guidelines not reproduced in CBA"
    ),
    "leave_pregnancy_disability_010": (
        "yes",
        "A Teacher who is granted an extended leave of absence for maternity/paternity purposes may elect to use her accrued sick leave at the time she begins the extended leave of absence from duty. (Art. 17.5.2); A Teacher shall be permitted to return from maternity/paternity, adoption, or educational leave upon a thirty (30) day written notice of intent to return to work prior to the end of a semester. (Art. 17.5.4)",
        "53", "high", ""
    ),
    "leave_adoption_childcare_011": (
        "yes",
        "Adoption leave listed as reason for extended leave of absence up to 2 years (Art. 17.5.1.5); A Teacher shall be permitted to return from maternity/paternity, adoption, or educational leave upon a thirty (30) day written notice (Art. 17.5.4)",
        "53", "high", ""
    ),
    "leave_fmla_012": (
        "yes",
        "Teachers shall receive benefits as provided in the Family and Medical Leave Act of 1993, as amended, and as provided in the District of Columbia Family and Medical Leave Act of 1990. (Art. 17.7)",
        "53", "high", "Reference-only; no additional CBA detail on eligibility, substitution, or benefit continuation beyond statutory rights"
    ),
    "leave_absence_reporting_013": (
        "yes",
        "If a Teacher cannot report for work due to illness, he/she shall notify the Supervisor or designee as soon as possible, but in no case later than the first fifteen (15) minutes of the Teachers' work day. (Art. 17.1.5); Teachers shall not be required to obtain their own substitutes. DCPS shall make every effort to provide substitute service for every absence of a Teacher, provided the Teacher notifies her/his Supervisor of the absence in accordance with the rules established in this Agreement. (Art. 23.16.1-23.16.2)",
        "49 (17.1.5); 75-76 (23.16)", "high", ""
    ),
    # ── workload ─────────────────────────────────────────────────────────────
    "workload_work_year_days_001": (
        "192 days (ET-15 10-month; up to 196 if extended for PD); 210 days (ET-15/11); 228 days (ET-15/12)",
        "The work year for 10-month ET-15 Teachers shall be one hundred ninety-two (192) days, of which not more than one hundred eighty-five (185) shall be Instructional Days. (Art. 23.1.1.1); The work year for eleven-month Teachers shall be two hundred ten (210) days. (Art. 23.1.2); The work year for twelve-month Teachers shall be 228 days. (Art. 23.1.3)",
        "64", "high", "9 non-instructional days minimum for PD per Art. 2.6.1"
    ),
    "workload_workday_length_002": (
        "7.5 hours (ET-15 and ET-15/12); 40 hours/week (EG-09); no earlier than 7:30 AM, no later than 4:30 PM, inclusive of duty-free lunch",
        "The work day for ET-15 and ET-15/12 Teachers shall be seven-and-one-half (7.5) consecutive hours beginning no earlier than 7:30 AM and ending no later than 4:30 PM, inclusive of a duty-free lunch period. (Art. 23.2.1); The workweek for EG-09 Teachers shall be forty (40) hours. (Art. 23.2.2)",
        "65", "high", "Teachers report 35 minutes before student day start (Art. 23.3.1)"
    ),
    "workload_prep_guarantee_003": (
        "yes",
        "All Teachers serving in elementary schools shall receive two hundred twenty-five (225) minutes per week for planning periods. (Art. 23.6.2.1.1); All secondary school teachers shall be given at least five (5) daily planning periods per week that are equal in length to a class period (Art. 23.6.5.1)",
        "66-68", "high", ""
    ),
    "workload_prep_minutes_004": (
        "225 minutes per week (elementary); 5 periods per week equal to class period length (secondary)",
        "All Teachers serving in elementary schools shall receive two hundred twenty-five (225) minutes per week for planning periods. (Art. 23.6.2.1.1); All secondary school teachers shall be given at least five (5) daily planning periods per week that are equal in length to a class period (Art. 23.6.5.1)",
        "66-68", "high", "Priority schedule for elementary: 45 min/day x5 preferred; secondary: period length varies by school schedule"
    ),
    "workload_prep_protected_005": (
        "yes",
        "Four of the Morning Blocks each week are reserved for Teacher-initiated planning. (Art. 23.8.5); If a Supervisor causes a Teacher to lose a Morning Block, the Teacher shall receive compensation for the additional workload using Administrative Premium. (Art. 23.8.6); Teachers compensated when planning period lost due to class coverage (Art. 23.17.5)",
        "70 (23.8); 76-77 (23.17)", "high", ""
    ),
    "workload_lunch_duty_free_006": (
        "yes",
        "In secondary schools, each Teacher shall have a duty-free lunch period equal in length to a full teaching period. A duty-free lunch period shall not include the supervision of students. (Art. 23.7.1.1); each Teacher shall have a minimum forty-five (45) minute, duty-free, uninterrupted lunch period each day [elementary] (Art. 23.7.2.1)",
        "68", "high", ""
    ),
    "workload_lunch_minutes_007": (
        "minimum 45 minutes; secondary: not less than 45 and not more than 60 minutes (equal to full teaching period); elementary: minimum 45 minutes per day",
        "in no case shall a Teacher's lunch period be less than 45 minutes or exceed 60 minutes (Art. 23.7.1.1); each Teacher shall have a minimum forty-five (45) minute, duty-free, uninterrupted lunch period each day (Art. 23.7.2.1)",
        "68", "high", ""
    ),
    "workload_meetings_limits_008": (
        "yes",
        "The Supervisor shall have the right to call one (1) required general faculty meeting per month. (Art. 23.11.2); No faculty meeting shall exceed one (1) hour in duration, nor extend beyond 4:30 PM (Art. 23.11.7)",
        "71-72", "high", "One additional meeting allowed in September and June (Art. 23.11.3); one extra per month allowed under specific conditions (Art. 23.11.4)"
    ),
    "workload_nonteaching_duties_009": (
        "yes",
        "Article 20 enumerates non-teaching duties teachers are NOT required to perform: bus duty (20.1.2), school-wide detention (20.1.3), lavatory duty (20.1.10), clerical duties on health records and roster cards (20.1.6-20.1.15), scoring citywide tests (20.1.12), money collection in secondary schools (20.1.13)",
        "60-61", "high", ""
    ),
    # ── class size ───────────────────────────────────────────────────────────
    "class_size_limits_001": (
        "yes",
        "Except as provided in Section 23.13.3, maximum class size shall not exceed the following: Pre-K Without Aide 15; Pre-K With Aide 20; K Through Grade 2 20; Grades 3 Through 12 25; Remedial Classes 12; Career and Technology Education 18 (Art. 23.13.1)",
        "73", "high", "Binding caps; special education class sizes separately defined (Art. 23.13.2)"
    ),
    "class_elementary_max_002": (
        "Pre-K without aide: 15; Pre-K with aide: 20; K through Grade 2: 20; Grades 3-5: 25; Remedial: 12",
        "Pre-Kindergarten Without an Aide 15; Pre-Kindergarten With an Aide 20; Kindergarten Through Grade 2 20; Grades 3 Through 12 25; Remedial Classes 12 (Art. 23.13.1 table)",
        "73", "high", "Grades 3-12 share a single cap of 25; special ed self-contained rooms have separate lower limits"
    ),
    "class_secondary_max_003": (
        "Grades 6-12: 25; Career and Technology Education: 18; Remedial: 12",
        "Grades 3 Through 12 25; Career and Technology Education 18; Remedial Classes 12 (Art. 23.13.1 table)",
        "73", "high", ""
    ),
    "class_overage_remedy_004": (
        "yes",
        "When an elementary Teacher is required to accept additional students in his/her class due to a Teacher's absence, and the additional number results in a class exceeding the contractual limit, the Teacher shall be paid at the Administrative Premium per day of coverage. (Art. 23.17.5.2.1); WTU/DCPS committee to recommend solutions when class size provisions cannot be met (Art. 23.13.2.3)",
        "73 (23.13.2.3); 76 (23.17.5.2.1)", "high", "Administrative Premium remedy for temporary overages; committee process for structural overages"
    ),
    # ── evaluation ───────────────────────────────────────────────────────────
    "evaluation_procedure_001": (
        "yes",
        "Per D.C. Code § 1-617.18...the evaluation process and instruments for evaluating District of Columbia Public Schools employees shall be a non-negotiable item for collective bargaining purposes. (Art. 15.1); DCPS makes commitments on process, documentation, and appeals (Art. 15.2-15.6)",
        "44", "high", "Evaluation process non-negotiable; CBA commits to consultation, documentation, and grievance rights on process (not judgment)"
    ),
    "evaluation_system_002": (
        "District of Columbia Schools Effectiveness Assessment System for School-Based Personnel (DCPS Teaching and Learning Framework)",
        "The evaluation process refers to the procedures set forth in the District of Columbia Schools Effectiveness Assessment System for School-Based Personnel. (Definitions, p. 2); DCPS Teaching and Learning Framework referenced throughout Arts. 2 and 15",
        "2 (Definitions); 44 (Art. 15)", "high", ""
    ),
    "evaluation_observation_count_003": (
        "discussed_unclear",
        "Teachers will be provided a copy of the documentation of all formal observations prior to the end of the school year. (Art. 15.2.2) — formal observations referenced but number not specified in CBA; count would be in the non-negotiable evaluation framework",
        "44", "medium", ""
    ),
    "evaluation_observation_duration_004": (
        "not_discussed",
        "Observation duration not mentioned in this CBA; evaluation process is non-negotiable",
        "", "high", ""
    ),
    "evaluation_ratings_005": (
        "Minimally Effective; Effective (and higher levels implied by 'Effective or higher' language)",
        "Teachers who receive an evaluation score of Minimally Effective shall be held on their current salary step. Such Teachers who earn an evaluation scored of Effective or higher shall be immediately moved to the next step. (Art. 36.6); Supports for Teachers Rated Minimally Effective (Art. 2.5 heading)",
        "94 (36.6); 14 (2.5)", "medium", "Full rating scale (likely includes Highly Effective) not enumerated in CBA; only Minimally Effective and Effective referenced"
    ),
    "evaluation_student_growth_006": (
        "yes",
        "the individual performance-based pay and/or bonus system shall be on a voluntary 'qualify-in' basis, with the qualifications including student growth for tested and non-tested grades and subjects (Art. 36.4); STUDENT ACHIEVEMENT defined to include test scores and other measures (Definitions, p. 4)",
        "4 (Definitions); 93-94 (Art. 36.3-36.4)", "medium", "Student growth tied to performance-pay system; whether it is part of the mandatory evaluation rubric is not stated"
    ),
    "evaluation_improvement_plan_007": (
        "discussed_unclear",
        "DCPS will consult with the WTU on the development of professional development opportunities that will be made available to teachers rated as Minimally Effective. (Art. 2.5.1) — professional development for low-rated teachers mentioned but no formal improvement plan with triggers, timeline, support steps, or consequences described",
        "14", "medium", ""
    ),
    "evaluation_consequences_008": (
        "yes",
        "Teachers who receive an evaluation score of Minimally Effective shall be held on their current salary step. (Art. 36.6.1); The standard for separation under the evaluation process shall be 'just cause,' which shall be defined as adherence to the evaluation process only. (Art. 15.4); Excessing rubric uses previous year's evaluation rating as Category 1 (50 points max) in determining order of excessing (Art. 4.5.2.5)",
        "94 (36.6); 44 (15.4); 23-24 (4.5.2.5)", "high", "Evaluation affects: step advancement (hold for Minimally Effective), separation (just cause standard), and excessing priority (rubric)"
    ),
    # ── security ─────────────────────────────────────────────────────────────
    "security_probation_001": (
        "yes",
        "The standard for disciplining permanent employees shall be just cause. The standard for disciplining probationary employees shall be not arbitrary or capricious, as opposed to at will. (Art. 7.3); references to permanent and probationary status throughout (Arts. 4, 17, 39)",
        "35", "high", ""
    ),
    "security_nonrenewal_002": (
        "not_discussed",
        "The CBA addresses discipline and discharge (Art. 7), separation via excessing (Art. 4), and evaluation-based separation (Art. 15), but does not include a separate article on contract nonrenewal notice, hearing, or appeal rights for probationary teachers",
        "", "medium", "Nonrenewal of probationary teachers likely governed by DC law (DCMR Title 5), not this CBA"
    ),
    "security_seniority_definition_003": (
        "yes",
        "SENIORITY. There are two forms of seniority: system-wide seniority and building seniority. System-wide seniority is based upon continual length of service as a Teacher in the District of Columbia Public School System. Periods of service divided by a break shall not be added together to determine system-wide seniority. Building seniority is based upon the length of uninterrupted service in a particular school or school administrative unit in a particular area of certification. (Definitions, p. 3)",
        "3-4", "high", "Definitions include tie-breaker rules and accrual specifics for special subject teachers"
    ),
    "security_voluntary_transfer_004": (
        "yes",
        "A voluntary transfer is a change in a building assignment from one work location to another when initiated by a teacher. (Art. 4.2.1); Lists of vacancies shall be prepared and posted on or before April 1 annually. (Art. 4.2.3); Teachers requesting a voluntary transfer may arrange to interview with school principals at a mutually agreeable time. (Art. 4.2.8); No Teacher shall be placed at a school without the Teacher's and the Supervisor's consent ('mutual consent') (Art. 4.4.1)",
        "21-22", "high", ""
    ),
    "security_involuntary_transfer_005": (
        "yes",
        "Involuntary transfers shall be made only after consultation and discussion with the Teacher involved. A Teacher who is involuntarily transferred shall be given two (2) weeks notice...The notice of the transfer shall contain the reasons therefore. (Art. 4.3.1); Involuntary transfers shall not be made for reasons of disciplinary action. (Art. 4.3.4)",
        "22", "high", ""
    ),
    "security_rif_006": (
        "yes",
        "ARTICLE 39 - REDUCTION-IN-FORCE, ABOLISHMENT AND FURLOUGH; Prior to the decision to implement a reduction in force and/or abolishment, DCPS shall discuss other possible options with the WTU. (Art. 39.3); DCPS intends not to use the reduction in force (RIF) or abolishment procedures in cases commonly known as 'Fall Equalization,' 'Spring Excessing' (Art. 39.1)",
        "100-101", "high", "DCPS prefers excessing (Art. 4.5) over formal RIF; RIF article establishes process when RIF does occur"
    ),
    "security_recall_007": (
        "yes",
        "All Teachers who are separated by DCPS according to the provisions of this article shall have the right to reapply to DCPS at any time. (Art. 39.8.1); DCPS will require principals to interview 2 appropriately qualified Teachers who lost their positions as a result of the reduction in force or abolishment before considering any other candidate to fill a vacancy for the remainder of the school year. (Art. 39.7)",
        "100-101", "medium", "Reapplication rights rather than a formal recall list; interview priority for remainder of school year only"
    ),
    "security_rif_criterion_008": (
        "discussed_unclear",
        "Article 39 addresses RIF procedures but does not specify a primary criterion for order of layoff. The excessing rubric (Art. 4.5.2.5) uses previous year's evaluation rating as Category 1 (50 points) with unique skills, contributions, and length of service also scored — but that rubric governs excessing, not formal RIF. No explicit RIF layoff-order criterion stated.",
        "100-101 (Art. 39); 23-24 (Art. 4.5.2.5)", "medium", ""
    ),
    # ── discipline ───────────────────────────────────────────────────────────
    "discipline_just_cause_001": (
        "yes",
        "The standard for disciplining permanent employees shall be just cause. (Art. 7.3); The standard for separation under the evaluation process shall be 'just cause,' which shall be defined as adherence to the evaluation process only. (Art. 15.4)",
        "35 (7.3); 44 (15.4)", "high", "Just cause standard applies to permanent employees; probationary employees: 'not arbitrary or capricious'"
    ),
    "discipline_dismissal_002": (
        "yes",
        "In the case of suspensions or disciplinary discharges, the official taking the action shall provide the employee with advance written notice of the charge[s]...no later than ten (10) school days prior to the effective date of the discipline. (Art. 7.8.1); Within five (5) school days of the receipt of the notice, the WTU and/or employee has the right to review all documents related to the charges, meet with representatives from the Office of the Chancellor...and to provide a written reply. (Art. 7.8.2)",
        "37", "high", ""
    ),
    # ── conduct ──────────────────────────────────────────────────────────────
    "conduct_outside_employment_001": (
        "no",
        "Personal behavior of a Teacher during non-duty hours is the Teacher's concern, but this shall not preclude DCPS from taking action against a Teacher in appropriate circumstances after notification to the WTU of such personal behavior. (Art. 28.1); Complaints concerning unpaid bills, bad checks, tax delinquencies, and court judgments not involving D.C. Government monies or accounts shall be forwarded to the employee concerned without comment. (Art. 28.2)",
        "89", "high", "Art. 28 does not restrict outside employment or tutoring; it affirmatively states that personal affairs during non-duty hours are the teacher's concern; no COI or tutoring restriction found anywhere in CBA"
    ),
    "conduct_ethics_002": (
        "not_discussed",
        "No code of ethics, standards of conduct, or professional responsibility article found in this CBA; document focuses on working conditions, compensation, and procedural rights",
        "", "medium", ""
    ),
    "conduct_drug_alcohol_003": (
        "not_discussed",
        "No drug-free workplace or substance abuse testing provisions found in this CBA; Art. 18.1.10 cites D.C. Code 22-3201 through 22-3217 (controlled substances) regarding student discipline, not employee testing",
        "", "medium", ""
    ),
    "conduct_mandatory_reporting_004": (
        "not_discussed",
        "No mandatory reporting of child abuse or educator misconduct provision found in this CBA; Art. 18 addresses student discipline and teacher assault protections, not mandatory reporting obligations",
        "", "medium", ""
    ),
    "conduct_social_media_005": (
        "not_discussed",
        "No social media regulation found in this CBA",
        "", "high", "Consistent with older-style CBA"
    ),
    "conduct_acceptable_use_006": (
        "not_discussed",
        "No acceptable use policy for technology, email, or network use found in this CBA",
        "", "high", ""
    ),
    # ── safety ───────────────────────────────────────────────────────────────
    "safety_health_committee_001": (
        "yes",
        "DCPS shall be responsible for furnishing and maintaining conditions of employment that are free of hazards that are causing, or are likely to cause accidents, injury or illness to employees. (Art. 16.12.2); Employees shall be guaranteed protection from any restraint, interference, coercion, discrimination or reprisal for filing a report of an unsafe or unhealthful condition. (Art. 16.12.3); unsafe conditions assessed by Supervisor in consultation with SCAC (Art. 16.12.1)",
        "47-48", "medium", "No formal named joint safety committee; SCAC serves consultative safety role; DCPS bears maintenance obligation"
    ),
    "safety_assault_protection_002": (
        "yes",
        "A reasonable loss of time, not to exceed ten (10) days, resulting from an assault on a Teacher shall not be deducted from the Teacher's unused sick leave, provided that the Teacher has filed...a written report of the assault with the appropriate police department. (Art. 18.2.2); DCPS shall provide the Teacher with administrative leave for court appearances related to such event. (Art. 18.2.3); Zero Tolerance policy for weapons/violence on school personnel (Art. 18.1.12)",
        "57", "high", ""
    ),
    "safety_student_discipline_003": (
        "yes",
        "The parties agree that Title 5, DCMR Chapter 25 is the policy which establishes the procedures for maintaining student discipline. (Art. 18.1.1); Each local school shall form a Student Behavior Management Committee (SBMC). (Art. 18.1.2); Teachers shall exercise the responsibility for the supervision and discipline of students. (Art. 18.1.5)",
        "55-58", "high", ""
    ),
    "safety_remove_student_004": (
        "yes",
        "If a student conducts himself/herself in such a manner that seriously impedes learning...or if the safety of himself/herself, other students, or the Teacher is seriously threatened, a Teacher shall be free to send or escort the student to the Supervisor's office. (Art. 18.1.6); the Teacher shall have the right to request that the student not return to his/her class prior to a parent conference if the student's behavior is so severe as to interfere with the Teacher's ability to provide instruction. (Art. 18.1.8)",
        "56-57", "high", ""
    ),
}

# ── question list (same order as codebook) ───────────────────────────────────
question_meta = [
    # qid, topic, question_text
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

# wide field order
meta_fields = list(metadata.keys())
q_fields = []
for qid, _, _ in question_meta:
    q_fields += [f"{qid}_answer", f"{qid}_evidence", f"{qid}_page", f"{qid}_confidence"]
wide_fields = meta_fields + q_fields

main_path = OUT_DIR / "dcps_manual_main.csv"
with main_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=wide_fields)
    w.writeheader()
    w.writerow(wide_row)
print(f"Wrote {main_path}  ({len(wide_fields)} columns)")

# ── build long log ────────────────────────────────────────────────────────────
log_fields = ["document_id","file_name","Question ID","topic category",
              "question","answer","evidence","page number","confidence","coder notes"]
log_rows = []
for qid, topic, question in question_meta:
    ans, ev, pg, cf, cn = coded[qid]
    log_rows.append({
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

log_path = OUT_DIR / "dcps_manual_log.csv"
with log_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=log_fields)
    w.writeheader()
    w.writerows(log_rows)
print(f"Wrote {log_path}  ({len(log_rows)} rows)")
