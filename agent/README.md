# merchant-analyst (Python)

ADK + Gemini agent that answers questions about the Google Merchandise Store GA4 sample
(2020-11-01 to 2021-01-31) by calling the Java `MerchantAnalyst` gRPC tool service. Every
number in an answer comes from a tool result.

```
merchant_analyst/        the agent package
  agent.py               root_agent (LlmAgent) + system instruction
  tools.py               7 tool functions (ADK wraps them; docstrings are the model contract)
  client.py              AnalystClient (gRPC) + proto_to_dict
  runtime.py             ask() / ask_sync() -> AskResult   (used by the CLI and merchant_eval)
  cli.py                 python -m merchant_analyst.cli "question"
  pb/merchant/v1/        generated protobuf stubs (committed; see "Regenerating stubs")
agents/merchant_analyst/ discovery shim for `adk web` / `adk run`
scripts/fix_pb_imports.py
tests/                   offline unit tests (fake in-process gRPC server, stub agent)
```

## Setup

```bash
cd agent
uv sync --all-groups          # or: make agent-sync (from the repo root)
cp ../.env.example ../.env    # then fill in GOOGLE_API_KEY
```

The repo-root `.env` is loaded automatically (python-dotenv, searched upwards from the
package) when `merchant_analyst.agent` or `merchant_analyst.runtime` is imported.

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOOGLE_API_KEY` | – | Gemini key (AI Studio). Or set `GOOGLE_GENAI_USE_VERTEXAI=TRUE` + GCP vars. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Model passed to `LlmAgent`. |
| `TOOL_SERVICE_ADDRESS` | `localhost:50051` | Address of the Java gRPC tool service. |

## Run

Start the tool service first (`make service-run` at the repo root), then:

```bash
# ADK dev UI: open http://127.0.0.1:8000 and pick "merchant_analyst"
uv run adk web agents

# one-shot / interactive terminal run
uv run adk run agents/merchant_analyst "top 5 products in December 2020"
uv run adk run agents/merchant_analyst

# project CLI: prints the tool trace (name, args, one-line response summary), then the answer
uv run python -m merchant_analyst.cli "how did revenue change from November to December 2020?"
uv run python -m merchant_analyst.cli --json "conversion rate in January 2021"
```

`adk web AGENTS_DIR` expects a directory whose subfolders each contain `agent.py` exposing
`root_agent`; `agents/merchant_analyst/agent.py` just re-exports it from the package.

## Programmatic use

```python
from merchant_analyst.runtime import ask_sync

r = ask_sync("revenue in December 2020")
r.answer        # final text
r.tool_calls    # [ToolCall(name, args, response)], paired by function-call id
r.model, r.events
```

## Tests and lint

```bash
uv run pytest -q tests --ignore=tests/eval   # agent tests (no network, no Gemini)
uv run ruff check .
```

`tests/conftest.py` starts an in-process gRPC server with a fake servicer generated from the
same proto; `tests/test_runtime.py` drives `ask()` with a scripted `BaseAgent` so the
runner/event folding is exercised without a model call.

## Regenerating stubs

From the repo root: `make proto`. Equivalent, from `agent/`:

```bash
uv run python -m grpc_tools.protoc -I../proto \
  --python_out=merchant_analyst/pb --grpc_python_out=merchant_analyst/pb --pyi_out=merchant_analyst/pb \
  ../proto/merchant/v1/analyst.proto
uv run python scripts/fix_pb_imports.py   # rewrites `from merchant.v1 import ...` to the package path
```
