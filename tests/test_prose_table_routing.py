"""A small prose table must be read by exactly one program, not zero.

Measured on Albuquerque, the salary extractor handled 1-2 column regions badly: the four
real matrices (4-7 money columns) scored fidelity 1.000, while every small region scored
0.500-0.833, with half their values not even on the page they cited. Those regions are
now excluded from the salary program on the grounds that a stipend written in sentences
is better read by the sentence programs.

That is only true if the sentence programs actually read them. `rights_score` skipped
whole appendices on the assumption that an appendix is a table — which would have left
Albuquerque's Appendix E ("Credential differentials are provided for credentials above
minimum teacher licensure...") read by nothing at all. These tests pin both halves.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rights_score import exclude_appendices, is_dense_grid
from salary_segment import MIN_TABLE_COLUMNS, PageFingerprint

GRID_PAGE = "\n".join(
    ["                 APPENDIX A — SALARY MATRIX"] +
    [f"   {step}      {40000 + step * 900:,}    {45000 + step * 950:,}    {52000 + step * 1000:,}"
     for step in range(1, 16)])

PROSE_PAGE = """                    APPENDIX E
              CREDENTIAL DIFFERENTIALS
Credential differentials are provided for credentials above minimum teacher licensure.
Differentials are provided because the credential adds to the teacher's knowledge base.
Bilingual and ESL Differentials - refer to Article 6.D on pages 22-24 of this agreement
concerning eligibility, reporting requirements and tuition reimbursement.
  - Teachers who possess a current Bilingual endorsement shall receive 3,000 annually.
"""


class SalaryProgramExcludesProseTablesTest(unittest.TestCase):
    def test_a_matrix_is_a_salary_table(self) -> None:
        matrix = PageFingerprint(page=72, columns=(120, 200, 280, 360, 440, 520, 600),
                                 money_rows=20, money_tokens=140, has_text=True)
        self.assertTrue(matrix.is_table)

    def test_a_one_or_two_column_region_is_not(self) -> None:
        for count in (1, 2):
            with self.subTest(columns=count):
                thin = PageFingerprint(page=84, columns=tuple(range(100, 100 + count * 80, 80)),
                                       money_rows=10, money_tokens=20, has_text=True)
                self.assertFalse(thin.is_table,
                                 "a stipend list is prose, and extracts at fidelity 0.5")

    def test_the_threshold_is_where_a_matrix_starts(self) -> None:
        self.assertEqual(MIN_TABLE_COLUMNS, 3)


class RightsScoreReadsProseAppendicesTest(unittest.TestCase):
    def test_a_dense_grid_is_recognised(self) -> None:
        self.assertTrue(is_dense_grid(GRID_PAGE))

    def test_appendix_prose_is_not_a_grid(self) -> None:
        self.assertFalse(is_dense_grid(PROSE_PAGE))

    # A whole document, so the >60%-blanked backstop inside exclude_appendices does not
    # fire. Passing a lone appendix page trips that guard and restores everything, which
    # says nothing about the filter itself.
    BODY = ("ARTICLE 12 - COMPENSATION\n"
            "Teachers shall receive a stipend of 1,500 for coaching duties.\n" * 6)

    def document(self, *appendix_pages: str) -> list[str]:
        return [self.BODY, self.BODY, self.BODY, *appendix_pages]

    def test_appendix_prose_survives_the_filter(self) -> None:
        """The half that would otherwise leave these pages read by nothing."""
        kept = exclude_appendices(self.document(PROSE_PAGE))
        self.assertTrue(kept[-1].strip(), "appendix prose must reach clause extraction")
        self.assertIn("Bilingual endorsement", kept[-1])

    def test_an_appendix_grid_is_still_skipped(self) -> None:
        """Salary matrices have no clauses; sending them to the classifier is waste."""
        self.assertEqual(exclude_appendices(self.document(GRID_PAGE))[-1], "")

    def test_prose_and_grid_in_the_same_appendix_are_told_apart(self) -> None:
        kept = exclude_appendices(self.document(GRID_PAGE, PROSE_PAGE))
        self.assertEqual(kept[-2], "", "the matrix is skipped")
        self.assertTrue(kept[-1].strip(), "the prose beside it is not")

    def test_body_pages_are_never_touched(self) -> None:
        self.assertEqual(exclude_appendices(self.document())[0], self.BODY)


if __name__ == "__main__":
    unittest.main()
