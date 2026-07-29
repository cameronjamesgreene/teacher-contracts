#!/usr/bin/env python3
"""Build Worker 02 LLM-coded outputs.

This worker-owned script parses the current extraction_elements.md codebook,
loads the assigned PDF text extractions, applies document-specific coding
judgment for high-value fields, and fills every remaining Question ID
conservatively from the document text.
"""

from __future__ import annotations

import csv
import re
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CODEBOOK = ROOT / "contract_coding" / "extraction_elements.md"
OUT_DIR = ROOT / "contract_coding" / "output" / "llm_parts"
MAIN_OUT = OUT_DIR / "worker_02_main.csv"
LOG_OUT = OUT_DIR / "worker_02_log.csv"


def norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def short(text: str, n: int = 360) -> str:
    text = norm_space(text)
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."


def parse_codebook() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in CODEBOOK.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols and cols[0] == "Question ID":
            header = cols
            continue
        if header and len(cols) >= 8 and re.match(r"^[a-z]+_", cols[0]):
            rows.append(dict(zip(header, cols[:8])))
    return rows


DOCS: list[dict[str, str]] = [
    {
        "key": "mc_flyer",
        "district_name": "Montgomery County Public Schools",
        "state": "MD",
        "file_name": "V2-Flyer-Contract-Settlement-Highlights_for-contract-vote.pdf",
        "text_path": "contract_coding/extracted_text/montgomery_county_public_schools__v2_flyer_contract_settlement_highlights_for_contract_vo__9ec68bcb.txt",
        "document_type": "settlement summary",
        "bargaining_unit": "teachers",
        "start_year": "2018",
        "end_year": "2020",
        "effective_dates": "School Years 2018-2020; selected changes effective 2017-07-01",
        "school_years_covered": "2018-2020",
        "union_name": "Montgomery County Education Association",
        "source_document_notes": "Short proposed settlement highlights document; not a complete contract or appendices.",
    },
    {
        "key": "mc_1114",
        "district_name": "Montgomery County Public Schools",
        "state": "MD",
        "file_name": "Montgomery_11-14.pdf",
        "text_path": "contract_coding/extracted_text/montgomery_county_public_schools__montgomery_11_14__76c77ce6.txt",
        "document_type": "collective bargaining agreement",
        "bargaining_unit": "teachers",
        "start_year": "2011",
        "end_year": "2014",
        "effective_dates": "School Years 2011-2014",
        "school_years_covered": "2011-2014",
        "union_name": "Montgomery County Education Association",
        "source_document_notes": "Full MCEA/BOE contract text appears usable.",
    },
    {
        "key": "pg_0607",
        "district_name": "Prince Georges County Public Schools",
        "state": "MD",
        "file_name": "14-05.pdf",
        "text_path": "contract_coding/extracted_text/prince_georges_county_public_schools__14_05__2801e0eb.txt",
        "document_type": "collective bargaining agreement",
        "bargaining_unit": "teachers",
        "start_year": "2006",
        "end_year": "2007",
        "effective_dates": "July 1, 2006 to June 30, 2007",
        "school_years_covered": "2006-2007",
        "union_name": "Prince George's County Educators' Association",
        "source_document_notes": "Full negotiated agreement; OCR text is usable with some table artifacts.",
    },
    {
        "key": "pg_0709",
        "district_name": "Prince Georges County Public Schools",
        "state": "MD",
        "file_name": "14.pdf",
        "text_path": "contract_coding/extracted_text/prince_georges_county_public_schools__14__a9997057.txt",
        "document_type": "collective bargaining agreement",
        "bargaining_unit": "teachers",
        "start_year": "2007",
        "end_year": "2009",
        "effective_dates": "July 1, 2007 to June 30, 2009",
        "school_years_covered": "2007-2009",
        "union_name": "Prince George's County Educators' Association",
        "source_document_notes": "Full negotiated agreement; OCR text is usable with some table artifacts.",
    },
    {
        "key": "ns_1213",
        "district_name": "Northside Independent School District",
        "state": "TX",
        "file_name": "Employee_HAndbook2012-2013.pdf",
        "text_path": "contract_coding/extracted_text/northside_independent_school_district__employee_handbook2012_2013__8b5feb26.txt",
        "document_type": "employee handbook",
        "bargaining_unit": "all employees",
        "start_year": "2012",
        "end_year": "2013",
        "effective_dates": "2012-2013 employee handbook",
        "school_years_covered": "2012-2013",
        "union_name": "not_discussed",
        "source_document_notes": "Employee handbook, not a negotiated teacher CBA; some pay and benefits details point to separate schedules/booklets.",
    },
    {
        "key": "ns_1314",
        "district_name": "Northside Independent School District",
        "state": "TX",
        "file_name": "Model_employee_handbook_2013-2014_(2)_(1).pdf",
        "text_path": "contract_coding/extracted_text/northside_independent_school_district__model_employee_handbook_2013_2014_2_1__82d5bce5.txt",
        "document_type": "employee handbook",
        "bargaining_unit": "all employees",
        "start_year": "2013",
        "end_year": "2014",
        "effective_dates": "2013-2014 employee handbook; revised March 18, 2013",
        "school_years_covered": "2013-2014",
        "union_name": "not_discussed",
        "source_document_notes": "Employee handbook, not a negotiated teacher CBA; some pay and benefits details point to separate schedules/booklets.",
    },
    {
        "key": "wa_0708",
        "district_name": "West Ada School District",
        "state": "ID",
        "file_name": "84.pdf",
        "text_path": "contract_coding/extracted_text/west_ada_school_district__84__0f9422a5.txt",
        "document_type": "collective bargaining agreement",
        "bargaining_unit": "certified staff",
        "start_year": "2007",
        "end_year": "2008",
        "effective_dates": "2007-2008 school year",
        "school_years_covered": "2007-2008",
        "union_name": "Meridian Education Association",
        "source_document_notes": "Meridian Education Association master contract; text extraction is usable.",
    },
    {
        "key": "wa_2223",
        "district_name": "West Ada School District",
        "state": "ID",
        "file_name": "Wes_Ada_Agreement_2022-2023.pdf",
        "text_path": "contract_coding/extracted_text/west_ada_school_district__wes_ada_agreement_2022_2023__08e8a4c6.txt",
        "document_type": "collective bargaining agreement",
        "bargaining_unit": "unclear",
        "start_year": "2022",
        "end_year": "2023",
        "effective_dates": "2022-2023 school year inferred from document file/title; body text not extractable",
        "school_years_covered": "2022-2023",
        "union_name": "Meridian Education Association",
        "source_document_notes": "Scanned/image-only PDF from SHARP MX-M7570; pdftotext returned only page breaks, so OCR/visual review is required.",
    },
    {
        "key": "cin_ta",
        "district_name": "Cincinnati Public Schools",
        "state": "OH",
        "file_name": "Cincinnati__2017_TA_CPS__CFT.pdf",
        "text_path": "contract_coding/extracted_text/cincinnati_public_schools__cincinnati_2017_ta_cps_cft__4102bf98.txt",
        "document_type": "tentative agreement",
        "bargaining_unit": "teachers",
        "start_year": "2017",
        "end_year": "2020",
        "effective_dates": "July 1, 2017 - June 30, 2020",
        "school_years_covered": "2017-2020",
        "union_name": "Cincinnati Federation of Teachers",
        "source_document_notes": "Short CPS/CFT tentative agreement summary; not a full CBA.",
    },
    {
        "key": "cin_0709",
        "district_name": "Cincinnati Public Schools",
        "state": "OH",
        "file_name": "Cincinnati_0709.pdf",
        "text_path": "contract_coding/extracted_text/cincinnati_public_schools__cincinnati_0709__85ef3d54.txt",
        "document_type": "collective bargaining agreement",
        "bargaining_unit": "teachers",
        "start_year": "2007",
        "end_year": "2009",
        "effective_dates": "Effective January 1, 2007; expires December 31, 2009",
        "school_years_covered": "2007-2009",
        "union_name": "Cincinnati Federation of Teachers",
        "source_document_notes": "CFT/Board contract text is usable; referenced Appendix A salary table is not visible in extracted text.",
    },
]


def with_id(doc: dict[str, str]) -> dict[str, str]:
    stem = Path(doc["text_path"]).stem
    doc = dict(doc)
    doc["document_id"] = stem
    return doc


DOCS = [with_id(d) for d in DOCS]


STOP_SINGLE = {
    "teacher",
    "teachers",
    "employee",
    "employees",
    "unit",
    "school",
    "schools",
    "district",
    "board",
    "professional",
    "position",
    "positions",
    "program",
    "programs",
    "benefits",
    "leave",
    "salary",
    "work",
    "state",
    "federal",
    "other",
    "section",
    "appendix",
    "policy",
    "procedures",
}


