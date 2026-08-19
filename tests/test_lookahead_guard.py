"""A grid must not be attributed to pages it was not read from.

The vision call sees the block's pages plus the next one, labelled context-only. On
Manchester block 43-43 the model transcribed page 44's schedule and returned it as page
43's; dedup then discarded the real page-44 grid as a duplicate and the FY'09 schedule
vanished from the output entirely, with nothing to flag it.

The guard is deliberately conservative — a genuine table continuing across the break
has values on both pages and must survive."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from salary_schedule import misattributed_to_lookahead as mis
def tbl(vals): return {"cells":[{"value":str(v)} for v in vals]}
class LookaheadMisattributionTest(unittest.TestCase):
    def test_reads_lookahead(self):
        self.assertTrue(mis(tbl([32588,35194,36497,39106,39758,40834]),
                            "31,018 33,499 34,739 37,221 37,842 38,866",
                            "32,588 35,194 36,497 39,106 39,758 40,834"))
    def test_reads_own_block(self):
        self.assertFalse(mis(tbl([31018,33499,34739,37221,37842,38866]),
                             "31,018 33,499 34,739 37,221 37,842 38,866",
                             "32,588 35,194 36,497 39,106 39,758 40,834"))
    def test_continuation_spanning_both_is_kept(self):
        self.assertFalse(mis(tbl([31018,33499,34739,39106,39758,40834]),
                             "31,018 33,499 34,739", "39,106 39,758 40,834"))
    def test_too_few_values_to_judge(self):
        self.assertFalse(mis(tbl([32588,35194]), "31,018", "32,588 35,194"))
    def test_no_lookahead(self):
        self.assertFalse(mis(tbl([32588,35194,36497,39106,39758,40834]), "31,018", ""))
class ReattributionTest(unittest.TestCase):
    """Detecting the misattribution is only half the fix; discarding loses the data.

    Pittsburgh is OCR'd, so every block goes down the vision path and the model read the
    following page each time. Dropping those grids produced 9 extracted blocks and 0
    written grids — a document with no salary data at all. The values are real and the
    page they belong to is known, so the grid is moved rather than deleted.
    """

    def test_a_misattributed_grid_is_moved_not_dropped(self) -> None:
        import salary_schedule
        block, lookahead = "31,018 33,499 34,739", "39,106 39,758 40,834 41,900 42,700"
        table = {"cells": [{"value": v} for v in
                           ("39106", "39758", "40834", "41900", "42700", "43500")]}
        self.assertTrue(salary_schedule.misattributed_to_lookahead(table, block, lookahead))

    def test_a_correctly_attributed_grid_is_untouched(self) -> None:
        import salary_schedule
        block = "31,018 33,499 34,739 37,221 37,842 38,866"
        table = {"cells": [{"value": v} for v in
                           ("31018", "33499", "34739", "37221", "37842", "38866")]}
        self.assertFalse(salary_schedule.misattributed_to_lookahead(
            table, block, "39,106 39,758 40,834"))


if __name__ == "__main__":
    unittest.main()
