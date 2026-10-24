"""Golden checks: the answer must contain the values a direct tool call returns.

Cases live in ``eval/cases.yaml``. For every ``golden`` entry the named tool is
called with explicit ``args`` (lazily imported from ``merchant_analyst.tools``,
or taken from the injectable ``tool_registry``), each ``answer_must_contain``
path is resolved against the result, and the answer is checked for that value:
numbers through the grounding matcher (so rounding / k-scale / percent
formatting is tolerated), strings as case-insensitive substrings.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from merchant_eval.grounding import SourceNumber, ground
from merchant_eval.numbers import extract_numbers

# Tests (and replay mode) inject fake tool functions here: {"get_top_products": fn}.
# When None, tools are imported from ``merchant_analyst.tools`` on first use.
tool_registry: dict[str, Callable[..., dict]] | None = None


@dataclass
class Golden:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    answer_must_contain: list[str] = field(default_factory=list)


@dataclass
class Case:
    id: str
    question: str
    expect_tools: list[str] = field(default_factory=list)
    forbid_tools: list[str] = field(default_factory=list)
    golden: list[Golden] = field(default_factory=list)
    expect_clamped: bool | None = None
    notes: str | None = None


@dataclass
class GoldenCheck:
    path: str
    expected: Any
    ok: bool
    explanation: str


@dataclass
class GoldenResult:
    tool: str
    args: dict[str, Any]
    checks: list[GoldenCheck] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(c.ok for c in self.checks)


@dataclass
class ToolExpectation:
    expected: list[str]
    forbidden: list[str]
    called: list[str]
    missing: list[str]
    forbidden_called: list[str]
    expect_clamped: bool | None = None
    clamped: bool | None = None

    @property
    def ok(self) -> bool:
        if self.missing or self.forbidden_called:
            return False
        return self.expect_clamped is None or self.clamped is self.expect_clamped


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


def load_cases(path: str | Path) -> list[Case]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    raw_cases = data["cases"] if isinstance(data, dict) else data
    cases: list[Case] = []
    for raw in raw_cases:
        goldens = [
            Golden(
                tool=g["tool"],
                args=dict(g.get("args") or {}),
                answer_must_contain=list(g.get("answer_must_contain") or []),
            )
            for g in raw.get("golden") or []
        ]
        cases.append(
            Case(
                id=str(raw["id"]),
                question=raw["question"],
                expect_tools=list(raw.get("expect_tools") or []),
                forbid_tools=list(raw.get("forbid_tools") or []),
                golden=goldens,
                expect_clamped=raw.get("expect_clamped"),
                notes=raw.get("notes"),
            )
        )
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate case ids: {sorted(dupes)}")
    return cases


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------

_SEGMENT = re.compile(r"([^.\[\]]+)|\[(-?\d+)\]")


def resolve_path(obj: Any, path: str) -> Any:
    """Resolve a tiny JSON path like ``rows[0].item_name`` or ``steps[3].sessions``."""
    pos = 0
    cur = obj
    for m in _SEGMENT.finditer(path):
        if m.start() != pos and path[pos : m.start()] != ".":
            raise KeyError(f"bad path syntax near {path[pos:]!r} in {path!r}")
        pos = m.end()
        key, index = m.group(1), m.group(2)
        if key is not None:
            if not isinstance(cur, dict) or key not in cur:
                raise KeyError(f"{key!r} not found while resolving {path!r}")
            cur = cur[key]
        else:
            if not isinstance(cur, list | tuple):
                raise KeyError(f"index [{index}] on non-list while resolving {path!r}")
            try:
                cur = cur[int(index)]
            except IndexError as e:
                raise KeyError(f"index [{index}] out of range while resolving {path!r}") from e
    if pos != len(path):
        raise KeyError(f"bad path syntax near {path[pos:]!r} in {path!r}")
    return cur


# --------------------------------------------------------------------------
# Tool invocation
# --------------------------------------------------------------------------


def get_tool(name: str) -> Callable[..., dict]:
    if tool_registry is not None:
        if name not in tool_registry:
            raise KeyError(f"tool {name!r} not in tool_registry")
        return tool_registry[name]
    from merchant_analyst import tools  # lazy: the agent package needs gRPC + env

    fn = getattr(tools, name, None)
    if fn is None or not callable(fn):
        raise KeyError(f"tool {name!r} not found in merchant_analyst.tools")
    return fn


def call_tool(golden: Golden) -> dict:
    result = get_tool(golden.tool)(**golden.args)
    if not isinstance(result, dict):
        raise TypeError(f"{golden.tool} returned {type(result).__name__}, expected dict")
    if "error" in result and len(result) == 1:  # tools report bad args as {"error": ...}
        raise RuntimeError(f"{golden.tool} returned error: {result['error']}")
    return result


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def value_in_answer(answer: str, expected: Any, *, label: str = "golden") -> tuple[bool, str]:
    """Is ``expected`` present in ``answer``? Numbers via the grounding matcher."""
    if isinstance(expected, bool) or expected is None:
        return False, f"unsupported golden value {expected!r}"
    if isinstance(expected, int | float):
        source = SourceNumber(
            value=float(expected),
            path=label,
            tool="golden",
            call_index=0,
            is_int=isinstance(expected, int),
            key=label.rsplit(".", 1)[-1],
        )
        for mention in extract_numbers(answer):
            match = ground(mention, [source], max_derivation_depth=0)
            if match:
                return True, match.explanation
        return False, f"no number in the answer matches {expected!r}"
    if isinstance(expected, str):
        if expected.lower() in answer.lower():
            return True, f"{expected!r} found (case-insensitive)"
        return False, f"{expected!r} not found in answer"
    return False, f"unsupported golden value type {type(expected).__name__}"


def check_golden(answer: str, golden: Golden, response: dict | None = None) -> GoldenResult:
    """Call the golden tool (or use ``response``) and verify each path's value."""
    result = GoldenResult(tool=golden.tool, args=dict(golden.args))
    try:
        data = response if response is not None else call_tool(golden)
    except Exception as e:  # noqa: BLE001 - any tool failure is a reportable golden error
        result.error = f"{type(e).__name__}: {e}"
        return result
    for path in golden.answer_must_contain:
        try:
            expected = resolve_path(data, path)
        except KeyError as e:
            result.checks.append(GoldenCheck(path, None, False, str(e)))
            continue
        ok, why = value_in_answer(answer, expected, label=f"{golden.tool}.{path}")
        result.checks.append(GoldenCheck(path, expected, ok, why))
    return result


def check_tools(case: Case, tool_calls: Iterable[Any]) -> ToolExpectation:
    calls = list(tool_calls)
    called = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None) for tc in calls]
    called = [c for c in called if c]
    clamped: bool | None = None
    if calls:
        clamped = False
        for tc in calls:
            resp = tc.get("response") if isinstance(tc, dict) else getattr(tc, "response", None)
            meta = resp.get("meta") if isinstance(resp, dict) else None
            if isinstance(meta, dict) and meta.get("clamped") is True:
                clamped = True
    return ToolExpectation(
        expected=list(case.expect_tools),
        forbidden=list(case.forbid_tools),
        called=called,
        missing=[t for t in case.expect_tools if t not in called],
        forbidden_called=[t for t in case.forbid_tools if t in called],
        expect_clamped=case.expect_clamped,
        clamped=clamped,
    )