PATTERNS: dict[str, list[str]] = {
    "pay_salary_schedule_001": [r"teacher'?s? salary schedule", r"\bsalary schedule\b", r"\bsalary scale\b"],
    "pay_salary_schedule_002": [r"salary schedule.*?(?:20\d{2}|19\d{2})", r"effective .* salary schedule"],
    "pay_step_increment_014": [r"\bstep increase\b", r"\bsalary increments?\b", r"annual advancements? in salary", r"vertical advancement"],
    "pay_lane_advancement_015": [r"lane change", r"salary lane", r"transcripts? of credits", r"credits.*salary schedule", r"move from Level"],
    "pay_prior_experience_016": [r"prior teaching experience", r"credit for previous employment", r"years? of experience.*salary"],
    "pay_new_hire_placement_017": [r"new hires?.*salary schedule", r"initial salary", r"initial placement", r"placement.*salary schedule"],
    "pay_performance_pay_018": [r"performance pay", r"merit pay", r"Teacher Advancement Program", r"\bTAP\b", r"Knowledge and Skills Based Pay"],
    "pay_cost_of_living_019": [r"\bCOLA\b", r"general wage increase", r"salary schedules shall be increased", r"across-the-board"],
    "pay_pay_frequency_020": [r"paid monthly", r"paychecks", r"pay day", r"pay plans", r"checks delivered"],
    "pay_extra_duty_schedule_021": [r"extra-duty pay schedule", r"supplemental salary schedule", r"extracurricular stipends", r"compensatory emoluments"],
    "pay_coaching_stipends_022": [r"\bcoach(?:es|ing)?\b", r"athletic", r"high school sports"],
    "pay_activity_stipends_023": [r"club sponsor", r"student council", r"yearbook", r"activity", r"extracurricular"],
    "pay_department_chair_024": [r"department chair", r"resource teacher", r"team leaders?"],
    "pay_summer_school_025": [r"summer school", r"summer employment", r"extended school year", r"intersession"],
    "pay_extra_period_026": [r"extra period", r"additional period", r"overload", r"additional assignment"],
    "pay_class_coverage_027": [r"class coverage", r"cover(?:ing)? classes", r"substitute.*unavailable"],
    "pay_homebound_tutoring_028": [r"home and hospital", r"homebound", r"tutor(?:ing)?"],
    "pay_pd_stipend_029": [r"professional development.*compensated", r"inservice.*paid", r"workshop payments?", r"paid separately"],
    "pay_recruitment_retention_030": [r"recruit(?:ment)? and retain", r"shortage", r"retention", r"hard[- ]to[- ]staff", r"high need"],
    "pay_national_board_031": [r"National Board", r"NBPTS", r"NBCT", r"National Teacher Board"],
    "pay_longevity_032": [r"longevity", r"career increment"],
    "pay_travel_mileage_033": [r"mileage", r"travel expense", r"IRS.*business expenses"],
    "pay_unused_leave_payout_034": [r"unused sick leave", r"sick leave conversion", r"unused leave", r"terminal pay"],
    "pay_retirement_incentive_035": [r"early retirement incentive", r"retirement incentive"],
    "pay_experience_credit_indistrict_037": [r"in-district experience", r"credit for previous employment"],
    "pay_experience_credit_outofdistrict_038": [r"another district", r"other districts?", r"prior teaching experience"],
    "pay_experience_credit_outofstate_039": [r"out-of-state", r"state accredited school", r"prior teaching experience"],
    "pay_experience_credit_military_public_040": [r"military service.*salary", r"allowance for military service"],
    "pay_hardtostaff_schools_041": [r"high need schools?", r"hard[- ]to[- ]staff school", r"priority school"],
    "pay_hardtostaff_sped_042": [r"special education.*(?:incentive|shortage|stipend)", r"shortage.*special education"],
    "pay_hardtostaff_stem_043": [r"mathematics, science", r"math(?:ematics)?.*science.*shortage", r"STEM"],
    "pay_hardtostaff_esl_044": [r"ESL", r"ELL", r"bilingual", r"ESOL"],
    "pay_performance_individual_046": [r"individual merit", r"evaluation-based pay", r"Teacher Advancement Program", r"\bTAP\b"],
    "pay_performance_schoolwide_047": [r"school-wide bonus", r"team-based", r"school performance"],
    "benefits_health_001": [r"health insurance", r"medical coverage", r"medical care", r"medical and prescription"],
    "benefits_health_contribution_002": [r"Board Contributions", r"district.*contribution", r"Board will purchase", r"premium shifts"],
    "benefits_health_employee_premium_003": [r"employee contribution", r"monthly employee contribution", r"premium"],
    "benefits_dependent_health_004": [r"dependent", r"spouse", r"family coverage", r"two person"],
    "benefits_health_plan_type_005": [r"\bHMO\b", r"\bPPO\b", r"Point of Service", r"TRS-ActiveCare"],
    "benefits_dental_006": [r"dental insurance", r"dental coverage", r"dental plans?"],
    "benefits_dental_contribution_007": [r"dental.*contribution", r"medical/dental chart", r"Board Contributions"],
    "benefits_vision_008": [r"vision", r"optical care", r"vision care"],
    "benefits_vision_contribution_009": [r"vision.*contribution", r"optical.*contribution"],
    "benefits_life_010": [r"life insurance", r"term life"],
    "benefits_life_amount_011": [r"\$[\d,]+\s+term life", r"term life insurance.*\$[\d,]+", r"\$30,000 term life"],
    "benefits_disability_012": [r"short[- ]term disability", r"long[- ]term disability", r"disability insurance"],
    "benefits_retirement_plan_013": [r"retirement system", r"\bTRS\b", r"\bSTRS\b", r"pension", r"IPERS|PERSI"],
    "benefits_retirement_contribution_014": [r"retirement contribution", r"STRS.*contribution", r"picked-up"],
    "benefits_supplemental_retirement_015": [r"tax sheltered annuity", r"403\(b\)", r"457", r"annuit"],
    "benefits_section125_016": [r"Section 125", r"cafeteria plan", r"flexible benefits"],
    "benefits_eap_wellness_017": [r"employee assistance", r"\bEAP\b", r"wellness"],
    "benefits_workers_comp_018": [r"workers'? compensation", r"work-related illness", r"job-related injury"],
    "benefits_eligibility_threshold_019": [r"eligible for health insurance", r"regularly scheduled to work", r"\.6\) time", r"one-half time"],
    "benefits_leave_continuation_020": [r"benefits.*leave", r"continue.*insurance.*leave", r"Continuation of Health Insurance"],
    "benefits_retiree_021": [r"retiree", r"retirement.*health", r"post-employment"],
    "leave_sick_days_001": [r"accrue sick leave", r"sick leave.*days", r"one day per month", r"one and one-fourth"],
    "leave_sick_accrual_002": [r"accumulated.*sick leave", r"cumulative", r"carry over", r"unused sick leave"],
    "leave_sick_family_003": [r"family illness", r"illness in the immediate family", r"family care", r"serious illness"],
    "leave_sick_bank_004": [r"sick leave bank", r"sick leave pool", r"family leave bank", r"donated leave"],
    "leave_medical_note_005": [r"physician", r"medical certification", r"doctor", r"medical explanation"],
    "leave_personal_days_006": [r"personal leave.*days", r"five days of paid personal", r"three personal leave days", r"two \(2\) days.*personal"],
    "leave_personal_restrictions_007": [r"personal leave.*notice", r"discretionary personal leave", r"restrictions.*personal leave"],
    "leave_personal_conversion_008": [r"unused personal leave.*sick", r"converted to sick leave"],
    "leave_bereavement_days_009": [r"bereavement leave", r"death in family", r"death of"],
    "leave_bereavement_relatives_010": [r"immediate family includes", r"bereavement.*parent", r"death in the immediate family"],
    "leave_parental_paid_011": [r"paid maternity", r"paid parental", r"birth of a child", r"bonding"],
    "leave_pregnancy_disability_012": [r"pregnancy", r"childbirth", r"temporary disability"],
    "leave_adoption_childcare_013": [r"adoption", r"child care", r"foster placement"],
    "leave_fmla_014": [r"Family and Medical Leave Act", r"\bFMLA\b", r"\bFML\b"],
    "leave_sabbatical_015": [r"sabbatical"],
    "leave_professional_016": [r"professional leave", r"conference", r"professional development"],
    "leave_jury_witness_017": [r"jury duty", r"witness", r"subpoena", r"appearance in court"],
    "leave_military_018": [r"military leave", r"military service"],
    "leave_public_office_019": [r"public office", r"political activity", r"religious holiday"],
    "leave_assault_injury_020": [r"assault leave", r"assault"],
    "leave_without_pay_021": [r"leave without pay", r"unpaid leave", r"non-compensated leave"],
    "leave_return_rights_022": [r"return from leave", r"reinstated", r"restored to"],
    "leave_absence_reporting_023": [r"report.*absence", r"notify.*absence", r"substitute", r"call-in"],
    "workload_work_year_days_001": [r"\bwork year\b", r"\bduty days\b", r"190 days", r"195 day", r"191 days"],
    "workload_calendar_breakdown_002": [r"school calendar", r"instructional days", r"planning days", r"professional development days"],
    "workload_workday_length_003": [r"length of workday", r"normal work day", r"workday.*minutes", r"seven hours", r"eight hours"],
    "workload_arrival_departure_004": [r"before school", r"after school", r"arrival", r"departure"],
    "workload_prep_guarantee_005": [r"planning periods", r"preparation time", r"duty-free daily preparation", r"prep"],
    "workload_prep_minutes_006": [r"\d+\s+minutes.*planning", r"planning.*\d+\s+minutes", r"\d+\s+minutes per week", r"one regular class period"],
    "workload_prep_protected_007": [r"uninterrupted planning", r"planning time.*meetings", r"shall not.*planning"],
    "workload_lunch_duty_free_008": [r"duty-free lunch"],
    "workload_lunch_minutes_009": [r"lunch.*\d+\s+minutes", r"thirty \(30\) minute.*lunch"],
    "workload_teaching_load_010": [r"teaching load", r"number of classes", r"assigned.*classes"],
    "workload_course_preps_011": [r"number of preparations", r"not be assigned more than three preparations"],
    "workload_elementary_specials_012": [r"elementary.*specialists", r"art, music, and physical education", r"elementary planning"],
    "workload_meetings_limits_013": [r"staff meetings.*per month", r"meetings.*no longer", r"after school.*meetings"],
    "workload_parent_conferences_014": [r"parent[- ]teacher conferences", r"conferences.*parents"],
    "workload_collaboration_time_015": [r"collaboration", r"PLC", r"team planning", r"group managed time"],
    "workload_nonteaching_duties_016": [r"non-teaching duties", r"lunch duty", r"bus duty", r"supervision"],
    "workload_class_coverage_017": [r"cover classes", r"serve as substitutes", r"substitute folders"],
    "workload_remote_emergency_018": [r"emergency closings", r"remote learning", r"teleworking", r"inclement weather"],
    "workload_job_share_019": [r"job-sharing", r"job sharing", r"part-time teaching"],
    "workload_summer_evening_assignment_020": [r"summer employment", r"evening high school", r"summer school"],
    "class_size_limits_001": [r"class size", r"class-size", r"pupil-teacher ratio", r"overload payments caps"],
    "class_elementary_max_002": [r"elementary class size", r"elementary.*class-size", r"grades? K"],
    "class_secondary_max_003": [r"secondary.*class size", r"high school.*class size", r"middle.*class size"],
    "class_overage_remedy_004": [r"overload pay", r"overload payments", r"class size.*remed"],
    "class_waivers_005": [r"waiver.*class size", r"exceptions.*class size"],
    "class_special_ed_caseload_006": [r"special education.*class size", r"caseload", r"service delivery"],
    "class_specialist_ratios_007": [r"counselor.*ratio", r"nurse.*ratio", r"librarian", r"psychologist", r"speech pathologist"],
    "class_student_teacher_ratio_008": [r"student-teacher ratio", r"pupil-teacher ratio"],
    "evaluation_procedure_001": [r"teacher evaluation", r"performance evaluation", r"evaluation and rating"],
    "evaluation_system_002": [r"Teacher Evaluation System", r"\bTES\b", r"evaluation model", r"Ohio Teacher Evaluation"],
    "evaluation_observation_count_003": [r"formal observations?", r"classroom visits?", r"observation"],
    "evaluation_observation_duration_004": [r"observation.*minutes", r"duration"],
    "evaluation_conferences_005": [r"post observation conference", r"pre-observation", r"performance conference"],
    "evaluation_ratings_006": [r"rating", r"performance levels", r"satisfactory"],
    "evaluation_student_growth_007": [r"student growth", r"test scores", r"value-added", r"SGM"],
    "evaluation_improvement_plan_008": [r"improvement plan", r"growth plan", r"intervention process", r"remediation"],
    "evaluation_peer_assistance_009": [r"peer assistance", r"peer review", r"consulting teacher", r"PAR"],
    "evaluation_appeal_010": [r"appeal.*evaluation", r"challenge.*evaluation", r"rebuttal"],
    "evaluation_personnel_file_access_011": [r"personnel file", r"access to personnel"],
    "evaluation_negative_material_012": [r"negative material", r"respond.*personnel file", r"material placed in a file"],
    "evaluation_consequences_013": [r"evaluation.*tenure", r"evaluation.*salary", r"denied an increment", r"intervention process"],
    "security_probation_001": [r"probationary", r"provisional", r"temporary contract", r"continuing contract", r"tenure"],
    "security_probation_length_002": [r"probationary.*years", r"provisional.*period", r"three years"],
    "security_tenure_rules_003": [r"tenure", r"continuing contract", r"permanent"],
    "security_nonrenewal_004": [r"non-renewal", r"nonrenewal"],
    "security_certification_005": [r"certification", r"licensure", r"endorsement", r"certificate"],
    "security_seniority_definition_006": [r"seniority.*defined", r"seniority shall", r"length of service"],
    "security_vacancy_posting_007": [r"vacancies", r"job vacancy", r"announcement of vacancies", r"posted"],
    "security_voluntary_transfer_008": [r"voluntary transfer"],
    "security_involuntary_transfer_009": [r"involuntary transfer", r"reassignment"],
    "security_excessing_010": [r"surplus", r"excess", r"unit adjustment", r"displacement"],
    "security_promotion_011": [r"promotion", r"teacher leadership", r"department chair", r"lead teacher"],
    "security_rif_012": [r"reduction in force", r"\bRIF\b", r"reduction in staff", r"layoff"],
    "security_recall_013": [r"recall", r"reemployment", r"priority consideration"],
    "security_rif_criterion_016": [r"reduction in force.*seniority", r"length of service", r"quality of performance", r"criteria"],
    "security_resignation_014": [r"resignation", r"early resignation"],
    "security_background_check_015": [r"background check", r"criminal history", r"fingerprint", r"arrests and convictions"],
    "discipline_just_cause_001": [r"just cause", r"proper cause", r"cause for"],
    "discipline_progressive_002": [r"progressive discipline", r"corrective action", r"written warning"],
    "discipline_representation_003": [r"representation.*disciplin", r"representative.*investigation", r"Weingarten"],
    "discipline_suspension_004": [r"suspension", r"suspended"],
    "discipline_dismissal_005": [r"dismissal", r"termination", r"discharge"],
    "discipline_complaints_006": [r"complaints", r"concerns against", r"grievances"],
    "discipline_investigation_007": [r"investigation", r"administrative leave"],
    "grievance_procedure_001": [r"grievance procedure", r"complaints and grievances", r"employee complaints"],
    "grievance_steps_002": [r"Step 1", r"Level One", r"Level I", r"steps? of the grievance"],
    "grievance_timelines_003": [r"within \d+ days", r"working days", r"calendar days"],
    "grievance_scope_004": [r"grievance.*means", r"grievable", r"not subject to grievance"],
    "grievance_arbitration_005": [r"arbitration", r"arbitrator"],
    "grievance_arbitration_binding_006": [r"binding arbitration", r"final and binding", r"advisory"],
    "grievance_mediation_007": [r"mediation", r"informal resolution", r"alternate grievance panel"],
    "conduct_academic_freedom_001": [r"academic freedom"],
    "conduct_curriculum_autonomy_002": [r"curriculum", r"instructional materials", r"lesson content", r"methods"],
    "conduct_lesson_plans_003": [r"lesson plans"],
    "conduct_grading_004": [r"grading", r"grade changes", r"student progress"],
    "conduct_nondiscrimination_005": [r"nondiscrimination", r"fair practices", r"equal employment"],
    "conduct_outside_employment_006": [r"outside employment", r"tutoring", r"conflict of interest"],
    "conduct_dress_code_007": [r"dress code", r"professional appearance"],
    "conduct_ethics_008": [r"code of ethics", r"standards of conduct", r"professional responsibility"],
    "conduct_drug_alcohol_009": [r"drug-free", r"drug abuse", r"alcohol", r"substance"],
    "conduct_searches_010": [r"searches", r"search.*property", r"district devices"],
    "conduct_confidentiality_011": [r"confidentiality", r"student records", r"personnel information"],
    "conduct_mandatory_reporting_012": [r"reporting suspected child abuse", r"mandatory reporting", r"educator misconduct"],
    "conduct_harassment_reporting_013": [r"harassment", r"retaliation", r"bullying"],
    "conduct_social_media_014": [r"social media", r"electronic media"],
    "conduct_electronic_student_contact_015": [r"electronic media with students", r"electronic communications with students"],
    "conduct_acceptable_use_016": [r"technology resources", r"computer use", r"acceptable use", r"internet"],
    "conduct_cell_phone_017": [r"cell phone", r"personal devices"],
    "conduct_political_activity_018": [r"political activity", r"public office"],
    "conduct_non_duty_hours_019": [r"personal life", r"non-duty hours"],
    "conduct_arrest_reporting_020": [r"arrests and convictions", r"report arrests", r"criminal charges"],
    "safety_health_committee_001": [r"health and safety", r"safety committee", r"hazardous conditions"],
    "safety_assault_protection_002": [r"assault", r"teacher assault"],
    "safety_property_damage_003": [r"damage to personal property", r"personal property", r"theft"],
    "safety_injury_reporting_004": [r"injury report", r"workplace injury", r"workers'? compensation"],
    "safety_student_discipline_005": [r"student discipline", r"behavior management", r"control and discipline"],
    "safety_remove_student_006": [r"remove.*student", r"exclude.*student"],
    "safety_restraint_seclusion_007": [r"restraint", r"seclusion", r"time-out"],
    "safety_emergency_closure_008": [r"emergency closing", r"inclement weather", r"lockdown", r"snow day"],
    "safety_environment_009": [r"physical environments", r"temperature", r"ventilation", r"air quality", r"hazardous conditions"],
    "safety_security_measures_010": [r"security", r"building access", r"visitors"],
    "safety_weapons_011": [r"weapons"],
    "resources_supplies_001": [r"instructional materials", r"supplies", r"textbooks"],
    "resources_supply_allowance_002": [r"supply allowance", r"professional account", r"personal funds", r"instructional supplies"],
    "resources_technology_device_003": [r"computers", r"laptops", r"technology resources", r"email"],
    "resources_phone_voicemail_004": [r"telephone", r"voicemail", r"communication tools"],
    "resources_workspace_005": [r"faculty space", r"teacher facilities", r"work areas", r"desks"],
    "resources_lounge_workroom_006": [r"lounge", r"workrooms"],
    "resources_restrooms_007": [r"restrooms"],
    "resources_parking_008": [r"parking"],
    "resources_parking_cost_009": [r"parking.*\$|\$.*parking", r"parking reimbursement"],
    "resources_clerical_support_010": [r"clerical", r"aide", r"instructor assistant", r"paraprofessional"],
    "resources_copy_print_011": [r"copier", r"printing", r"duplicating"],
    "resources_field_trip_012": [r"field trip", r"transporting students", r"student travel"],
    "pd_required_days_001": [r"professional development days", r"inservice", r"staff development", r"required trainings"],
    "pd_scheduling_pay_002": [r"professional development.*paid", r"paid separately", r"outside of the school day", r"compensated"],
    "pd_tuition_reimbursement_003": [r"tuition reimbursement", r"course reimbursement"],
    "pd_tuition_amount_004": [r"tuition reimbursement.*\$|\$.*tuition", r"\$\d[\d,]*.*tuition"],
    "pd_relicensure_support_005": [r"renewal of certificate", r"relicensure", r"certification", r"continuing education"],
    "pd_new_teacher_mentoring_006": [r"mentor teacher", r"new teacher", r"orientation", r"induction"],
    "pd_teacher_leadership_007": [r"teacher leadership", r"Instructional Leadership Team", r"\bILT\b", r"lead teacher"],
    "pd_career_ladder_008": [r"career ladder", r"Career in Teaching", r"career lattice", r"Teacher Advancement Program"],
    "pd_national_board_support_009": [r"National Board", r"NBPTS", r"NBCT"],
    "pd_professional_growth_plan_010": [r"professional growth", r"growth plan", r"professional development plan"],
    "union_recognition_001": [r"exclusive bargaining representative", r"recognition", r"sole and exclusive bargaining agent"],
    "union_dues_deduction_002": [r"dues deduction", r"payroll deduction.*dues", r"fair share", r"agency shop"],
    "union_release_time_003": [r"release time", r"Association.*leave", r"Federation conventions"],
    "union_president_leave_004": [r"president of the Association", r"PGCEA'?s President", r"Federation president"],
    "union_access_005": [r"access to schools", r"representatives.*schools", r"Association access"],
    "union_bulletin_mail_006": [r"bulletin board", r"mailboxes", r"email system", r"interschool mail"],
    "union_labor_management_007": [r"labor management", r"joint committee", r"consultation committee", r"Benefits Committee"],
    "union_site_decision_008": [r"shared decision", r"Faculty Advisory Council", r"Instructional Leadership Team", r"\bILT\b"],
    "union_no_strike_009": [r"no strike", r"withholding of services", r"work stoppage"],
    "union_management_rights_010": [r"management rights", r"Board Authority", r"School Board Authority"],
    "union_contract_waiver_011": [r"waiver", r"temporary contract alteration", r"site-adapt"],
}


