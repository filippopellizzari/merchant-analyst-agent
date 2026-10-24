"""Ground numbers mentioned in an answer in the tool results that produced it.

Inputs are duck-typed: any object (or dict) with ``name``, ``args`` and
``response`` works, so the matcher runs offline against hand-built tool calls
and against ``merchant_analyst.runtime.ToolCall`` alike.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from merchant_eval.numbers import NumberMention, extract_numbers

# Leaves that are provenance, not data: the agent is not expected to quote them.
EXCLUDED_KEYS = frozenset({"sql_hash", "bytes_processed"})
# Fields that are never combined arithmetically (rank 2 + rank 3 = 5 is noise).
NON_DERIVABLE_KEYS = frozenset({"rank"})
# Pairwise derivations consider all source pairs up to this many sources; above
# it only pairs from the same tool call are tried.
PAIRWISE_CAP = 400
# Small integers may be grounded by a list length (rows, steps, points).
STRUCTURAL_MAX = 10
_EPS = 1e-9
_NUMERIC_STRING = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class SourceNumber:
    """One numeric leaf of a tool call, labelled with a JSON path."""

    value: float
    path: str
    tool: str
    call_index: int
    kind: str = "value"  # "value" (response leaf) | "arg" (tool argument) | "count" (list length)
    is_int: bool = False
    key: str = ""


@dataclass
class Match:
    kind: str  # exact | rounded | percent | scale | structural | derived
    explanation: str
    source_paths: list[str]


@dataclass
class GroundingReport:
    mentions: list[NumberMention]
    grounded: list[tuple[NumberMention, Match]] = field(default_factory=list)
    ungrounded: list[NumberMention] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.ungrounded


# --------------------------------------------------------------------------
# Collecting sources
# --------------------------------------------------------------------------


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_date_like_string(s: str) -> bool:
    return len(s) == 8 and s[:2] in ("19", "20")


def _walk(node: Any, path: str, key: str, tool: str, idx: int, kind: str, out: list[SourceNumber]):
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        out.append(
            SourceNumber(
                value=float(node),
                path=path,
                tool=tool,
                call_index=idx,
                kind=kind,
                is_int=isinstance(node, int),
                key=key,
            )
        )
    elif isinstance(node, str):
        if _NUMERIC_STRING.fullmatch(node) and not _is_date_like_string(node):
            v = float(node)
            out.append(
                SourceNumber(
                    value=v,
                    path=path,
                    tool=tool,
                    call_index=idx,
                    kind=kind,
                    is_int=v.is_integer() and "." not in node,
                    key=key,
                )
            )
    elif isinstance(node, dict):
        for k, v in node.items():
            if k in EXCLUDED_KEYS:
                continue
            _walk(v, f"{path}.{k}", k, tool, idx, kind, out)
    elif isinstance(node, list | tuple):
        if kind == "value":
            out.append(
                SourceNumber(
                    value=float(len(node)),
                    path=f"{path}.length",
                    tool=tool,
                    call_index=idx,
                    kind="count",
                    is_int=True,
                    key=key,
                )
            )
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", key, tool, idx, kind, out)


def collect_tool_numbers(tool_calls: Iterable[Any]) -> list[SourceNumber]:
    """Flatten every numeric leaf of every tool call (args and response)."""
    out: list[SourceNumber] = []
    for idx, tc in enumerate(tool_calls):
        name = _get(tc, "name", "tool")
        prefix = f"{name}[{idx}]"
        args = _get(tc, "args") or {}
        response = _get(tc, "response")
        if isinstance(args, dict):
            _walk(args, f"{prefix}.args", "", name, idx, "arg", out)
        if isinstance(response, dict | list):
            _walk(response, f"{prefix}.response", "", name, idx, "value", out)
    return out


# --------------------------------------------------------------------------
# Comparison helpers
# --------------------------------------------------------------------------


def _rounds_to(candidate: float, target: float, decimals: int) -> bool:
    """True when ``candidate`` rounded to ``decimals`` places equals ``target``."""
    return abs(candidate - target) <= 0.5 * 10.0 ** (-decimals) + _EPS


def _same(candidate: float, mention: NumberMention, *, ints_only: bool = False) -> str | None:
    """Return 'exact'/'rounded' when ``candidate`` is what the mention displays."""
    if abs(candidate - mention.value) <= _EPS:
        return "exact"
    if ints_only and mention.is_integer:
        return None
    if mention.scale != 1.0:
        ok = _rounds_to(candidate / mention.scale, mention.value / mention.scale, mention.decimals)
    else:
        ok = _rounds_to(candidate, mention.value, mention.decimals)
    return "rounded" if ok else None


def _percent_same(candidate_rate: float, mention: NumberMention) -> bool:
    """Percent mention vs a fraction source, checked in both directions."""
    if mention.scale != 1.0:
        return False
    as_pct = candidate_rate * 100.0
    if _rounds_to(as_pct, mention.value, mention.decimals):
        return True
    return _rounds_to(candidate_rate, mention.value / 100.0, mention.decimals + 2)


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# --------------------------------------------------------------------------
# Matching strategies
# --------------------------------------------------------------------------


def _match_direct(mention: NumberMention, sources: list[SourceNumber]) -> Match | None:
    if mention.kind == "percent":
        return None
    for s in sources:
        if s.kind == "count":
            continue
        how = _same(s.value, mention, ints_only=s.is_int)
        if how:
            if mention.scale != 1.0 and how == "rounded":
                how = "scale"
            label = "tool arg " if s.kind == "arg" else ""
            return Match(how, f"{mention.raw} = {label}{_fmt(s.value)} ({s.path})", [s.path])
    return None


def _match_percent(mention: NumberMention, sources: list[SourceNumber]) -> Match | None:
    if mention.kind != "percent":
        return None
    for s in sources:
        if s.kind == "count":
            continue
        if _percent_same(s.value, mention):
            return Match("percent", f"{mention.raw} = {_fmt(s.value)} × 100 ({s.path})", [s.path])
    return None


def _match_structural(mention: NumberMention, sources: list[SourceNumber]) -> Match | None:
    if not mention.is_integer or not 0 <= mention.value <= STRUCTURAL_MAX:
        return None
    for s in sources:
        if s.kind == "count" and s.value == mention.value:
            return Match(
                "structural", f"{mention.raw} = number of items in {s.path[:-7]}", [s.path]
            )
    return None


def _generalize(path: str) -> str:
    head, _, rest = path.partition(".")
    return head + "." + re.sub(r"\[\d+\]", "[*]", rest)


def _parent(path: str) -> str:
    return path.rsplit(".", 1)[0]


def _derived_candidates(sources: list[SourceNumber]):
    """Yield (value, explanation, paths, ints_only, op) for depth-1 derivations.

    ``op`` is one of ``sum``, ``diff``, ``ratio``, ``change`` and decides which
    mention kinds the candidate may explain.
    """
    base = [s for s in sources if s.kind == "value" and s.key not in NON_DERIVABLE_KEYS]

    # Aggregates over same-path siblings (rows[*].revenue).
    groups: dict[str, list[SourceNumber]] = {}
    for s in base:
        g = _generalize(s.path)
        if g != s.path:
            groups.setdefault(g, []).append(s)
    for g, members in groups.items():
        if len(members) < 2:
            continue
        total = sum(m.value for m in members)
        ints = all(m.is_int for m in members)
        yield total, f"sum of {g} ({len(members)} items)", [g], ints, "sum"
        yield total / len(members), f"mean of {g} ({len(members)} items)", [g], False, "sum"

    # Complement of a rate: drop-off 94.8% = 1 − 0.052 (step_rate / conversion_rate).
    for s in base:
        if s.key.endswith("rate") and 0.0 <= s.value <= 1.0:
            yield 1.0 - s.value, f"1 − {_fmt(s.value)} ({s.path})", [s.path], False, "ratio"

    if len(base) > PAIRWISE_CAP:
        pairs = (
            (a, b)
            for a, b in itertools.combinations(base, 2)
            if (a.tool, a.call_index) == (b.tool, b.call_index)
        )
    else:
        pairs = itertools.combinations(base, 2)
    for a, b in pairs:
        # Unit coherence: sums/differences only between like fields (revenue −
        # revenue); ratios also within one object (revenue / orders).
        same_key = a.key == b.key
        same_parent = _parent(a.path) == _parent(b.path)
        if not (same_key or same_parent):
            continue
        av, bv = a.value, b.value
        ab = f"a={_fmt(av)} ({a.path}), b={_fmt(bv)} ({b.path})"
        ints = a.is_int and b.is_int
        if same_key:
            yield av + bv, f"a+b with {ab}", [a.path, b.path], ints, "sum"
            yield av - bv, f"a−b with {ab}", [a.path, b.path], ints, "diff"
            yield bv - av, f"b−a with {ab}", [a.path, b.path], ints, "diff"
        if bv:
            yield av / bv, f"a/b with {ab}", [a.path, b.path], False, "ratio"
            yield (av - bv) / bv, f"(a−b)/b with {ab}", [a.path, b.path], False, "change"
        if av:
            yield bv / av, f"b/a with {ab}", [a.path, b.path], False, "ratio"
            yield (bv - av) / av, f"(b−a)/a with {ab}", [a.path, b.path], False, "change"


def _match_derived(mention: NumberMention, sources: list[SourceNumber]) -> Match | None:
    for value, how, paths, ints_only, op in _derived_candidates(sources):
        if mention.kind == "percent":
            if op in ("ratio", "change") and _percent_same(value, mention):
                return Match("derived", f"{mention.raw} = {how} (as percent)", paths)
            if op == "diff" and _same(value * 100.0, mention):
                return Match("derived", f"{mention.raw} = ({how}) × 100 (percentage points)", paths)
            continue
        if op == "change":
            continue  # percent change only explains percent mentions
        if _same(value, mention, ints_only=ints_only):
            return Match("derived", f"{mention.raw} = {how}", paths)
    return None


def ground(
    mention: NumberMention, sources: list[SourceNumber], *, max_derivation_depth: int = 1
) -> Match | None:
    """Find the first source (or derivation of sources) that explains ``mention``.

    Strategies, in order: exact/rounded (incl. tool args), percent <-> rate,
    k/M scale, structural (list lengths for 0..10), depth-1 derivations.
    ``max_derivation_depth=0`` disables derivations; deeper than 1 is not
    implemented and behaves like 1.
    """
    for strategy in (_match_direct, _match_percent, _match_structural):
        m = strategy(mention, sources)
        if m:
            return m
    if max_derivation_depth >= 1:
        return _match_derived(mention, sources)
    return None


def check_answer(
    answer: str, tool_calls: Iterable[Any], *, max_derivation_depth: int = 1
) -> GroundingReport:
    """Extract every number in ``answer`` and ground it in ``tool_calls``."""
    sources = collect_tool_numbers(list(tool_calls))
    report = GroundingReport(mentions=extract_numbers(answer))
    for mention in report.mentions:
        match = ground(mention, sources, max_derivation_depth=max_derivation_depth)
        if match:
            report.grounded.append((mention, match))
        else:
            report.ungrounded.append(mention)
    return report
