# Virtual Merchant Analyst

A chat agent that answers merchandising questions about the public
**Google Merchandise Store** GA4 dataset in BigQuery, built so that **every
number in an answer is traceable to a tool result**.

- **Agent**: Python, [Google ADK](https://github.com/google/adk-python) 2.x, Gemini.
- **Tool service**: Java 21, gRPC, hand-written parameterised SQL against
  `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`.
- **Eval harness**: runs questions through the agent, extracts every number
  from each answer and requires it to be grounded in a tool response.

```
user ──▶ ADK LlmAgent (Gemini) ──gRPC──▶ Java MerchantAnalyst service ──SQL──▶ BigQuery
                   │
                   └──events──▶ eval harness: every number grounded? golden values present?
```

See [docs/architecture.md](docs/architecture.md) for the full design and the
metric definitions.

## Why typed tools instead of text-to-SQL

The agent gets a fixed menu of seven RPCs (sales summary, top products, daily
trend, traffic by source, funnel, geo breakdown, dataset info). Each one runs a
reviewed SQL statement with named parameters. The model cannot invent a
metric, there is no SQL injection surface, results are deterministic, and the
eval harness can recompute expected values with the very same tools. Every
response carries `QueryMeta` (applied date range, clamped flag, SQL hash,
bytes processed, cache hit) so an answer can be audited.

## Example

```
$ make agent-cli Q="What were the top 3 products by revenue in December 2020?"

tool  get_top_products(start_date=2020-12-01, end_date=2020-12-31, metric=REVENUE, limit=3)
      -> 3 rows, currency USD, clamped=false

In December 2020 (2020-12-01 to 2020-12-31) the top products by revenue were:

| # | Product | Revenue | Units |
|---|---------|---------|-------|
| 1 | ...     | $...    | ...   |
```

A live transcript is recorded in the eval fixtures once BigQuery and Gemini
credentials are configured (see below). Nothing in this repo is hard-coded
from the dataset.

## Quickstart

Prerequisites: JDK 21, [uv](https://docs.astral.sh/uv/), the
[gcloud CLI](https://cloud.google.com/sdk/docs/install), a GCP project with
the BigQuery API enabled, and a Gemini API key from
[AI Studio](https://aistudio.google.com/).

```bash
# 1. Credentials
cp .env.example .env            # set GCP_PROJECT and GOOGLE_API_KEY
gcloud auth application-default login

# 2. Tool service (terminal 1)
make service-run                # gRPC on localhost:50051, reflection + health enabled

# 3. Agent (terminal 2)
make agent-sync
make agent-cli Q="How did conversion rate change from November to December 2020?"
make agent-web                  # ADK dev UI at http://localhost:8000
```

Or run the tool service in Docker: `docker compose up --build` (reuses your
local Application Default Credentials read-only).

Query cost: the sample tables are small and public dataset reads fall under
the BigQuery free tier. The service sets `maximumBytesBilled`
(`BQ_MAX_BYTES_BILLED`, default 2 GB) on every query as a guard.

## Eval harness

```bash
make eval                       # live: asks every case, checks, writes eval/reports/<ts>.{json,md}
make eval ARGS="--only nov_top5_revenue,dec_funnel_dropoff"
make eval ARGS="--record"       # also saves fixtures to eval/fixtures/
make eval ARGS="--replay"       # re-check saved fixtures, no model or service needed
make eval-test                  # offline unit tests for the extractor and matcher
```

Two checks run per case, defined in [eval/cases.yaml](eval/cases.yaml):

1. **Grounding**: every numeric mention in the answer (`$12,345.67`, `12.3%`,
   `1.2k`, `1,234`) must match a number in some tool response or argument:
   exactly or rounded to the shown precision, as percent of a fraction, at
   k/M scale, as a one-step derivation (sum, difference, ratio, percent
   change, sum or mean over sibling rows), or as a structural count (number of
   rows). Dates, years and list markers are not counted as numbers. Any
   unmatched mention fails the case and is reported with its surrounding text.
2. **Golden values**: selected cases call a tool directly with fixed
   arguments and assert the answer contains the resulting values, so the
   right numbers for the wrong question (wrong month, wrong metric) still fail.

Cases can also require that specific tools were (or were not) called and that
a date range was clamped. The run exits non-zero on any failure, so it can
gate a CI job. Full details in [eval/README.md](eval/README.md).

## Repository layout

```
proto/merchant/v1/analyst.proto   gRPC contract (single source of truth for both sides)
tool-service/                     Java 21 gRPC service, SQL in src/main/resources/sql/
agent/merchant_analyst/           ADK agent, tools, gRPC client, CLI, generated stubs (pb/)
agent/merchant_eval/              eval harness (extractor, matcher, golden checks, runner)
agent/agents/merchant_analyst/    discovery shim for `adk web` / `adk run`
eval/cases.yaml                   eval cases; eval/reports/ for output; eval/fixtures/ for recordings
docs/architecture.md              components, request flow, metric definitions
```

## Development

```bash
make test                       # Java unit tests + Python unit tests, no cloud needed
make service-test               # ./mvnw test (59 tests, fake BigQuery gateway)
make agent-test                 # pytest (agent + eval, 142 tests)
make proto                      # regenerate Python stubs after editing the proto
cd tool-service && GCP_PROJECT=<id> ./mvnw -Pbq test   # one live BigQuery integration test
```

CI runs both suites on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Limitations

- No free-form SQL: questions outside the seven tools get a "not available"
  answer by design.
- The dataset covers 2020-11-01 to 2021-01-31 only and is obfuscated by
  Google. Ranges that partially overlap are clamped and flagged; ranges
  entirely outside are rejected.
- No forecasting. The agent is instructed to refuse, and the eval harness
  flags any ungrounded figure if it does not.
- The gRPC service has no authentication; run it locally or behind your own
  network controls.

## License

Apache-2.0. See [LICENSE](LICENSE).
