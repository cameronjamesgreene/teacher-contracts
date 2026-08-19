"""The salary grid scorer must catch the defects salary_schedule.py is known to have.

Salary extraction has no answer key, so this scorer is the only cheap signal available
and it has to be trustworthy before any change is measured against it. Each test below
is one of the failure modes recorded in the version history: values that are not on the
page (vision transcription error), a grid that stops early (truncation), and the same
table emitted twice under different labels.

The scorer is deliberately *not* an accuracy metric, and one test pins the reason: a
two-cell grid scores a perfect fidelity, which is why capture is reported beside it.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import score_salary_grids as scorer

PAGE = """
                 TEACHER SALARY SCHEDULE 2021-22
    Step        Lane A          Lane B          Lane C
      1         54,461          66,838          95,393
      2         55,950          69,545          96,986
      3         57,480          72,331          98,624
      4         59,054          75,201         100,309
"""


def write_grid(directory: Path, name: str, pages: str, body: list[list[str]]) -> Path:
    path = directory / name
    lines = [f"# Contract.pdf — Teacher Salary Schedule (2021-22)",
             f"# pages: {pages} | extraction_method: text",
             "# population: teachers | is_teacher_schedule: True",
             "# validation_warnings: none | audit confirmed"]
    rows = ["\n".join(lines)] + [",".join(row) for row in body]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


class GridScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.pages = ["cover page", PAGE, "unrelated appendix"]   # PAGE is PDF page 2

    def score(self, path: Path) -> dict:
        grid = scorer.parse_grid(path)
        self.assertIsNotNone(grid, "grid failed to parse")
        result = scorer.score_grid(grid, self.pages)
        result["monotonic"] = scorer.monotonic_share(grid)
        return result

    def test_a_faithful_complete_grid_scores_clean(self) -> None:
        path = write_grid(self.dir, "good.csv", "2-2", [
            ["step", "Lane A", "Lane B", "Lane C"],
            ["1", "54461", "66838", "95393"],
            ["2", "55950", "69545", "96986"],
            ["3", "57480", "72331", "98624"],
            ["4", "59054", "75201", "100309"]])
        result = self.score(path)
        self.assertEqual(result["fidelity"], 1.0)
        self.assertEqual(result["capture"], 1.0)
        self.assertEqual(result["monotonic"], 1.0)
        self.assertEqual(result["note"], "")

    def test_values_not_on_the_page_are_caught(self) -> None:
        """A vision misread puts a figure in the grid that the page never contained."""
        path = write_grid(self.dir, "wrong.csv", "2-2", [
            ["step", "Lane A", "Lane B", "Lane C"],
            ["1", "54461", "66838", "95393"],
            ["2", "55950", "69545", "13200"],       # invented
            ["3", "57480", "72331", "98624"],
            ["4", "59054", "75201", "100309"]])
        result = self.score(path)
        self.assertLess(result["fidelity"], 1.0)
        self.assertIn("not on the cited page", result["note"])

    def test_truncation_shows_up_as_low_capture(self) -> None:
        """The known defect: rows dropped at a page break, grid looks internally fine."""
        path = write_grid(self.dir, "short.csv", "2-2", [
            ["step", "Lane A", "Lane B", "Lane C"],
            ["1", "54461", "66838", "95393"]])
        result = self.score(path)
        self.assertEqual(result["fidelity"], 1.0, "every value is genuinely on the page")
        self.assertLess(result["capture"], scorer.LOW_CAPTURE)
        self.assertIn("truncation", result["note"])

    def test_fidelity_alone_is_gameable_which_is_why_capture_exists(self) -> None:
        path = write_grid(self.dir, "tiny.csv", "2-2", [
            ["step", "Lane A"], ["1", "54461"]])
        result = self.score(path)
        self.assertEqual(result["fidelity"], 1.0)
        self.assertLess(result["capture"], 0.2)

    def test_a_falling_column_is_flagged_as_non_monotonic(self) -> None:
        path = write_grid(self.dir, "falling.csv", "2-2", [
            ["step", "Lane A"],
            ["1", "59054"], ["2", "57480"], ["3", "55950"], ["4", "54461"]])
        self.assertEqual(self.score(path)["monotonic"], 0.0)

    def test_missing_page_provenance_is_reported_not_guessed(self) -> None:
        path = self.dir / "nopages.csv"
        path.write_text("# Contract.pdf — Schedule ()\nstep,Lane A\n1,54461\n", encoding="utf-8")
        grid = scorer.parse_grid(path)
        result = scorer.score_grid(grid, self.pages)
        self.assertEqual(result["fidelity"], "")
        self.assertIn("no page provenance", result["note"])

    def test_pages_are_read_from_the_filename_when_the_header_lacks_them(self) -> None:
        """Older grids recorded the range only in the name, on a collision."""
        path = self.dir / "legacy__p2-2.csv"
        path.write_text("# Contract.pdf — Schedule ()\nstep,Lane A\n1,54461\n", encoding="utf-8")
        grid = scorer.parse_grid(path)
        self.assertEqual((grid["page_start"], grid["page_end"]), (2, 2))
        self.assertEqual(scorer.score_grid(grid, self.pages)["fidelity"], 1.0)


class FigureParsingTest(unittest.TestCase):
    def test_comma_and_decimal_forms_compare_equal(self) -> None:
        self.assertEqual(scorer.figures("54,461 and 54461.00"), {"54461"})

    def test_step_and_article_numbers_are_not_treated_as_pay(self) -> None:
        self.assertEqual(scorer.figures("Step 3 of Article 12, see section 7"), set())

    def test_bare_years_are_not_counted_as_salary_figures(self) -> None:
        """Otherwise every dated page inflates its own figure count and capture sags."""
        self.assertEqual(scorer.figures("2021-22 Schedule, effective July 1, 2023"), set())

    def test_money_shaped_values_in_the_year_range_are_kept(self) -> None:
        self.assertEqual(scorer.figures("a $2,021 stipend"), {"2021"})


if __name__ == "__main__":
    unittest.main()


class MonotonicScopeTest(unittest.TestCase):
    """Monotonicity is only meaningful where a step axis exists."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())

    def test_a_step_ladder_is_scored(self) -> None:
        path = write_grid(self.dir, "steps.csv", "2-2", [
            ["step", "Lane A"], ["1", "54461"], ["2", "55950"], ["3", "57480"]])
        self.assertEqual(scorer.monotonic_share(scorer.parse_grid(path)), 1.0)

    def test_a_table_without_steps_is_not_scored(self) -> None:
        """A credential differential has no step axis; 0.000 would be a false alarm."""
        path = write_grid(self.dir, "diff.csv", "2-2", [
            ["credential", "amount"], ["National Board", "54461"],
            ["Bilingual", "55950"], ["Special Ed", "54461"]])
        self.assertEqual(scorer.monotonic_share(scorer.parse_grid(path)), "")
