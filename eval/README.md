# Eval harness

The agent answers merchandising questions about the GA4 Google Merchandise
Store sample by calling typed gRPC tools. This harness checks two things about
every answer:

1. **Grounding** - every number in the answer can be traced back to a tool
   result. No tool call, no number. This catches hallucinated and
   mis-transcribed figures regardless of what the question was.
2. **Golden values** - for selected questions, the answer contains the values
   that the *right* tool call returns for explicit arguments (for example the
   top product's name and revenue for December with `limit=5`). This catches
   wrong tool choice, wrong date ranges and wrong metrics even when the
   numbers quoted are "real".

Each case can also require that specific tools were called (`expect_tools`),
that others were not (`forbid_tools`), and that the service clamped the date
range (`expect_clamped`).

Code lives in `agent/merchant_eval/`; offline unit tests in `agent/tests/eval/`.

## How grounding works

`merchant_eval.numbers.extract_numbers` finds numeric mentions in the answer:
`$12,345.67`, `USD 12,345.67`, `12,345`, `12.3%`, `2 percent`, `1.2k`, `3.4M`,
negative numbers with `-` or `−`, `+12.3%`, and numbers inside markdown tables.
It ignores things that are not quantities: ISO and slash dates, times, years
1900-2100 standing alone or next to a month name ("December 2020", "Dec 25"),
ordinal list markers at the start of a line, hex hashes and ordinals ("5th").

`merchant_eval.grounding.collect_tool_numbers` flattens every numeric leaf of
every tool call (arguments and response) into labelled sources such as
`get_top_products[1].response.rows[2].revenue`, skipping `sql_hash`,
`bytes_processed`, booleans and dates. List lengths are recorded too.

`ground(mention, sources)` tries these strategies in order and stops at the
first hit; the match kind and an explanation end up in the report:

| kind | rule |
|---|---|
| `exact` / `rounded` | source equals the mention when rounded to the mention's displayed decimals (`$1,235` for 1234.56, `$52.65` for 52.654). Integer sources must match integer mentions exactly. A mention with more decimals than the source never matches unless equal. |
| `percent` | `5.26%` matches a rate source `0.0526` (checked as value/100 against the rate and value against rate×100). A percent mention never matches a fraction directly, so `0.05%` is not grounded by `0.0526`. |
| `scale` | `1.2k` matches 1,234 (source / 1000 rounded to the displayed decimals); same for `M` and `B`. |
| `structural` | integers 0..10 equal to the length of a list in a response (rows, points, steps) - "the top **3** products". Tool arguments such as `limit` are ordinary sources and match as `exact`. |
| `derived` | depth-1 arithmetic over tool numbers: `a+b`, `a−b` (only between like fields, e.g. revenue and revenue), `a/b` (like fields or fields of the same object, e.g. revenue/orders), `(b−a)/a` as percent change (percent mentions only), `1 − rate` for drop-offs, and sum / mean over same-path siblings (`rows[*].revenue`). All source pairs are tried up to 400 sources; above that only pairs within one tool call. `rank` fields are never combined. |

Anything else is **ungrounded** and fails the case. The report prints the
mention with 30 characters of context on either side so it is quick to judge
whether the agent invented the number or the matcher has a gap.

## How golden checks work

A golden entry names a tool, explicit arguments and a list of paths:

```yaml
golden:
  - tool: get_top_products
    args: {start_date: "2020-12-01", end_date: "2020-12-31", metric: REVENUE, limit: 5}
    answer_must_contain: ["rows[0].item_name", "rows[0].revenue"]
```

The harness calls `merchant_analyst.tools.get_top_products(**args)` itself,
resolves each path (`rows[0].item_name`, `revenue`, `steps[3].sessions`) and
checks the answer contains the value. Numbers go through the same matcher as
grounding (without derivations), so a golden `1234.5` is satisfied by
`$1,234.50`, `$1,235` or `$1.2k`; strings are case-insensitive substrings.

## Running

Live runs need the tool service and a Gemini key (see `.env.example`).

```bash
cd agent
uv run python -m merchant_eval.run                 # all cases, writes eval/reports/<ts>.{json,md}
uv run python -m merchant_eval.run --only dec_totals,forecast_trick
uv run python -m merchant_eval.run --record        # also saves eval/fixtures/<id>.json
uv run python -m merchant_eval.run --replay        # re-check saved fixtures, no model calls
uv run python -m merchant_eval.run --fail-fast
make eval ARGS="--only dec_totals"                 # from the repo root
```

Other flags: `--cases PATH`, `--fixtures DIR`, `--reports DIR`, `--no-report`.
Exit code is 1 when any case fails or errors, 2 on usage errors.

Offline tests for the harness itself:

```bash
cd agent
uv run pytest -q tests/eval
uv run ruff check merchant_eval tests/eval
```

## Replay mode

`--record` stores each `AskResult` (question, answer, tool calls with full
responses, model, event count) plus the responses of the golden tool calls in
`eval/fixtures/<id>.json`. `--replay` evaluates those files instead of calling
the model or the tool service, so CI can run the full check pipeline against a
known set of answers, and matcher changes can be validated against real agent
output without spending tokens. Cases without a fixture are reported as `SKIP`
and do not fail the run. If a fixture's golden entries no longer match the
case file (tool or args changed) the harness falls back to calling the tool
live.

## Reading a report

Each run prints a console table and writes `eval/reports/<UTC timestamp>.json`
and `.md`. Example table (**illustrative, hand-written, not real output**):

| case | status | grounded | ungrounded | golden | tools | time |
|---|---|---|---|---|---|---|
| dec_totals | OK | 4/4 | | 2/2 | ok | 6.1s |
| nov_top5_revenue | OK | 11/11 | | 3/3 | ok | 7.8s |
| mom_revenue_change | OK | 3/3 | | 2/2 | ok | 9.4s |
| dec_funnel_dropoff | FAIL | 6/7 | 85% | 2/2 | ok | 7.0s |
| march_2021_outside_window | FAIL | 2/2 | | - | clamped=False | 5.2s |
| forecast_trick | FAIL | 0/2 | $150,000, 20% | - | ok | 3.9s |

Columns:

- **grounded** - grounded mentions / all numeric mentions in the answer.
- **ungrounded** - the raw spans that could not be traced to a tool result.
- **golden** - passed / total `answer_must_contain` checks (plus `(n err)` when
  a golden tool call itself failed).
- **tools** - `ok`, or `missing <tool>`, `forbidden <tool>`, `clamped=<bool>`.

In the example, `dec_funnel_dropoff` quoted an 85% drop-off that no step rate
(or `1 − rate`) produces; `march_2021_outside_window` expected the service to
clamp the range but the agent queried a range inside the window; and the
forecast answer invented both numbers.

The JSON file has, per case: `question`, `status`, `grounding` (every grounded
mention with its match kind, explanation and source paths; every ungrounded
mention with `context`), `golden` (expected value and verdict per path),
`tools` (expected / called / missing / clamped), a summary of each tool call
(name, args, row counts, applied date range, clamped flag), the full `answer`,
`model`, `events`, `duration_s` and `error`. The markdown file has the table
plus a "Failures" section listing the reasons per failing case.

## Adding a case

Append to `eval/cases.yaml`:

```yaml
  - id: jan_conversion_rate            # unique; also the fixture file name
    question: What was the conversion rate in January 2021?
    expect_tools: [get_sales_summary]  # must all have been called
    forbid_tools: []                   # optional
    expect_clamped: false              # optional
    golden:                            # optional
      - tool: get_sales_summary
        args: {start_date: "2021-01-01", end_date: "2021-01-31"}
        answer_must_contain: [conversion_rate, sessions]
    notes: Rate is a fraction; "4.7%" formatting is fine.
```

Guidelines:

- Use explicit `args` (dates as `YYYY-MM-DD`, enums as names such as `REVENUE`,
  `UNITS`) so the golden call is independent of how the agent phrases its own
  call.
- Pick paths whose values the answer must obviously contain (top item name and
  its metric, a total, a rate). Avoid values an honest answer might omit.
- For comparison questions add one golden per period; the delta itself is
  covered by the derivation rules.
- Questions that should produce no numbers (dataset description, forecasts)
  need no golden: grounding alone fails them if they invent a figure.
- Run `--record --only <id>` once to capture a fixture, inspect the report,
  then keep the fixture so `--replay` covers the new case.
