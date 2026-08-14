# SOM endpoint — measured capability (2026-08-14)

Measured directly against `api.som.chat`, model `Qwen3.6-35B-A3B-FP8`, using the real
salary-labelling tool schema rather than a toy prompt. These supersede the numbers the
pipeline was built around; several of those were an order of magnitude pessimistic.

## Tool calling

| test | result |
|---|---|
| forced `tool_choice`, `enable_thinking: False` | **works**, correct args first try |
| forced `tool_choice`, thinking ON | **returns no tool call at all** |
| multi-turn loop (search → answer) | **works**, 2 calls in 1.3s total |

The thinking-ON failure matters: reasoning mode and forced tool choice are mutually
exclusive here. Anything built on tool calling must set
`extra_body={"chat_template_kwargs": {"enable_thinking": False}}`, which is what the rest of
the pipeline already does for speed.

On the real Albuquerque p72 prompt the model returned every field correctly, including
`days_per_year: 184` lifted from the page's prose rather than the table:

    {"days_per_year": 184, "employee_group": "teacher",
     "lane_type": "education", "pay_basis": "annual"}

## Latency and concurrency

| test | result |
|---|---|
| bare call, 5 samples | min 0.11s / median 0.12s / max 0.12s |
| single labelling call with tools | ~1.0-1.2s |
| 2-turn agentic loop | 1.3s |
| concurrency 8 | 8/8 succeeded, 1.0s wall |
| concurrency 16 | 16/16 succeeded, 0.6s wall |

## What this changes

The pipeline is configured for "concurrency 8, ~9.6s per call", and that shaped every design
decision about how much the model could be asked to do. The real figures are roughly **10x
cheaper**, and concurrency 16 completed *faster* than 8 rather than degrading.

Recomputed budgets:

| workload | old assumption | measured |
|---|---|---|
| salary stage 3 (216 page-ranges) | ~4-5 min | **~30 seconds** at concurrency 16 |
| rights, one call per clause (55,119) | infeasible | **~60 min**; batched, minutes |
| rights, agentic loop per clause | infeasible | affordable |

The consequence for architecture: an agentic, multi-turn, per-clause treatment is **not**
ruled out by the endpoint. The constraint I had been designing around was largely imaginary.

## Caveats

- Measured on one afternoon; the endpoint is shared and has been slow before. The historical
  62.3s → 9.6s reasoning measurement was real when taken, so treat these as an upper bound on
  capability, not a guarantee. Any production loop still needs the separate timeout/connection
  retry budgets (`APITimeoutError` subclasses `APIConnectionError`).
- Concurrency was tested to 16, not to failure. The previously observed ~24-32 in-flight
  ceiling has not been re-tested and a dropped connection at 24 once voided 41% of a
  document's windows.
- These are latency measurements, not accuracy measurements. Nothing here says the model's
  labels are right — only that asking it is cheap.
