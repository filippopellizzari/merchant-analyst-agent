"""Per-case records, JSON + markdown reports and a plain-text console table."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from merchant_eval.golden import Case, GoldenResult, ToolExpectation
from merchant_eval.grounding import GroundingReport
from merchant_eval.numbers import NumberMention

CONTEXT_CHARS = 30


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def context(answer: str, mention: NumberMention, width: int = CONTEXT_CHARS) -> str:
    """The mention with up to ``width`` chars on either side, newlines flattened."""
    lo, hi = max(0, mention.start - width), min(len(answer), mention.end + width)
    snippet = answer[lo:hi].replace("\n", " ")
    return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(answer) else "")


def summarize_tool_call(tc: Any) -> dict[str, Any]:
    name, args, resp = _get(tc, "name"), _get(tc, "args") or {}, _get(tc, "response")
    summary: dict[str, Any] = {"name": name, "args": args}
    if isinstance(resp, dict):
        for key in ("rows", "points", "steps"):
            if isinstance(resp.get(key), list):
                summary[key] = len(resp[key])
        meta = resp.get("meta")
        if isinstance(meta, dict):
            summary["date_range_applied"] = meta.get("date_range_applied")
            summary["clamped"] = meta.get("clamped")
        if "error" in resp:
            summary["error"] = resp["error"]
    else:
        summary["response_type"] = type(resp).__name__
    return summary


def build_record(
    case: Case,
    result: Any | None,
    grounding: GroundingReport | None,
    golden_results: Iterable[GoldenResult],
    tool_expectation: ToolExpectation | None,
    *,
    duration_s: float | None = None,
    error: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """One JSON-serialisable record per case. ``status`` is pass/fail/error/skip."""
    goldens = list(golden_results)
    answer = _get(result, "answer", "") or ""
    tool_calls = list(_get(result, "tool_calls", None) or [])
    grounding_ok = grounding.ok if grounding else False
    golden_ok = all(g.ok for g in goldens)
    tools_ok = tool_expectation.ok if tool_expectation else True
    if status is None:
        if error:
            status = "error"
        else:
            status = "pass" if (grounding_ok and golden_ok and tools_ok) else "fail"
    ok = status == "pass"
    rec: dict[str, Any] = {
        "id": case.id,
        "question": case.question,
        "status": status,
        "ok": ok,
        "notes": case.notes,
        "grounding": None,
        "golden": [
            {
                "tool": g.tool,
                "args": g.args,
                "ok": g.ok,
                "error": g.error,
                "checks": [asdict(c) for c in g.checks],
            }
            for g in goldens
        ],
        "tools": None,
        "tool_calls": [summarize_tool_call(tc) for tc in tool_calls],
        "answer": answer,
        "model": _get(result, "model"),
        "events": _get(result, "events"),
        "duration_s": round(duration_s, 3) if duration_s is not None else None,
        "error": error,
    }
    if grounding is not None:
        rec["grounding"] = {
            "ok": grounding.ok,
            "mentions": len(grounding.mentions),
            "grounded_count": len(grounding.grounded),
            "ungrounded": [
                {
                    "raw": m.raw,
                    "value": m.value,
                    "kind": m.kind,
                    "start": m.start,
                    "end": m.end,
                    "context": context(answer, m),
                }
                for m in grounding.ungrounded
            ],
            "grounded": [
                {
                    "raw": m.raw,
                    "kind": m.kind,
                    "match": match.kind,
                    "explanation": match.explanation,
                    "sources": match.source_paths,
                }
                for m, match in grounding.grounded
            ],
        }
    if tool_expectation is not None:
        rec["tools"] = {**asdict(tool_expectation), "ok": tool_expectation.ok}
    return rec


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _cell_grounding(rec: dict[str, Any]) -> str:
    g = rec.get("grounding")
    if not g:
        return "-"
    return f"{g['grounded_count']}/{g['mentions']}"


def _cell_golden(rec: dict[str, Any]) -> str:
    gs = rec.get("golden") or []
    if not gs:
        return "-"
    checks = [c for g in gs for c in g["checks"]]
    errors = sum(1 for g in gs if g["error"])
    txt = f"{sum(1 for c in checks if c['ok'])}/{len(checks)}"
    return txt + (f" ({errors} err)" if errors else "")


def _cell_tools(rec: dict[str, Any]) -> str:
    t = rec.get("tools")
    if not t:
        return "-"
    parts = []
    if t["missing"]:
        parts.append("missing " + ",".join(t["missing"]))
    if t["forbidden_called"]:
        parts.append("forbidden " + ",".join(t["forbidden_called"]))
    if t.get("expect_clamped") is not None and t.get("clamped") is not t.get("expect_clamped"):
        parts.append(f"clamped={t.get('clamped')}")
    return "; ".join(parts) if parts else "ok"


def _status_label(rec: dict[str, Any]) -> str:
    return {"pass": "OK", "fail": "FAIL", "error": "ERROR", "skip": "SKIP"}.get(
        rec["status"], rec["status"].upper()
    )


def _rows(records: Iterable[dict[str, Any]]) -> list[list[str]]:
    rows = []
    for rec in records:
        ungrounded = ", ".join(u["raw"] for u in (rec.get("grounding") or {}).get("ungrounded", []))
        if rec.get("error"):
            ungrounded = (ungrounded + "; " if ungrounded else "") + f"error: {rec['error']}"
        dur = rec.get("duration_s")
        rows.append(
            [
                rec["id"],
                _status_label(rec),
                _cell_grounding(rec),
                ungrounded[:80],
                _cell_golden(rec),
                _cell_tools(rec),
                f"{dur:.1f}s" if isinstance(dur, int | float) else "-",
            ]
        )
    return rows


HEADERS = ["case", "status", "grounded", "ungrounded", "golden", "tools", "time"]


def summary_counts(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    recs = list(records)
    counts = {"total": len(recs), "pass": 0, "fail": 0, "error": 0, "skip": 0}
    for r in recs:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def render_console(records: Iterable[dict[str, Any]]) -> str:
    recs = list(records)
    rows = [HEADERS] + _rows(recs)
    widths = [max(len(r[i]) for r in rows) for i in range(len(HEADERS))]
    lines = []
    for n, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    c = summary_counts(recs)
    lines.append("")
    lines.append(
        f"{c['pass']}/{c['total']} passed, {c['fail']} failed, {c['error']} errors, "
        f"{c['skip']} skipped"
    )
    return "\n".join(lines)


def render_markdown(records: Iterable[dict[str, Any]], generated_at: str | None = None) -> str:
    recs = list(records)
    c = summary_counts(recs)
    out = ["# Merchant analyst eval report", ""]
    if generated_at:
        out.append(f"Generated: {generated_at}  ")
    out.append(
        f"Result: **{c['pass']}/{c['total']} passed**, {c['fail']} failed, "
        f"{c['error']} errors, {c['skip']} skipped"
    )
    out += ["", "| " + " | ".join(HEADERS) + " |", "|" + "---|" * len(HEADERS)]
    for row in _rows(recs):
        out.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    failing = [r for r in recs if r["status"] in ("fail", "error")]
    if failing:
        out += ["", "## Failures", ""]
        for r in failing:
            out.append(f"### {r['id']} - {_status_label(r)}")
            out.append("")
            out.append(f"Q: {r['question']}")
            out.append("")
            if r.get("error"):
                out.append(f"- error: `{r['error']}`")
            for u in (r.get("grounding") or {}).get("ungrounded", []):
                out.append(f"- ungrounded `{u['raw']}` ({u['kind']}): …{u['context']}…")
            for g in r.get("golden") or []:
                if g["error"]:
                    out.append(f"- golden {g['tool']} error: `{g['error']}`")
                for ch in g["checks"]:
                    if not ch["ok"]:
                        out.append(
                            f"- golden {g['tool']} `{ch['path']}` = `{ch['expected']!r}`: "
                            f"{ch['explanation']}"
                        )
            t = r.get("tools") or {}
            if t and not t.get("ok", True):
                out.append(
                    f"- tools: {_cell_tools(r)} (called: {', '.join(t['called']) or 'none'})"
                )
            out.append("")
    return "\n".join(out) + "\n"


def write_reports(
    records: Iterable[dict[str, Any]],
    reports_dir: str | Path,
    *,
    generated_at: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write ``<UTC timestamp>.json`` and ``.md`` into ``reports_dir``."""
    recs = list(records)
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = generated_at or datetime.now(UTC)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_at": ts.isoformat(),
        "summary": summary_counts(recs),
        **(extra or {}),
        "cases": recs,
    }
    json_path = reports_dir / f"{stamp}.json"
    md_path = reports_dir / f"{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    md_path.write_text(render_markdown(recs, generated_at=ts.isoformat()))
    return json_path, md_path
