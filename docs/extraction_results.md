# What we measured, and what it does and does not establish

All numbers are on one contract, `Manchester School District|83.pdf`, against a
38-question answer key. Read the limits section before quoting anything.

## Headline

| system | overall | status | required | complete | page | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| previous extractor (`llm_extract.py`) | 0.079 | 0.842 | 0.737 | 0.469 | 0.132 | 0.711 |
| first FTS/PydanticAI candidate | 0.289 | 0.658 | 0.605 | 0.522 | 0.658 | 0.605 |
| A, full-document sweep | 0.684 | 0.868 | 0.737 | 0.522 | 0.789 | 1.000 |
| B, absence-verified retrieval | 0.842 | 0.947 | 0.868 | 0.760 | 0.921 | 1.000 |
| **A + B reconciled** | **0.895** | 0.947 | 0.921 | 0.774 | 0.921 | 1.000 |

`status` 0.947 is 36 of 38 questions with the correct discussion status, against 32 for
the previous extractor.

## The measurement instrument came first

None of this is knowable without a way to score cheaply. The answer key
(`output/extraction/answer_gold.csv`) was transcribed from 38 independent blinded
reviews, each of which verified a provision against the PDF; the full packet is kept in
`output/extraction/blinded_review/` as provenance.

The scorer reproduces those human judgments exactly — previous extractor status 0.842
(reviewers: 32/38), first candidate 0.658 (25/38) — which is the evidence that the
transcription is faithful rather than convenient.

Variant authors were allowed to run the scorer but forbidden to read the key or
special-case a question id. That constraint is why the numbers mean anything.

## What actually worked

**1. Take the page away from the model.** The previous extractor scored 0.132 on pages
purely by reporting the number printed on the page. In this contract printed footers run
1 behind the PDF page in the body and up to 7 behind in the appendices; one citation was
page 59 of a 54-page PDF. Retrieval already knows each passage's true page. Combined with
requiring contiguous verbatim quotes, evidence went to **1.000**. This is arithmetic, not
prompting.

**2. Never accept an absence claim on the first pass.** Wrongly answering
`not_discussed` was the dominant error in every earlier system. Re-querying with
contract vocabulary before accepting absence took status 0.658 → **0.947**. Of 106
first-pass answers, 38 claimed absence and 3 were overturned — and all three were
appendix or special-employee-group provisions: a job-sharer premium share in Appendix J,
make-up days limited to school psychologists in Appendix I, and an academic-freedom
clause the first wording missed.

**3. Reconstruct the quote rather than trusting it.** The model picks the right clause
reliably and transcribes it unreliably (a dropped word, `"Blue Cross -Blue Shield"`).
The host takes the longest exact run it did get right, expands to clause boundaries, and
emits the passage's own characters. A 60-character anchor floor stops an invented quote
from being "repaired" onto real text.

**4. Read the whole document, not just retrieved fragments.** Extractor A uses 11
overlapping windows with all 106 questions in each prompt, repeated over only the
still-unanswered questions — 33 calls and under 8 minutes. Repeating passes over
unanswered questions was the largest single gain inside that variant.

**5. Fuse lexical and dense retrieval by interleaving.** FTS5 alone has a hard recall
ceiling on appendix provisions: its P@8 and P@10 are identical, and it never retrieves
Appendix B's `Plus.22 Title I Supervisor` line even at depth 30, because that text shares
almost no vocabulary with a question about high-need-subject pay. Dense retrieval reaches
it at depth 8.

| strategy | P@8 | P@10 | appendix@8 |
| --- | --- | --- | --- |
| FTS5 only | 0.889 | 0.889 | 0.375 |
| dense only | 0.861 | 0.861 | 0.750 |
| interleaved | **0.944** | **0.972** | 0.750 |

Reciprocal-rank fusion *loses* to plain interleaving, because RRF rewards passages both
engines found and the entire value of the pair is that they fail on different questions.

## What did not work

- **Reciprocal-rank fusion** — worse than interleaving, as above.
- **A structural section router** that picked named articles from a table-of-contents
  skeleton and read them whole: 0.605 at six times the sweep's call count. Reading whole
  articles gave perfect evidence but poor completeness (0.404), because routing to one
  article misses the appendix carrying the variation.
- **A PydanticAI agent using `output_validator` + `ModelRetry`** to repair quotes rather
  than discard them: 0.632, well short of B. Worth recording that repairing a quote
  *eagerly* measurably hurt (0.632 → 0.500): being told to fix a quote also pressures the
  model to revise a weak answer, and silently repairing removes that pressure. Quote
  repair belongs after a retry, not instead of one.
- **Subset-variation enrichment as a route to a higher score.** It never regresses
  anything and adds completeness (+0.053 on the sweep, +0.023 on the ensemble), but the
  gain shrinks as the upstream extractor improves and is 0.000 on B alone, whose own
  absence re-query already recovers most variations.
- **Denser sweep windows** (32 windows, 64 calls) scored worse overall than 11.
- **Meilisearch**, on operational grounds. It was only ever a convenient local
  `bge-small-en-v1.5` host. Embeddings now live in the same SQLite file as the passages:
  3x faster queries (19 ms vs 59 ms), no Docker, no PyTorch. Retrieval measured slightly
  *better* after the move, most likely because `fastembed` applies BGE's query prefix and
  Meilisearch's embedder did not.

## Limits — read before quoting any number

- **One contract, 38 questions.** Nothing here generalises until it runs on a second
  document.
- **Manchester is development data, not a test set.** Several variant authors ran the
  scorer against it repeatedly. 0.895 is optimistically biased by an unknown amount.
- **Run-to-run variance is large.** Three identical sweep configurations scored 0.658,
  0.684 and 0.737 at temperature 0, and three runs of one agent spanned 0.132. Single-run
  differences under about 0.05 are not signal, which **includes the ensemble's +0.053
  over B alone** — treat that as "no worse, plausibly better", not a win.
- **Prefer paired comparisons.** Score two policies from the *same* model output where
  possible. One unpaired A/B during development suggested the opposite of the right
  conclusion.
- **The page win is partly document-specific.** Manchester's printed-page offset is
  unusual; measured modal offsets elsewhere in the corpus include 0, 0, 1, 1, 10, 12, 18
  and several incoherent. On a zero-offset document the old footer-copying behaviour
  would have scored fine, so the 0.132 → 0.921 delta will not reproduce everywhere.
- **The key covers only questions where two systems disagreed**, so it oversamples hard
  questions and is blind to errors both systems share. The other 68 questions are
  unmeasured.
- **The reference standard is itself uncertain.** Each question was reviewed by one
  reviewer, so accuracy partly measures agreement with one interpretation. One key row
  needed correcting during the work, and two apparent model failures turned out to be
  scorer strictness. Blind double-coding with adjudication, and a reported
  inter-annotator agreement, is needed before the key can carry more weight.
- **The scorer is a proxy in two places.** Required-token matching penalises a correct
  answer phrased unexpectedly, and page credit is page-overlap, so "right page" is not
  quite "right clause".
- **Source document defect.** `raw/Manchester School District/83.pdf` is missing the
  Blue Choice, Matthew Thornton and Delta Dental plan appendices its own table of
  contents lists, so some benefits questions have no answerable ground truth in it. This
  caps achievable accuracy and is a corpus problem, not an extractor problem.

## Remaining failures on the best configuration

4 of 38. Two are answer/evidence mismatch, where the answer is right but the quote
supports a different clause. One is a wrong `not_discussed` on a study-committee-only
provision. One is scorer strictness, where naming FY'08/FY'09/FY'10 is marked wrong
against a key expecting 2007 and 2010.
