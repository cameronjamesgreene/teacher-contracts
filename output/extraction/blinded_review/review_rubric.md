# Blinded review rubric

Every `.task.md` in `review_tasks_top8/` presents two anonymized answers, A and B,
to one codebook question about one contract. Judge each independently against the
document. A and B are randomized per row; do not try to identify their source, and
do not assume the pair contains one right and one wrong answer. Both may be
correct, both may be wrong.

Score five fields per candidate as `yes`, `no`, or `na`.

## status

Is the discussion status right? The statuses are `yes`, `no`, `not_discussed`,
`discussed_unclear`, `not_applicable`, or an extracted value standing in for `yes`.

- `no` is correct only when the document explicitly states the provision is absent,
  prohibited, or not provided. A passage that merely describes something else does
  not support `no`.
- `not_discussed` is correct only when the topic is genuinely absent. Search the
  whole document with several synonym sets before accepting an absence claim.
- A provision that exists only for a named subset (job sharers, specialists, a
  single school level, one contract year) is still discussed. A candidate that
  answers `not_discussed` for such a provision has the wrong status.

Never `na`.

## value

Is the extracted value correct and complete for a question that asks for one
(days, dollars, minutes, percentages, counts, dates, names, lists)?

- `na` when the question asks only whether a provision exists, or when the status
  is a correct `not_discussed`/`not_applicable` so no value is owed.
- `no` when the value is wrong, or when it omits a material variation the document
  states — a different figure for another employee group, school level, plan, or
  contract year.

## evidence

Is the quote verbatim from this document and does it contain the clause that
governs the provision?

- `no` for paraphrase, an altered or stitched quote, ellipsis standing in for
  omitted governing words, a passage label, or a quote about a related but
  different provision.
- `no` when the quote's subject is an excluded classification (principals,
  administrators, supervisors) rather than the teacher/certificated unit.
- `na` when the status is a correct `not_discussed`/`not_applicable`, where no
  evidence is owed. An empty evidence field on a substantive answer is `no`.

## page

Does the reported PDF page actually contain the quoted evidence?

Use the PDF viewer page — the extracted text is form-feed delimited, so the Nth
page block is PDF page N. Printed page numbers in the footer often differ by one
or more; judge against the PDF page, and say so in notes when they diverge.

- `na` when no page is owed (correct `not_discussed`/`not_applicable`) or the field
  is `not_applicable` for that reason.
- `no` when the page is absent, wrong, or off by any amount.

## overall

Would you accept this record as coded data as it stands? `yes` only when status is
right, any owed value is right, and any owed evidence and page are right. Never
`na`.

## reviewer_notes

One to three sentences citing what in the document decided it — article, page, and
the operative words. If you accepted an absence claim, name the search terms you
tried. If a page number is off by a fixed offset, say so.