def keyword_patterns(row: dict[str, str]) -> list[str]:
    pats = PATTERNS.get(row["Question ID"], [])[:]
    raw = row.get("Suggested keywords or sections to search", "")
    pieces = []
    for item in re.split(r",|;", raw):
        item = norm_space(item)
        if not item:
            continue
        # Keep meaningful phrases; filter very broad single words.
        if " " not in item and item.lower() in STOP_SINGLE:
            continue
        if len(item) < 4:
            continue
        pieces.append(item)
    for item in pieces[:8]:
        esc = re.escape(item).replace(r"\ ", r"\s+")
        if " " in item:
            pats.append(esc)
        else:
            pats.append(r"\b" + esc + r"\b")
    return list(OrderedDict.fromkeys(pats))


def load_pages(doc: dict[str, str]) -> list[str]:
    path = ROOT / doc["text_path"]
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    return text.split("\f") if text else [""]


def find_snippet(pages: list[str], patterns: list[str]) -> tuple[str, str]:
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for i, page in enumerate(pages, 1):
            match = rx.search(page)
            if match:
                start = max(0, match.start() - 260)
                end = min(len(page), match.end() + 520)
                return short(page[start:end]), str(i)
    return "", ""


def extract_value(answer_type: str, snippet: str) -> str | None:
    if not snippet:
        return None
    if "dollar" in answer_type:
        m = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", snippet)
        if m:
            return m.group(1).replace(",", "")
    if "percentage" in answer_type or "percent" in answer_type:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)", snippet, re.I)
        if m:
            return m.group(1)
    if "numeric" in answer_type:
        m = re.search(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*\(([0-9]+)\)|\b([0-9]+(?:\.[0-9]+)?)\b", snippet, re.I)
        if m:
            return (m.group(1) or m.group(2)).replace(",", "")
    if "date" in answer_type:
        m = re.search(r"(?:July|August|September|October|November|December|January|February|March|April|May|June)\s+\d{1,2},\s+\d{4}|\b\d{4}\s*[-–]\s*\d{4}\b|\b20\d{2}\b|\b19\d{2}\b", snippet)
        if m:
            return norm_space(m.group(0)).replace(" – ", "-").replace("–", "-")
    if "categorical" in answer_type:
        s = snippet.lower()
        for val in ["employee handbook", "tentative agreement", "settlement summary", "collective bargaining agreement", "policy manual", "monthly", "biweekly", "semimonthly", "binding", "advisory"]:
            if val in s:
                return val
    if "short text" in answer_type or "extracted quote" in answer_type:
        return short(snippet, 220)
    return None


def code_from_text(row: dict[str, str], pages: list[str], ocr_bad: bool) -> dict[str, str]:
    if ocr_bad:
        return {
            "answer": "discussed_unclear",
            "evidence": "PDF text extraction yielded only page breaks; OCR/visual review required before coding this field.",
            "page": "document",
            "confidence": "low",
            "coder notes": "Image-only/scanned PDF.",
        }
    pats = keyword_patterns(row)
    snippet, page = find_snippet(pages, pats)
    atype = row["Answer type"].lower()
    if not snippet:
        return {"answer": "not_discussed", "evidence": "", "page": "", "confidence": "high", "coder notes": ""}
    if atype == "yes/no":
        return {"answer": "yes", "evidence": snippet, "page": page, "confidence": "medium", "coder notes": "Coded from document text match; verify for publication use."}
    val = extract_value(atype, snippet)
    if val:
        return {"answer": val, "evidence": snippet, "page": page, "confidence": "medium", "coder notes": "Value/text extracted from nearby source text; verify tables before publication use."}
    return {"answer": "discussed_unclear", "evidence": snippet, "page": page, "confidence": "medium", "coder notes": "Topic discussed, but the exact requested value was not clear from extracted text."}


def law_coding(doc: dict[str, str], pages: list[str]) -> dict[str, dict[str, str]]:
    text = "\n".join(pages)
    state_terms = [
        r"Ohio Revised Code",
        r"\bORC\b",
        r"Section 3319\.\d+",
        r"Texas Education Code",
        r"Texas Labor Code",
        r"State Board for Educator Certification",
        r"Idaho Code",
        r"public school laws of Maryland",
        r"Maryland",
    ]
    federal_terms = [
        r"Family and Medical Leave Act",
        r"\bFMLA\b",
        r"\bFML\b",
        r"\bCOBRA\b",
        r"No Child Left Behind",
        r"\bNCLB\b",
        r"\bESSA\b",
        r"Internal Revenue Code",
        r"Section 125",
        r"Public Law",
        r"federal wage and hour laws",
    ]
    out: dict[str, dict[str, str]] = {}
    for prefix, terms, yes_q, list_q in [
        ("state", state_terms, "meta_cites_state_law_006", "meta_state_law_citations_007"),
        ("federal", federal_terms, "meta_cites_federal_law_008", "meta_federal_law_citations_009"),
    ]:
        snippet, page = find_snippet(pages, terms)
        if snippet:
            found = []
            for term in terms:
                if re.search(term, text, re.I):
                    found.append(re.sub(r"\\b|\\", "", term).replace(".*", " "))
            out[yes_q] = {"answer": "yes", "evidence": snippet, "page": page, "confidence": "medium", "coder notes": f"{prefix} law citation/name found in document text."}
            out[list_q] = {"answer": short("; ".join(OrderedDict.fromkeys(found)), 240), "evidence": snippet, "page": page, "confidence": "medium", "coder notes": f"List is extracted from recognized {prefix} law names/citations in text."}
        else:
            out[yes_q] = {"answer": "not_discussed", "evidence": "", "page": "", "confidence": "high", "coder notes": ""}
            out[list_q] = {"answer": "not_discussed", "evidence": "", "page": "", "confidence": "high", "coder notes": ""}
    return out


def ans(answer: str, evidence: str, page: str, confidence: str = "high", notes: str = "") -> dict[str, str]:
    return {"answer": str(answer), "evidence": short(evidence), "page": str(page), "confidence": confidence, "coder notes": notes}


OVERRIDES: dict[str, dict[str, dict[str, str]]] = {
    "mc_flyer": {
        "meta_doc_type_001": ans("settlement summary", "Title states Proposed Settlement Agreement; text says proposed settlement agreement for School Years 2018-2020.", "1"),
        "meta_effective_dates_002": ans("School Years 2018-2020; wage and step items effective 2017-07-01", "Proposed settlement agreement ... for the School Years 2018-2020; 1% General Wage Increase, effective July 1, 2017.", "1"),
        "meta_bargaining_unit_003": ans("teachers/unit members represented by MCEA", "The MCEA bargaining team announces a proposed settlement agreement; highlights refer to unit members and teachers.", "1-2"),
        "meta_document_scope_004": ans("summary-only/proposed", "To become final, the proposed agreement requires approval by MCEA membership and the Board of Education.", "1"),
        "meta_text_usability_005": ans("usable", "Text extraction produced readable settlement highlights.", "document"),
        "pay_step_increment_014": ans("yes", "Step increase for all eligible employees, effective July 1, 2017.", "1"),
        "pay_cost_of_living_019": ans("1", "1% General Wage Increase, effective July 1, 2017.", "1"),
        "pay_pd_stipend_029": ans("required trainings compensated at applicable hourly rates", "Subs will be compensated for required trainings at short-term hourly rate; HHTs will be compensated for required trainings at regular hourly rate.", "2"),
        "pay_recruitment_retention_030": ans("yes", "Parties will examine how to recruit and retain highly qualified teachers at high need schools; Board commits $1.7 million for piloting recommendations.", "1"),
        "pay_hardtostaff_schools_041": ans("yes", "Board commits $1.7 million for piloting recommendations for high need schools.", "1"),
        "leave_sick_family_003": ans("yes", "Creation of a contributory family leave bank to provide paid time off for care of family members with serious illnesses.", "1"),
        "leave_sick_bank_004": ans("yes", "Creation of a contributory family leave bank ... with MCPS seeding the first 200 days.", "1"),
        "leave_parental_paid_011": ans("yes", "The Board agrees to provide 2 days of paid leave to the mother for the birth of a child.", "1"),
        "leave_parental_paid_011": ans("yes", "The Board agrees to provide 2 days of paid leave to the mother for the birth of a child.", "1"),
        "workload_meetings_limits_013": ans("yes", "Maximum time for meetings after school reduced from 3 hours to 2.5 hours per month.", "2"),
        "workload_collaboration_time_015": ans("yes", "Group Managed Time: teams, departments, and committees can determine how, when, and where work will be accomplished.", "2"),
        "class_size_limits_001": ans("yes", "Section 500 - Same Class Size Caps; overload payments caps listed.", "1"),
        "safety_student_discipline_005": ans("yes", "Any change to a student's behavior management plan will be communicated to all impacted teachers.", "2"),
        "resources_supplies_001": ans("yes", "Unit members cannot be required to spend personal funds for classroom materials/supplies.", "2"),
        "resources_supply_allowance_002": ans("teachers not required to spend personal funds", "Unit members cannot be required to spend personal funds for classroom materials/supplies.", "2"),
        "pd_teacher_leadership_007": ans("yes", "School leadership teams roles should be rotated; Creation of a Joint Professional Learning Committee.", "2"),
        "union_labor_management_007": ans("yes", "MCEA and MCPS shall meet; creation of a Joint Professional Learning Committee.", "1-2"),
    },
    "mc_1114": {
        "meta_doc_type_001": ans("collective bargaining agreement", "Contract Agreement Between Montgomery County Education Association and Board of Education ... for School Years 2011-2014.", "1"),
        "meta_effective_dates_002": ans("School Years 2011-2014", "Title page states for the School Years 2011-2014.", "1"),
        "meta_bargaining_unit_003": ans("teachers/unit members represented by MCEA", "Article 1 Recognition and title identify Montgomery County Education Association and Board of Education.", "title/Article 1"),
        "meta_document_scope_004": ans("binding agreement", "Contract Agreement Between MCEA and Board of Education.", "1"),
        "meta_text_usability_005": ans("usable", "Full contract text and tables are extractable.", "document"),
        "pay_salary_schedule_001": ans("yes", "Article 19 lists the 10-Month Salary Schedule with BA, MA/MEQ, MA+30 and MA+60 lanes.", "52"),
        "pay_salary_schedule_002": ans("2010-2011; schedule effective July 1, 2008", "The salary schedule for 2010-2011 is: 10-Month Salary Schedule Effective July 1, 2008.", "52"),
        "pay_salary_steps_003": ans("19", "The 10-month schedule lists steps 1 through 19.", "52"),
        "pay_salary_lanes_004": ans("4", "Salary lanes shown are BA, MA/MEQ, MA+30, and MA+60.", "52"),
        "pay_lane_names_005": ans("BA; MA/MEQ; MA+30; MA+60", "Table headings: BA, MA/MEQ, MA+30, MA+60.", "52"),
        "pay_ba_start_006": ans("46410", "Step 1 BA is $46,410.", "52"),
        "pay_ma_start_007": ans("51128", "Step 1 MA/MEQ is $51,128.", "52"),
        "pay_phd_start_008": ans("not_discussed", "", "", "high"),
        "pay_ba_max_009": ans("62201", "BA lane has values through Step 10, with Step 10 at $62,201.", "52"),
        "pay_ma_max_010": ans("94832", "MA/MEQ lane reaches $94,832 at Step 19.", "52"),
        "pay_phd_max_011": ans("not_discussed", "", "", "high"),
        "pay_overall_max_012": ans("101354", "Highest listed value on the schedule is MA+60 Step 19 at $101,354.", "52"),
        "pay_ba_phd_gap_013": ans("not_discussed", "", "", "high"),
        "pay_department_chair_024": ans("yes", "Resource Teachers and Resource Counselors supplements range from $2,750 to $4,425 depending on department size.", "52"),
        "pay_national_board_031": ans("2000", "NBPTS certification increases regular scheduled salary by $2,000 annually.", "53"),
        "pay_longevity_032": ans("yes", "Unit members completing six or more years on Step 19 receive a 2.25 percent longevity increase.", "52"),
        "leave_sick_days_001": ans("1 day per month of assigned responsibility", "Each full-time unit member shall accrue sick leave at the rate of one day per month of assigned responsibility.", "76"),
        "leave_sick_accrual_002": ans("unlimited accumulation", "Unused sick leave is accumulated on an unlimited basis.", "76"),
        "leave_sick_family_003": ans("yes", "Leave may be granted for illness in the immediate family and charged against accumulated sick leave.", "76"),
        "leave_fmla_014": ans("yes", "Employees are provided up to 12 weeks in any 12-month period under the Family and Medical Leave Act.", "74"),
        "workload_workday_length_003": ans("7 hours plus duty-free lunch for normal school workday", "Normal workday at their school will be seven hours in addition to their duty-free lunch period.", "41"),
        "workload_lunch_duty_free_008": ans("yes", "Unit members' lunch period shall be no less than 30 minutes in length.", "41"),
        "workload_lunch_minutes_009": ans("30", "Unit members' lunch period shall be no less than 30 minutes in length.", "41"),
        "workload_prep_minutes_006": ans("3 hours 45 minutes weekly individually managed planning/work", "Requirement to provide a minimum of 3 hours and 45 minutes for individually managed planning and work.", "42"),
        "security_recall_013": ans("yes", "Terminated unit members receive priority consideration for re-employment for three years.", "73"),
    },
    "pg_0607": {
        "meta_doc_type_001": ans("collective bargaining agreement", "Negotiated Agreement between Prince George's County Educators' Association and the Board of Education of Prince George's County.", "1"),
        "meta_effective_dates_002": ans("2006-07-01 to 2007-06-30", "Title states July 1, 2006 to June 30, 2007.", "1"),
        "meta_bargaining_unit_003": ans("teachers/certificated personnel represented by PGCEA", "Article II Recognition identifies PGCEA as exclusive bargaining representative.", "3"),
        "meta_document_scope_004": ans("binding agreement", "Negotiated Agreement between PGCEA and the Board.", "1"),
        "meta_text_usability_005": ans("usable", "Full negotiated agreement text and salary tables are extractable, with minor OCR artifacts.", "document"),
        "pay_salary_schedule_001": ans("yes", "Teacher's Salary Schedule, Prince George's County Public Schools, Table A - Salary Schedule.", "33"),
        "pay_salary_schedule_002": ans("2006-07-01 to 2007-06-30", "Teacher's Salary Schedule ... July 1, 2006 - June 30, 2007.", "33"),
        "pay_salary_steps_003": ans("20", "Teacher salary schedule lists steps 01 through 20.", "33"),
        "pay_salary_lanes_004": ans("7", "Columns shown: Prov, BA, BA+30, BA+45 & MA, MA+30, MA+60, DR.", "33"),
        "pay_lane_names_005": ans("Prov; BA; BA+30; BA+45 & MA; MA+30; MA+60; DR", "Table headings list Prov, BA, BA+30, BA+45 & MA, MA+30, MA+60, DR.", "33"),
        "pay_ba_start_006": ans("41410", "Table A Step 01 BA is 41,410.", "33"),
        "pay_ma_start_007": ans("45393", "Table A Step 01 BA+45 & MA is 45,393.", "33"),
        "pay_phd_start_008": ans("50255", "Table A Step 01 DR is 50,255.", "33"),
        "pay_ba_max_009": ans("55379", "Table A BA reaches 55,379 at Step 20.", "33"),
        "pay_ma_max_010": ans("76606", "Table A BA+45 & MA reaches 76,606 at Step 20.", "33"),
        "pay_phd_max_011": ans("84813", "Table A DR reaches 84,813 at Step 20.", "33"),
        "pay_overall_max_012": ans("101775", "Table C DR Step 20 is 101,775.", "35"),
        "pay_ba_phd_gap_013": ans("8845", "Table A Step 01 DR 50,255 minus BA 41,410 equals 8,845.", "33"),
        "pay_extra_duty_schedule_021": ans("yes", "Compensatory Emoluments table lists competitive, product, service, and enrichment activity stipends.", "37"),
        "pay_coaching_stipends_022": ans("yes", "High School Sports stipend table lists football, basketball, track, baseball, softball, wrestling and other sports.", "37"),
        "pay_activity_stipends_023": ans("yes", "Compensatory Emoluments includes yearbook, newspaper, dramatics and music, science fair coordinator, and other activities.", "37"),
    },
    "pg_0709": {
        "meta_doc_type_001": ans("collective bargaining agreement", "Negotiated Agreement between Prince George's County Educators' Association and the Board of Education of Prince George's County.", "1"),
        "meta_effective_dates_002": ans("2007-07-01 to 2009-06-30", "Title states July 1, 2007 to June 30, 2009.", "1"),
        "meta_bargaining_unit_003": ans("teachers/certificated personnel represented by PGCEA", "Article II Recognition identifies PGCEA as exclusive bargaining representative.", "3"),
        "meta_document_scope_004": ans("binding agreement", "Negotiated Agreement between PGCEA and the Board.", "1"),
        "meta_text_usability_005": ans("usable", "Full negotiated agreement text and salary tables are extractable, with minor OCR artifacts.", "document"),
        "pay_salary_schedule_001": ans("yes", "Teacher's Salary Schedule, Prince George's County Public Schools, Table A - Salary Schedule.", "36"),
        "pay_salary_schedule_002": ans("2007-07-01 to 2008-06-30 first schedule; agreement covers 2007-2009", "Table A - Salary Schedule, July 1, 2007 - June 30, 2008.", "36"),
        "pay_salary_steps_003": ans("20", "Teacher salary schedule lists steps 1 through 20.", "36"),
        "pay_salary_lanes_004": ans("7", "Columns shown: Prov, BA, BA+30, BA+45 & MA, MA+30, MA+60, DR.", "36"),
        "pay_lane_names_005": ans("Prov; BA; BA+30; BA+45 & MA; MA+30; MA+60; DR", "Table headings list Prov, BA, BA+30, BA+45 & MA, MA+30, MA+60, DR.", "36"),
        "pay_ba_start_006": ans("43481", "Table A Step 1 BA is 43,481.", "36"),
        "pay_ma_start_007": ans("47663", "Table A Step 1 BA+45 & MA is 47,663.", "36"),
        "pay_phd_start_008": ans("52768", "Table A Step 1 DR is 52,768.", "36"),
        "pay_ba_max_009": ans("58148", "Table A BA reaches 58,148 at Step 20.", "36"),
        "pay_ma_max_010": ans("80436", "Table A BA+45 & MA reaches 80,436 at Step 20.", "36"),
        "pay_phd_max_011": ans("89054", "Table A DR reaches 89,054 at Step 20.", "36"),
        "pay_overall_max_012": ans("106864", "Table C DR Step 20 is 106,864.", "38"),
        "pay_ba_phd_gap_013": ans("9287", "Table A Step 1 DR 52,768 minus BA 43,481 equals 9,287.", "36"),
        "pay_extra_duty_schedule_021": ans("yes", "Compensatory Emoluments, July 1, 2007 - June 30, 2009, lists activity stipends.", "40"),
        "pay_coaching_stipends_022": ans("yes", "Compensatory Emoluments lists football, basketball, baseball/softball, wrestling, track, soccer and other sports.", "40"),
        "pay_activity_stipends_023": ans("yes", "Compensatory Emoluments lists yearbook, newspaper, student government, National Honor Society, and other activities.", "40"),
        "leave_parental_paid_011": ans("yes", "Employees with at least six months of service are eligible for up to ten paid days of maternity leave from the district.", "22"),
    },
    "ns_1213": {
        "meta_doc_type_001": ans("employee handbook", "Northside ISD Employee Handbook.", "title/TOC"),
        "meta_effective_dates_002": ans("2012-2013", "Employee Handbook 2012-2013.", "title"),
        "meta_bargaining_unit_003": ans("all employees; teacher-specific provisions included", "Handbook applies to employees and includes classroom teachers, librarians, nurses, and counselors.", "13"),
        "meta_document_scope_004": ans("employee handbook guidance", "Employee handbook describes district policies and employee procedures.", "document"),
        "meta_text_usability_005": ans("usable", "Handbook text is extractable and readable.", "document"),
        "pay_salary_schedule_001": ans("no", "Handbook says teachers are paid no less than the minimum state salary schedule but does not include the schedule; employees should contact Donna Lee for pay schedules.", "13"),
        "pay_pay_frequency_020": ans("monthly", "All professional and salaried employees are paid monthly.", "13"),
        "benefits_health_001": ans("yes", "Group health insurance coverage is provided through TRS-ActiveCare.", "15"),
        "benefits_health_contribution_002": ans("discussed_unclear", "The district's contribution to employee insurance premiums is determined annually by the board of trustees.", "15", "medium"),
        "benefits_eligibility_threshold_019": ans("active contributing TRS members or regularly scheduled at least 10 hours/week", "Eligible employees include active contributing TRS members and employees regularly scheduled to work at least 10 hours per week.", "15"),
        "leave_sick_days_001": ans("2 local sick leave days per year", "Personal and local sick leave is earned on a one day per semester basis.", "17", "medium"),
        "leave_personal_days_006": ans("5", "State law entitles all employees to five days of paid personal leave per year.", "17"),
        "leave_medical_note_005": ans("yes", "An employee absent more than 3 days because of personal or family illness must submit medical certification.", "17"),
        "leave_fmla_014": ans("yes", "Eligible employees can take up to 12 weeks of unpaid leave each year under family and medical leave.", "19"),
        "leave_pregnancy_disability_012": ans("yes", "Pregnancy and conditions related to pregnancy are treated the same as any other temporary disability.", "18"),
        "leave_return_rights_022": ans("yes", "Professional employees returning from leave will be reinstated to the school previously assigned as soon as an appropriate position is available.", "19"),
        "workload_prep_minutes_006": ans("450 minutes within each two-week period, blocks not less than 45 minutes", "Planning periods must provide at least 450 minutes within each two-week period in blocks not less than 45 minutes.", "10"),
        "workload_lunch_duty_free_008": ans("yes", "Teachers and librarians are entitled to a duty-free lunch period of at least 30 minutes.", "10"),
        "workload_lunch_minutes_009": ans("30", "Duty-free lunch period of at least 30 minutes.", "10"),
    },
    "ns_1314": {
        "meta_doc_type_001": ans("employee handbook", "Northside ISD Employee Handbook, revised March 18, 2013.", "title/TOC"),
        "meta_effective_dates_002": ans("2013-2014; revised 2013-03-18", "Northside ISD Employee Handbook, Revised March 18, 2013; 2013-2014 contents.", "1"),
        "meta_bargaining_unit_003": ans("all employees; teacher-specific provisions included", "Handbook applies to employees and includes classroom teachers, librarians, nurses, and counselors.", "17"),
        "meta_document_scope_004": ans("employee handbook guidance", "Employee handbook describes district policies and employee procedures.", "document"),
        "meta_text_usability_005": ans("usable", "Handbook text is extractable and readable.", "document"),
        "pay_salary_schedule_001": ans("no", "Classroom teachers will be paid no less than the minimum state salary schedule; employees should contact the superintendent for pay schedules.", "17"),
        "pay_pay_frequency_020": ans("monthly", "All professional and salaried employees are paid monthly; hourly employees are paid every two weeks.", "17"),
        "benefits_health_001": ans("yes", "Group health insurance coverage is provided through TRS-ActiveCare.", "20-21"),
        "benefits_health_contribution_002": ans("discussed_unclear", "The district's contribution to employee insurance premiums is determined annually by the board of trustees.", "21", "medium"),
        "benefits_eligibility_threshold_019": ans("active contributing TRS members or regularly scheduled at least 10 hours/week", "Eligible employees include active contributing TRS members and employees regularly scheduled to work at least 10 hours per week.", "21"),
        "leave_sick_days_001": ans("discussed_unclear", "State sick leave accumulated before 1995 is available; local leave is two paid local leave days per school year.", "24-25", "medium"),
        "leave_personal_days_006": ans("5", "State law entitles all employees to five days of paid personal leave per year.", "24"),
        "leave_sick_bank_004": ans("yes", "An employee may request the establishment of a sick leave pool for catastrophic illness or injury.", "25"),
        "leave_fmla_014": ans("yes", "The FMLA requires covered employers to provide up to 12 weeks of unpaid, job-protected leave.", "25"),
        "leave_assault_injury_020": ans("yes", "Assault leave provides extended job income and benefits protection to an employee injured by physical assault at work.", "29"),
        "leave_military_018": ans("yes", "Paid military leave is limited to 15 days each federal fiscal year.", "30"),
        "workload_prep_minutes_006": ans("450 minutes within each two-week period, blocks not less than 45 minutes", "Planning periods must provide at least 450 minutes within each two-week period in blocks not less than 45 minutes.", "14"),
        "workload_lunch_duty_free_008": ans("yes", "Teachers and librarians are entitled to a duty-free lunch period of at least 30 minutes.", "14"),
        "workload_lunch_minutes_009": ans("30", "Duty-free lunch period of at least 30 minutes.", "14"),
    },
    "wa_0708": {
        "meta_doc_type_001": ans("collective bargaining agreement", "Meridian Education Association Master Contract Between the Association and the Board of Trustees 2007-2008 School Year.", "1"),
        "meta_effective_dates_002": ans("2007-2008 school year", "Title page states 2007-2008 School Year.", "1"),
        "meta_bargaining_unit_003": ans("certified employees", "Salary and contract provisions refer to certified employees covered by this contract.", "8-9"),
        "meta_document_scope_004": ans("binding agreement", "Master Contract between the Association and the Board of Trustees.", "1"),
        "meta_text_usability_005": ans("usable", "Master contract text and tables are extractable.", "document"),
        "pay_salary_schedule_001": ans("yes", "2007-2008 Salary Schedule lists BA+0 through BA+72/MA+36 lanes.", "8"),
        "pay_salary_schedule_002": ans("2007-2008", "Heading states 2007-2008 Salary Schedule.", "8"),
        "pay_salary_steps_003": ans("14", "Salary schedule lists rows 0 through 13 across Levels 1-3.", "8", "medium"),
        "pay_salary_lanes_004": ans("7", "Columns are BA+0, BA+12, BA+24, BA+36/MA, BA+48/MA+12, BA+60/MA+24, BA+72/MA+36.", "8"),
        "pay_lane_names_005": ans("BA+0; BA+12; BA+24; BA+36/MA; BA+48/MA+12; BA+60/MA+24; BA+72/MA+36", "Column headings list BA+0 through BA+72/MA+36.", "8"),
        "pay_ba_start_006": ans("31000", "Level 1 row 0 BA+0 is 31,000.", "8"),
        "pay_ma_start_007": ans("31519", "Level 1 row 0 BA+36/MA is 31,519.", "8"),
        "pay_phd_start_008": ans("not_discussed", "", "", "high"),
        "pay_overall_max_012": ans("56940", "Highest base salary cell visible is BA+72/MA+36 Level 3 H at 56,940, excluding career enhancement add-ons.", "8"),
        "pay_extra_duty_schedule_021": ans("yes", "Supplemental Salary Schedule for High School Activities, 2007-2008.", "11"),
        "pay_coaching_stipends_022": ans("yes", "Supplemental schedule lists baseball, basketball, cross country, football, golf, soccer and other coaching stipends.", "11-14"),
        "pay_activity_stipends_023": ans("yes", "Supplemental schedule lists band, orchestra, choir, drama, debate, yearbook, student council, and other advisor stipends.", "13-15"),
        "pay_department_chair_024": ans("yes", "Department Chair maximum of 12 per school: $1,257.00.", "13"),
        "leave_personal_days_006": ans("2 or 4 depending contract category", "Personal leave is two days for Category 1, 2, or 3 employees and four days for renewable contracts.", "20"),
        "workload_workday_length_003": ans("7.5 hours elementary; 8 hours middle/high", "Normal work day hours are seven and one half hours at elementary and eight hours at middle and high school.", "23"),
        "workload_lunch_duty_free_008": ans("yes", "Full-time certified employees shall be provided a continuous thirty minute duty-free lunch period daily.", "24"),
        "workload_lunch_minutes_009": ans("30", "Continuous thirty (30) minute duty-free lunch period daily.", "24"),
        "workload_prep_minutes_006": ans("one regular class period secondary; 200 minutes per week elementary", "Secondary teachers receive one regular duty-free preparation period; elementary teachers receive 200 minutes per full workweek.", "23-24"),
    },
    "wa_2223": {
        "meta_doc_type_001": ans("collective bargaining agreement", "File/title indicates West Ada Agreement 2022-2023; body text is not extractable.", "document", "low", "Requires OCR/visual confirmation."),
        "meta_effective_dates_002": ans("2022-2023", "File/title indicates agreement for 2022-2023; body text is not extractable.", "document", "low", "Requires OCR/visual confirmation."),
        "meta_bargaining_unit_003": ans("unclear", "The PDF body text is image-only; bargaining unit cannot be confirmed from extractable text.", "document", "low"),
        "meta_document_scope_004": ans("collective bargaining agreement likely, but unclear from extractable body text", "File/title says Agreement 2022-2023; pdftotext produced no readable body text.", "document", "low"),
        "meta_text_usability_005": ans("scanned/OCR needed", "pdftotext returned only page breaks for the 26-page PDF.", "document", "high"),
    },
    "cin_ta": {
        "meta_doc_type_001": ans("tentative agreement", "Title states CPS / CFT Tentative Agreement.", "1"),
        "meta_effective_dates_002": ans("2017-07-01 to 2020-06-30", "Title states July 1, 2017 - June 30, 2020.", "1"),
        "meta_bargaining_unit_003": ans("teachers represented by Cincinnati Federation of Teachers", "Title identifies CPS / CFT Tentative Agreement.", "1"),
        "meta_document_scope_004": ans("tentative agreement summary", "Short numbered tentative agreement summary sections.", "1-2"),
        "meta_text_usability_005": ans("usable", "Tentative agreement text is extractable and readable.", "document"),
        "pay_salary_schedule_001": ans("discussed_unclear", "Tentative agreement refers to all salary schedules, re-indexing the salary schedule, and adding Step 30, but does not include schedule tables.", "1", "medium"),
        "pay_salary_steps_003": ans("30", "Add Step 30 to Salary Schedules.", "1"),
        "pay_lane_names_005": ans("Class VI - Master's plus 45 replacing PhD", "Class VI - (Master's plus 45 to replace PHD); all current PHDs remain in Class VI.", "1"),
        "pay_cost_of_living_019": ans("2", "COLA: July 1, 2017: 2%; July 1, 2018: 2%; January 1, 2020 reopener.", "1"),
        "pay_activity_stipends_023": ans("yes", "Schedule E increased budget for 2017/18: $200,000 to allow for additional activities.", "1"),
        "pay_department_chair_024": ans("yes", "Appendix D cleanup: Department Chair selection based on MOU language.", "2"),
        "pay_national_board_031": ans("yes", "Active NBCT Certification satisfies LT Evaluation requirement and Continuing Contract Evaluation requirements.", "2"),
        "pay_hardtostaff_esl_044": ans("yes", "Section 610 - Language for ELL Students and ESL Teachers; ESL Coordinators - $15.00 stipend per student.", "1"),
        "class_size_limits_001": ans("yes", "Section 500 - Same Class Size Caps; overload payments caps listed.", "1"),
        "evaluation_observation_count_003": ans("discussed_unclear", "Observation reports due electronically within 15 days; post-observation conference within 15 days of first formal observation.", "2", "medium"),
        "evaluation_conferences_005": ans("yes", "The post observation conference must be held within 15 days of the first formal observation of the year.", "2"),
        "security_voluntary_transfer_008": ans("yes", "Teacher Transfer Process; internal staff may participate with the Job Fair.", "2"),
        "leave_sick_accrual_002": ans("yes", "Aligned with ORC - Sick Leave credit from another district.", "2"),
        "conduct_grading_004": ans("yes", "Sections 220/400 Grading Practices: weekly electronic communication of student progress.", "2"),
        "union_dues_deduction_002": ans("yes", "Section 130 - Federation Rights - Cancellation of Dues Deduction Date.", "2"),
    },
    "cin_0709": {
        "meta_doc_type_001": ans("collective bargaining agreement", "Contract table of contents and signature page identify Cincinnati Federation of Teachers and Cincinnati Board of Education contract.", "1/85"),
        "meta_effective_dates_002": ans("2007-01-01 to 2009-12-31", "This contract shall expire on December 31, 2009; effective this 1st day of January 2007.", "85"),
        "meta_bargaining_unit_003": ans("teachers represented by Cincinnati Federation of Teachers", "Recognition section states sole and exclusive bargaining agent; signature page lists Cincinnati Federation of Teachers.", "1/85"),
        "meta_document_scope_004": ans("binding agreement", "Contract includes recognition, salaries, fringe benefits, board authority, amendment, legality, and term.", "TOC/85"),
        "meta_text_usability_005": ans("usable", "Contract text is extractable; Appendix A salary table is referenced but not visible in extracted text.", "document"),
        "pay_salary_schedule_001": ans("discussed_unclear", "The salaries of teachers are set forth in Appendix A, attached hereto and made part of this contract; the actual schedule table is not visible in extracted text.", "75", "medium"),
        "pay_salary_schedule_002": ans("2007-2009 agreement; schedule values in missing/not-visible Appendix A", "All salary schedules increased by 1.0% effective Jan. 1, 2007 and 2.0% effective Jan. 1, 2008; Appendix A referenced.", "72/75", "medium"),
        "pay_cost_of_living_019": ans("1; 2", "All salary schedules increased by 1.0% effective January 1, 2007 and 2.0% effective January 1, 2008.", "72"),
        "pay_pay_frequency_020": ans("26 checks year-round or 21 checks school-year biweekly", "Pay plans: Twenty-six checks every other Friday year-round or twenty-one checks every other Friday from opening through end of school.", "75"),
        "pay_national_board_031": ans("1000", "Any teacher attaining National Teacher Board Certification shall have $1000 added to base salary.", "72"),
        "pay_recruitment_retention_030": ans("yes", "For shortage areas, district may provide up to $2,000 per year for up to three years, maximum $6,000.", "73"),
        "pay_hardtostaff_sped_042": ans("yes", "Shortage incentives include areas of mathematics, science, and special education.", "73"),
        "pay_hardtostaff_stem_043": ans("yes", "Shortage incentives include mathematics and science.", "73"),
        "pay_experience_credit_military_public_040": ans("yes", "Allowance for military service is one year of credit for each year of military service up to six years.", "73"),
        "leave_sick_days_001": ans("1.25 days per month", "Full-time teachers accrue sick leave at one and one-fourth day per month for each year under contract.", "35"),
        "leave_sick_accrual_002": ans("cumulative without limitation; new hires after 2004 capped at 200 days", "Unused sick leave shall be cumulative without limitation, except new hires after May 22, 2004 limited to a 200-day cap.", "35"),
        "leave_sick_family_003": ans("yes", "Sick leave may be used for illness, injury, or death of the teacher's immediate family.", "37"),
        "leave_personal_days_006": ans("3", "Teachers may take up to three personal leave days.", "38"),
        "leave_personal_conversion_008": ans("yes", "Unused personal leave days shall be converted to sick leave on July 31.", "38"),
        "leave_bereavement_days_009": ans("3", "Teachers allowed up to three days chargeable to sick leave for death in the immediate family.", "38"),
        "leave_parental_paid_011": ans("30 sick leave days usable for bonding", "A teacher may use up to 30 days sick leave for routine care and bonding with a newborn or newly adopted child.", "37"),
        "workload_workday_length_003": ans("420 minutes including 30-minute duty-free lunch", "Teacher workday shall be no more than 420 consecutive minutes per day, including a duty-free lunch period of 30 minutes.", "30"),
        "workload_lunch_duty_free_008": ans("yes", "Workday includes a duty-free lunch period of thirty minutes.", "30"),
        "workload_lunch_minutes_009": ans("30", "Duty-free lunch period of thirty minutes.", "30"),
        "workload_prep_minutes_006": ans("255 minutes/week elementary; secondary equivalent by schedule", "Elementary K-8 teachers assigned preparation/conference time of 255 minutes per week.", "30"),
        "workload_course_preps_011": ans("3", "Teachers (7-12) shall not be assigned more than three preparations in each marking period.", "32"),
        "workload_meetings_limits_013": ans("yes", "No more than two building-wide staff meetings per month; business faculty meetings no longer than one hour except emergencies.", "33"),
        "class_size_limits_001": ans("yes", "Index and Section 500 include class size limits and enforcement procedures.", "86-88"),
        "benefits_life_amount_011": ans("30000", "Eligibility for the $30,000 term life insurance includes teachers appointed one-half time or more.", "81"),
        "benefits_health_plan_type_005": ans("HMO and POS", "Employees electing medical coverage shall choose a Health Maintenance Organization or Point of Service medical plan.", "76"),
        "benefits_health_employee_premium_003": ans("0.788-2.232 percent of base salary depending plan/tier", "Employee contribution as percentage of base salary: Co-Choice single 0.788%, family 2.206%; New Health single 0.797%, family 2.232%.", "77"),
    },
}


def meta_overrides(doc: dict[str, str], pages: list[str]) -> dict[str, dict[str, str]]:
    overrides = dict(OVERRIDES.get(doc["key"], {}))
    overrides.update(law_coding(doc, pages))
    return overrides


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codebook = parse_codebook()
    qids = [r["Question ID"] for r in codebook]
    if len(qids) != len(set(qids)):
        raise SystemExit("Duplicate Question IDs in codebook")

    meta_cols = [
        "document_id",
        "file_name",
        "district_name",
        "state",
        "document_type",
        "bargaining_unit",
        "start_year",
        "end_year",
        "effective_dates",
        "school_years_covered",
        "union_name",
        "source_document_notes",
    ]
    main_header = meta_cols[:]
    for qid in qids:
        main_header.extend([f"{qid}_answer", f"{qid}_evidence", f"{qid}_page", f"{qid}_confidence"])

    main_rows: list[dict[str, str]] = []
    log_rows: list[dict[str, str]] = []

    for doc in DOCS:
        pages = load_pages(doc)
        word_count = len(" ".join(pages).split())
        ocr_bad = doc["key"] == "wa_2223" or word_count < 50
        overrides = meta_overrides(doc, pages)
        main_row = {col: doc.get(col, "") for col in meta_cols}
        for row in codebook:
            qid = row["Question ID"]
            if qid in overrides:
                coded = overrides[qid]
            else:
                coded = code_from_text(row, pages, ocr_bad)
            # Ensure no blank answers; evidence/page may be blank for not_discussed.
            if not coded.get("answer"):
                coded["answer"] = "not_discussed"
            if not coded.get("confidence"):
                coded["confidence"] = "low" if ocr_bad else "medium"
            main_row[f"{qid}_answer"] = coded["answer"]
            main_row[f"{qid}_evidence"] = coded.get("evidence", "")
            main_row[f"{qid}_page"] = coded.get("page", "")
            main_row[f"{qid}_confidence"] = coded["confidence"]
            log_rows.append(
                {
                    "document_id": doc["document_id"],
                    "file_name": doc["file_name"],
                    "Question ID": qid,
                    "topic category": row["Topic category"],
                    "question": row["Question"],
                    "answer": coded["answer"],
                    "evidence": coded.get("evidence", ""),
                    "page number": coded.get("page", ""),
                    "confidence": coded["confidence"],
                    "coder notes": coded.get("coder notes", ""),
                }
            )
        main_rows.append(main_row)

    with MAIN_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=main_header)
        writer.writeheader()
        writer.writerows(main_rows)
    with LOG_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "document_id",
                "file_name",
                "Question ID",
                "topic category",
                "question",
                "answer",
                "evidence",
                "page number",
                "confidence",
                "coder notes",
            ],
        )
        writer.writeheader()
        writer.writerows(log_rows)

    # Validation summary to stdout.
    blank_answers = sum(1 for r in log_rows if not r["answer"])
    print(f"wrote {MAIN_OUT}")
    print(f"wrote {LOG_OUT}")
    print(f"documents={len(main_rows)} question_ids={len(qids)} log_rows={len(log_rows)} blank_answers={blank_answers}")
    print(f"main_columns={len(main_header)}")


if __name__ == "__main__":
    build()
