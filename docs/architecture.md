# Architecture

## Components

```
┌────────────────────┐   natural language    ┌──────────────────────────┐
│  User / adk web    │ ───────────────────▶  │  ADK agent (Python)      │
│  / CLI / eval      │ ◀───────────────────  │  LlmAgent on Gemini      │
└────────────────────┘   grounded answer     │  7 function tools        │
                                             └───────────┬──────────────┘
                                                         │ gRPC (typed RPCs)
                                                         ▼
                                             ┌──────────────────────────┐
                                             │  Tool service (Java 21)  │
                                             │  MerchantAnalyst gRPC    │
                                             │  hand-written SQL files  │
                                             └───────────┬──────────────┘
                                                         │ BigQuery API
                                                         ▼
                                   bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*
```

- **Agent** (`agent/merchant_analyst`): one `LlmAgent`. Its instruction forbids
  stating numbers that were not returned by a tool. Each tool is a thin
  wrapper over one gRPC method and returns a plain dict with ints as ints,
  money rounded to 2 decimals and rates to 4.
- **Tool service** (`tool-service/`): a fixed menu of seven RPCs defined in
  `proto/merchant/v1/analyst.proto`. There is no free-form SQL. Every response
  carries `QueryMeta` (applied date range, clamped flag, SQL hash, bytes
  processed, cache hit) so results are auditable.
- **Eval harness** (`agent/merchant_eval`, cases in `eval/cases.yaml`): runs
  questions through the ADK `Runner`, captures every tool response from the
  event stream, extracts every number from the final answer and requires each
  one to be grounded in a tool result (directly or via a one-step derivation).
  Golden cases additionally call the tool directly with fixed arguments and
  assert the answer contains the resulting values.

## Request sequence

```
User ──question──▶ Runner ──▶ LlmAgent ──function_call──▶ tool fn ──gRPC──▶ Java service ──SQL──▶ BigQuery
                                   ◀──function_response──┘            ◀── proto ───┘       ◀── rows ──┘
                             LlmAgent ──final text──▶ Runner ──answer──▶ User
                                                        └──events──▶ eval harness (tool responses + answer)
```

## Dataset

`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`: daily-sharded
GA4 export of the Google Merchandise Store, **2020-11-01 to 2021-01-31**,
obfuscated (some fields are masked or sampled). Requested ranges that partially
overlap the window are clamped by the service and flagged in `QueryMeta.clamped`;
the agent is instructed to mention this. Ranges entirely outside the window are
rejected with `INVALID_ARGUMENT` so the agent cannot present a one-day clamp as
a month's figure.

## Metric definitions

All metrics are computed on the clamped date range, over `_TABLE_SUFFIX`
between the YYYYMMDD bounds.

| Metric | Definition |
|---|---|
| Session | distinct `(user_pseudo_id, event_params.ga_session_id)` |
| Revenue | `SUM(ecommerce.purchase_revenue)` on `event_name = 'purchase'`, USD |
| Orders | `COUNT(DISTINCT ecommerce.transaction_id)` on purchase events, excluding null and `(not set)` |
| Units | `SUM(ecommerce.total_item_quantity)` on purchase events |
| Purchasers | distinct `user_pseudo_id` with at least one purchase event |
| Purchasing sessions | distinct sessions with at least one purchase event |
| Average order value | revenue / orders (0 when no orders) |
| Conversion rate | purchasing sessions / sessions, as a fraction in [0, 1] |
| Product revenue | `SUM(items.item_revenue)` per `items.item_name` on purchase events |
| Product units | `SUM(items.quantity)` per item on purchase events |
| Product orders | distinct `transaction_id` containing the item |
| Traffic source | `traffic_source.source` / `traffic_source.medium` (user-scoped acquisition source in the GA4 export) |
| Funnel step | distinct sessions containing `view_item`, `add_to_cart`, `begin_checkout`, `purchase`; step rate = sessions / previous step; cumulative rate = sessions / first step |
| Country | `geo.country` |

Rounding happens once, in the Python tool wrapper, so the model and the eval
harness see identical numbers.

## Grounding check

For each answer the harness:

1. Extracts numeric mentions (`$12,345.67`, `12.3%`, `1.2k`, `1,234`), skipping
   dates, years, list markers and times.
2. Flattens every numeric leaf of every tool response (and tool arguments
   such as `limit`) into a source set with JSON paths.
3. Matches each mention against the sources: exact or rounded to the shown
   precision, percent vs fraction, k/M scaling, one-step derivations (sum,
   difference, ratio, percent change, sum over sibling rows), or structural
   counts (number of rows).
4. Fails the case on any unmatched mention and reports the span with context.

This catches invented figures, silent re-computation errors and numbers
copied from the wrong field, while tolerating ordinary formatting.

## Non-goals (v1)

- Free-form SQL from the model.
- Forecasting or trend extrapolation.
- Multi-turn memory beyond one ADK session.
- Authentication on the gRPC service (run it locally or behind your own mesh).
