# Salary table hand-review — 27 tables (round 2)

## What changed since your last pass

You found it: the output was treating a page as holding one table. It doesn't — 14 of 92
table-bearing pages hold 2–4 schedules, and **17 of the 27 sheets you were given mixed
several tables together**. That's fixed. A table is now delimited by its heading, so a page
with ten pay grades yields ten tables, each with its own title and header.

**Your earlier verdicts describe the old merge, not the extraction.** They're kept for
comparison, but this packet supersedes them.

Measured effect: `grid_id`s carrying more than one schedule title went from **252 of 411 to
6 of 693**, with cell count essentially unchanged (34,413 → 34,232).

## Why you're doing this round

Same question as before, still unanswered: **does the Apple Vision agreement score track
correctness?** On pages I verified byte-perfect it scores 0.705 to 0.955, so no threshold
separates right from wrong. If low-scoring tables really are the wrong ones, the score
becomes a free measure across all 693 tables and you never do this at scale. That's why the
sample is stratified by agreement band, not random.

27 tables, 6,046 cells, roughly 2–4 minutes each. Please do them in order.

## How to check one table

Each has two files in `review/pages/`:

| file | what it is |
|---|---|
| `P01_p689-689.png` | the contract page as printed |
| `P01_p689_extracted.txt` | the table the pipeline extracted |

Open both, compare the numbers, record a verdict in `review/VERDICTS.csv`.

| verdict | meaning |
|---|---|
| `correct` | every value present, in the right row and column |
| `wrong_position` | real numbers from this page, wrong row/column |
| `wrong_values` | numbers not on the page, or misread digits |
| `truncated` | values right but rows/columns of **this** schedule are missing |
| `not_a_salary_table` | not pay data at all |
| `cant_tell` | illegible or undecidable — say why in `notes` |

Put a rough count in `wrong_cells_approx` (5, 20, "half") when it isn't `correct`.

## Things to know before you start

- **Several sheets come from the same page.** That is the fix working, not a duplicate. You
  are only checking the schedule shown in the sheet. If the page holds other schedules that
  aren't in it, that is expected and is **not** truncation.
- **`step` should be the row's own label** — `01`, `1`, `20D E basis`, `Minimum`. If it
  reads like a sentence, that's a bug worth noting.
- **Empty column headers can be correct.** UTLA-style schedules print a monthly and an
  annual figure per pay level with no header on the second.
- **A `low_density` sheet** carries one amount per row. That's either a real extra-duty
  schedule (`Baseball  $2,205`) or a prose page wrongly clustered into a grid. No automated
  test I tried separates the two — density, amount magnitude and label length all score them
  identically — so they're kept and flagged. **Judging a few of these is especially useful**,
  because it decides whether the flag can be trusted as a filter.
- **`employee_group` is blank.** The SOM endpoint went down (a bare call timed out at 227s),
  so labelling didn't finish. Judge the numbers and their positions, not the labels.

## Two requests

**Don't open `review_manifest.csv` until you're done** — it holds the bands and agreement
scores, and knowing them while judging contaminates the thing being measured. The `P01…P27`
numbering is shuffled.

**Three of the 27 are pages I verified myself**, included unlabelled as a consistency check
between your reading and mine. I won't say which.

## When you're done

Send me `review/VERDICTS.csv`. I'll report:

1. whether accuracy differs across the agreement bands — the actual question;
2. a first defensible accuracy estimate for the tables no mechanical check can reach
   (Pittsburgh, Cleveland, Columbus);
3. whether `low_density` separates real stipend schedules from prose artefacts;
4. whether your three control verdicts match mine.
