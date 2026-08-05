# OCR fidelity: what the citation audit cannot see

## The problem in one line

`scripts/audit_citations.py` verifies that a quote appears verbatim in the *extracted text*.
For an OCR'd document, the extracted text **is the OCR output**, so **every OCR error is
invisible to the audit** — including fabricated content.

Demonstrated: olmOCR-2 emitted `![A stamp in the bottom right corner](https://i.imgur.com/…)`
on a blank page of the Pittsburgh scan, a fabricated image URL for content that does not
exist. That string is in the extracted text, so an answer quoting it would score verbatim
1.000, contiguous 1.000, on_page 1.000. The audit compares answers to the OCR text and
never to the PDF.

Earlier reporting said OCR'd documents "behave like born-digital ones" on the strength of a
0.975 integrity score. That claim was about internal consistency, not fidelity, and should
not have been stated without this qualification.

## What olmOCR-2 gets right and wrong

An independent reviewer spot-checked four PDF pages of the Pittsburgh scan against the OCR.
Findings verified directly:

**Narrative prose: effectively verbatim.** Pages of running text match word for word,
including `403(b)`, `Article 130, Severance Pay, Section 7`, and `maximum of twenty (20)
students per PRC teacher`. Provision-level questions can be coded from this text.

**Numbers inside tables: systematically wrong.** The salary schedules are printed rotated
90° with a staircase layout, and the model flattened them into misaligned rows. Steps and
years are transposed, and percentages attach to the wrong rows. Verified digit corruption on
one page alone:

| PDF says | OCR says |
| --- | --- |
| `195 days` | `135 days` |
| `202 days (192 days + 10 additional…)` | `132 days (192 days - 10 additional…)` |
| `eight (8) hours` | `eighty (8) hours` |

Note the third: `eighty (8)` is internally contradictory, so a careful reader can catch it,
but nothing in the pipeline does.

**Degenerate generation loops, with content loss.** Page 19 repeats an incrementing row for
roughly 200 lines and is truncated mid-token; it is 6,240 characters against a 3,015-character
median page. Page 25 repeats a row about 130 times. Real content on those pages is gone.

**Hallucination.** The fabricated URL above.

## Consequence for this project

The codebook asks for dollar amounts, day counts, minutes and percentages. Those live
disproportionately in tables and schedules, which is exactly where this OCR is least
trustworthy. So:

- **Provision-level and yes/no questions on OCR'd documents: usable.**
- **Numeric answers sourced from a schedule or table page on an OCR'd document: not
  trustworthy without checking the PDF.**

## This reverses an earlier judgement

The team's original four-engine benchmark had Apple Vision ahead on **fact recall** (89.5%
against olmOCR-2's 81.6%) while behind on character accuracy. That result was dismissed
earlier in this work as a small-sample artifact. It now looks correct and mechanistically
explicable: a deterministic OCR engine transcribes whatever glyphs are present, whereas a
vision-language model *reconstructs* a page and will therefore smooth, transpose, loop or
invent when a layout is hard. Character accuracy rewards fluent output; fact recall punishes
confabulation.

olmOCR-2 remains the right default, because it returns reading order natively and Apple
Vision does not — and owning bounding-box reconstruction on the critical path of every
citation is worse. But the fact-recall gap was real and the reason for it is now understood.

## What to do about it

1. **Flag table-dense pages.** A page whose character count is a large multiple of the
   document median, or that contains many short numeric lines, should be marked
   `low_confidence_layout`, and numeric answers citing it flagged for human check.
2. **Detect degenerate loops mechanically.** A page with a low distinct-line ratio, or one
   far above the median length, is a generation-loop signature and should be re-OCR'd or
   excluded.
3. **Cross-check numbers against a second engine.** Where a numeric answer cites an OCR'd
   page, a deterministic engine's reading of the same page is a cheap independent check;
   disagreement means "go look at the PDF".
4. **Never claim OCR quality from a citation audit.** Fidelity requires comparison against
   the PDF, which means either a second engine or human spot-checks.
