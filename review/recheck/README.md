# Re-check: 11 sheets, CSV only

## Why you're seeing these again

Your first two packets rendered each table by pivoting into `(step label, column header)`.
UTLA-style schedules print an annual line and a monthly line per pay level and label **only
the annual one**, so every unlabelled row collapsed onto a single key. You were shown a
fraction of the table and correctly called it truncated — **of the extraction, which was
complete.**

The worst case was P06: 484 cells in the data, **19 shown**.

Sheets that lost nothing are not reissued. **Your other 16 verdicts stand** — I'm not asking
you to redo them.

## What's here

One CSV per table plus its page image:

    P25_p328.csv        the table, in printed order, every row
    P25_p328-328.png    the page as printed

Open the CSV in Excel beside the image. Three comment rows at the top carry the title, cell
count and how many cells the old sheet hid. Row 4 is the header; everything below is data,
in the order it appears on the page.

**A blank `step` cell is expected**, not a missing row — it's the second line of an
annual/monthly pair, and that is exactly what the old renderer was throwing away.

Record verdicts in `RECHECK_VERDICTS.csv` (same scheme as before: `correct`,
`wrong_position`, `wrong_values`, `truncated`, `not_a_salary_table`, `cant_tell`).

## What already stands from your round-2 pass

These came through lossless sheets and I've taken them as real:

- **`BA+60` ordered last instead of between `BA+45` and `MA`** (P01, P02, P23) — column order
- **Two-row column headers mishandled** (P19, P22, P24)
- **Titles missing or truncated** (P12, P18, P21, P26)
- **Pittsburgh row duplication** (P05) — the legacy image path

Those are on the fix list regardless of what this round says.
