"""Segmentation must tell a continuing table from a new one at a page break.

This is the decision both earlier approaches got wrong, in opposite directions: the
density rule split Manchester's schedules into single pages and never rejoined the
continuations, and the tool-calling navigator merged all three annual schedules into
one block. The signals that settle it — column layout, step sequence, the page's own
"(cont.)" marker — are in the PDF geometry and need no model, so they are tested here
without one.

Every case below is a real shape from the corpus, not an invention.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from salary_segment import PageFingerprint, Region, blocks_from_regions, segment


def page(number: int, columns=(126, 208, 290, 373, 455, 537), rows=13,
         steps=None, title="APPENDIX B", tokens=77) -> PageFingerprint:
    if steps is None:
        steps = tuple(str(i) for i in range(1, rows + 1))
    return PageFingerprint(page=number, columns=tuple(columns), money_rows=rows,
                           money_tokens=tokens, steps=tuple(steps), title=title,
                           has_text=True)


class SegmentationTest(unittest.TestCase):
    def test_manchesters_three_annual_schedules_stay_separate(self) -> None:
        """The real case both earlier approaches got wrong.

        Three consecutive pages, identical 6-column layout, each restarting at step 1.
        The density rule split them and never rejoined continuations; the navigator
        merged all three into one block. Geometry says: three tables.
        """
        regions = segment([page(42), page(43, title="APPENDIX B (cont.)"),
                           page(44, rows=14, title="APPENDIX B (cont.)")])
        self.assertEqual(len(regions), 3, "each page restarts its step sequence")
        self.assertEqual([(r.start, r.end) for r in regions], [(42, 42), (43, 43), (44, 44)])
        self.assertTrue(all("restarts" in r.reason for r in regions[1:]))

    def test_continuing_steps_join_into_one_region(self) -> None:
        first = page(72, rows=20, steps=tuple(str(i) for i in range(1, 21)))
        second = page(73, rows=20, steps=tuple(str(i) for i in range(21, 41)))
        regions = segment([first, second])
        self.assertEqual(len(regions), 1)
        self.assertEqual((regions[0].start, regions[0].end), (72, 73))
        self.assertTrue(regions[0].confident)
        self.assertIn("steps continue", regions[0].reason)

    def test_restart_splits_even_when_layout_is_identical(self) -> None:
        first = page(77, rows=10, steps=tuple(str(i) for i in range(1, 11)))
        second = page(78, rows=10, steps=tuple(str(i) for i in range(1, 11)))
        regions = segment([first, second])
        self.assertEqual(len(regions), 2, "a restarting step sequence is a new table")
        self.assertIn("restarts", regions[1].reason)

    def test_a_changed_column_layout_splits(self) -> None:
        first = page(75, columns=(100, 200, 300, 400))
        second = page(76, columns=(100, 200, 300, 400, 500, 600),
                      steps=tuple(str(i) for i in range(14, 27)))
        regions = segment([first, second])
        self.assertEqual(len(regions), 2)
        self.assertIn("column layout changes", regions[1].reason)

    def test_cont_marker_joins_but_is_not_certain(self) -> None:
        """Layout matches and the page says (cont.), but no steps confirm it."""
        first = page(42)
        second = page(43, steps=("$",) * 13, title="APPENDIX B (cont.)")
        regions = segment([first, second])
        self.assertEqual(len(regions), 1)
        self.assertEqual((regions[0].start, regions[0].end), (42, 43))
        self.assertFalse(regions[0].confident, "an unconfirmed join must be adjudicated")
        self.assertTrue(regions[0].joins, "the ambiguous join is recorded for stage C")

    def test_non_adjacent_table_pages_never_join(self) -> None:
        regions = segment([page(28), page(72)])
        self.assertEqual(len(regions), 2)

    def test_prose_pages_are_not_tables(self) -> None:
        prose = PageFingerprint(page=5, has_text=True, money_tokens=3)
        self.assertFalse(prose.is_table)
        self.assertEqual(segment([prose]), [])

    def test_a_scanned_page_yields_nothing_rather_than_a_guess(self) -> None:
        scan = PageFingerprint(page=9)          # no vector text at all
        self.assertFalse(scan.has_text)
        self.assertFalse(scan.is_table)
        self.assertEqual(segment([scan]), [])


class ExpectedCellsTest(unittest.TestCase):
    def test_expected_cells_is_rows_times_columns(self) -> None:
        region = segment([page(42)])[0]
        self.assertEqual(region.expected_cells, 13 * 6)

    def test_a_joined_region_sums_the_rows(self) -> None:
        first = page(72, rows=20, steps=tuple(str(i) for i in range(1, 21)))
        second = page(73, rows=20, steps=tuple(str(i) for i in range(21, 41)))
        self.assertEqual(segment([first, second])[0].expected_cells, 40 * 6)


class BlockSplittingTest(unittest.TestCase):
    def test_regions_are_split_at_the_extractor_ceiling(self) -> None:
        regions = [Region(start=1, end=10, columns=(1, 2, 3), rows=30)]
        self.assertEqual(blocks_from_regions(regions, 4), [(1, 4), (5, 8), (9, 10)])

    def test_a_short_region_is_one_block(self) -> None:
        regions = [Region(start=42, end=43, columns=(1,), rows=26)]
        self.assertEqual(blocks_from_regions(regions, 4), [(42, 43)])




class SplitRegionTest(unittest.TestCase):
    """A split must yield two regions. Truncating one deletes a schedule."""

    def setUp(self) -> None:
        self.fingerprints = [page(42), page(43, title="APPENDIX B (cont.)"),
                             page(44, rows=14, title="APPENDIX B (cont.)")]

    def test_split_keeps_both_halves(self) -> None:
        from salary_segment import split_region
        region = Region(start=42, end=44, columns=(126,) * 6, rows=40)
        parts = split_region(region, 42, self.fingerprints)
        self.assertEqual([(p.start, p.end) for p in parts], [(42, 42), (43, 44)],
                         "the pages after the cut must survive as their own region")

    def test_rows_are_recounted_per_half(self) -> None:
        from salary_segment import split_region
        region = Region(start=42, end=44, columns=(126,) * 6, rows=40)
        first, second = split_region(region, 43, self.fingerprints)
        self.assertEqual(first.rows, 26)     # p42 13 + p43 13
        self.assertEqual(second.rows, 14)    # p44

    def test_a_cut_outside_the_region_is_a_no_op(self) -> None:
        from salary_segment import split_region
        region = Region(start=42, end=42, columns=(126,) * 6, rows=13)
        self.assertEqual(len(split_region(region, 42, self.fingerprints)), 1)


if __name__ == "__main__":
    unittest.main()
