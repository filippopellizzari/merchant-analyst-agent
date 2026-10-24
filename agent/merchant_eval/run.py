"""Run the eval cases against the agent (or saved fixtures) and write reports.

    python -m merchant_eval.run [--cases PATH] [--only ID,ID] [--record] [--replay]
                                [--fail-fast] [--fixtures DIR] [--reports DIR]

Exit code 1 when any case fails or errors.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import merchant_eval.golden as golden_mod
from merchant_eval.golden import Case, GoldenResult, check_golden, check_tools, load_cases
from merchant_eval.grounding import check_answer
from merchant_eval.report import build_record, render_console, write_reports

AGENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_DIR.parent
DEFAULT_CASES = REPO_ROOT / "eval" / "cases.yaml"
DEFAULT_REPORTS = REPO_ROOT / "eval" / "reports"
DEFAULT_FIXTURES = REPO_ROOT / "eval" / "fixtures"


@dataclass
class ReplayToolCall:
    name: str
    args: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)


@dataclass
class ReplayResult:
    """Duck-type of ``merchant_analyst.runtime.AskResult`` loaded from a fixture."""

    question: str
    answer: str
    tool_calls: list[ReplayToolCall] = field(default_factory=list)
    model: str = "replay"
    events: int = 0
    duration_s: float | None = None
    golden_responses: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _plain(obj: Any) -> Any:
    """Best-effort conversion of dataclasses / objects to JSON-able data."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    if isinstance(obj, str | int | float | bool) or obj is None:
        return obj
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _plain(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if hasattr(obj, "__dict__"):
        return {k: _plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def result_to_fixture(
    case: Case, result: Any, duration_s: float, golden_responses: list[dict]
) -> dict[str, Any]:
    return {
        "id": case.id,
        "question": getattr(result, "question", case.question),
        "answer": getattr(result, "answer", ""),
        "tool_calls": [
            {
                "name": getattr(tc, "name", None),
                "args": _plain(getattr(tc, "args", {})),
                "response": _plain(getattr(tc, "response", {})),
            }
            for tc in getattr(result, "tool_calls", []) or []
        ],
        "model": getattr(result, "model", None),
        "events": getattr(result, "events", None),
        "duration_s": round(duration_s, 3),
        "golden_responses": golden_responses,
    }


def load_fixture(path: Path) -> ReplayResult:
    data = json.loads(path.read_text())
    return ReplayResult(
        question=data.get("question", ""),
        answer=data.get("answer", ""),
        tool_calls=[
            ReplayToolCall(tc.get("name"), tc.get("args") or {}, tc.get("response") or {})
            for tc in data.get("tool_calls") or []
        ],
        model=data.get("model") or "replay",
        events=data.get("events") or 0,
        duration_s=data.get("duration_s"),
        golden_responses=data.get("golden_responses") or [],
    )


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _ask(question: str, **kw: Any) -> Any:
    from merchant_analyst.runtime import ask_sync  # lazy: needs Gemini key + tool service

    return ask_sync(question, **kw)


def run_goldens(
    case: Case, answer: str, saved: list[dict] | None = None
) -> tuple[list[GoldenResult], list[dict]]:
    """Check each golden; use saved responses (replay) when they match tool+args."""
    results: list[GoldenResult] = []
    responses: list[dict] = []
    for i, g in enumerate(case.golden):
        response = None
        if saved and i < len(saved):
            s = saved[i]
            if s.get("tool") == g.tool and (s.get("args") or {}) == g.args:
                response = s.get("response")
        if response is None:
            try:
                response = golden_mod.call_tool(g)
            except Exception as e:  # noqa: BLE001 - reported per golden, never aborts the run
                results.append(GoldenResult(g.tool, dict(g.args), error=f"{type(e).__name__}: {e}"))
                continue
        results.append(check_golden(answer, g, response=response))
        responses.append({"tool": g.tool, "args": g.args, "response": _plain(response)})
    return results, responses


def evaluate(case: Case, result: Any, duration_s: float | None, saved_goldens=None):
    grounding = check_answer(result.answer, result.tool_calls)
    tools = check_tools(case, result.tool_calls)
    goldens, responses = run_goldens(case, result.answer, saved_goldens)
    rec = build_record(case, result, grounding, goldens, tools, duration_s=duration_s)
    return rec, responses


def run_cases(
    cases: list[Case],
    *,
    replay: bool = False,
    record: bool = False,
    fixtures_dir: Path = DEFAULT_FIXTURES,
    fail_fast: bool = False,
    ask_kwargs: dict[str, Any] | None = None,
    log=print,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for case in cases:
        fixture_path = fixtures_dir / f"{case.id}.json"
        log(f"[{case.id}] {case.question}")
        if replay:
            if not fixture_path.exists():
                log(f"  no fixture at {fixture_path}, skipping")
                records.append(build_record(case, None, None, [], None, status="skip"))
                continue
            result = load_fixture(fixture_path)
            rec, _ = evaluate(case, result, result.duration_s, result.golden_responses)
        else:
            t0 = time.perf_counter()
            try:
                result = _ask(case.question, **(ask_kwargs or {}))
            except Exception as e:  # noqa: BLE001 - an agent failure is an ERROR record
                records.append(
                    build_record(
                        case,
                        None,
                        None,
                        [],
                        None,
                        duration_s=time.perf_counter() - t0,
                        error=f"{type(e).__name__}: {e}",
                    )
                )
                log(f"  ERROR {type(e).__name__}: {e}")
                if fail_fast:
                    break
                continue
            duration = time.perf_counter() - t0
            rec, responses = evaluate(case, result, duration)
            if record:
                fixtures_dir.mkdir(parents=True, exist_ok=True)
                fixture_path.write_text(
                    json.dumps(
                        result_to_fixture(case, result, duration, responses),
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    )
                )
        records.append(rec)
        log(
            f"  {rec['status'].upper()}  grounded {rec['grounding']['grounded_count']}/"
            f"{rec['grounding']['mentions']}"
        )
        for u in rec["grounding"]["ungrounded"]:
            log(f"    ungrounded {u['raw']!r}: {u['context']}")
        if fail_fast and rec["status"] != "pass":
            break
    return records


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m merchant_eval.run", description=__doc__)
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--only", help="comma-separated case ids")
    p.add_argument("--record", action="store_true", help="save each AskResult as a fixture")
    p.add_argument("--replay", action="store_true", help="evaluate saved fixtures, no model calls")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    p.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    p.add_argument("--no-report", action="store_true", help="do not write report files")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.record and args.replay:
        print("--record and --replay are mutually exclusive", file=sys.stderr)
        return 2
    cases = load_cases(args.cases)
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = [w for w in wanted if w not in {c.id for c in cases}]
        if unknown:
            print(f"unknown case ids: {unknown}", file=sys.stderr)
            return 2
        cases = [c for c in cases if c.id in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    records = run_cases(
        cases,
        replay=args.replay,
        record=args.record,
        fixtures_dir=args.fixtures,
        fail_fast=args.fail_fast,
    )
    print()
    print(render_console(records))
    if not args.no_report:
        json_path, md_path = write_reports(
            records,
            args.reports,
            extra={"mode": "replay" if args.replay else "live", "cases_file": str(args.cases)},
        )
        print(f"\nreport: {json_path}\n        {md_path}")
    failed = any(r["status"] in ("fail", "error") for r in records)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
