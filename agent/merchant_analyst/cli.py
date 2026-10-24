"""Ask the merchant analyst one question from the shell.

    uv run python -m merchant_analyst.cli "top 5 products in December 2020"
    uv run python -m merchant_analyst.cli --json "revenue in November 2020"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from merchant_analyst.runtime import AskResult, ask_sync


def summarize_response(response: dict[str, Any], max_len: int = 160) -> str:
    """Compact one-line summary of a tool response: scalars inline, lists as counts."""
    if "error" in response:
        return f"error={response['error']!r}"
    parts: list[str] = []
    for key, value in response.items():
        if key == "meta":
            applied = value.get("date_range_applied", {}) if isinstance(value, dict) else {}
            rng = f"{applied.get('start_date', '?')}..{applied.get('end_date', '?')}"
            flag = " clamped" if isinstance(value, dict) and value.get("clamped") else ""
            parts.append(f"meta={rng}{flag}")
        elif isinstance(value, list):
            parts.append(f"{key}[{len(value)}]")
        elif isinstance(value, dict):
            parts.append(f"{key}{{{len(value)}}}")
        else:
            parts.append(f"{key}={value!r}")
    line = " ".join(parts)
    return line if len(line) <= max_len else line[: max_len - 3] + "..."


def format_trace(result: AskResult) -> str:
    lines = [f"model: {result.model}  events: {result.events}  tool calls: {len(result.tool_calls)}"]
    for i, call in enumerate(result.tool_calls, 1):
        args = ", ".join(f"{k}={v!r}" for k, v in call.args.items())
        lines.append(f"  [{i}] {call.name}({args})")
        lines.append(f"      -> {summarize_response(call.response)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merchant_analyst.cli", description=__doc__)
    parser.add_argument("question", help="natural-language question for the analyst")
    parser.add_argument("--json", action="store_true", help="print the AskResult as JSON")
    parser.add_argument("--user-id", default="cli")
    args = parser.parse_args(argv)

    result = ask_sync(args.question, user_id=args.user_id)
    if args.json:
        json.dump(result.to_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(format_trace(result))
        print()
        print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
