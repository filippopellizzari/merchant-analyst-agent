import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from merchant_eval.golden import Case, Golden, GoldenCheck, GoldenResult, check_tools
from merchant_eval.grounding import check_answer
from merchant_eval.report import build_record, render_console, render_markdown, write_reports


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)


@dataclass
class AskResult:
    question: str
    answer: str
    tool_calls: list
    model: str = "gemini-test"
    events: int = 3


def make_records():
    summary = ToolCall(
        "get_sales_summary",
        {"start_date": "2020-12-01", "end_date": "2020-12-31"},
        {"revenue": 1234.5, "orders": 10, "rows": [], "meta": {"clamped": False}},
    )
    good_case = Case(
        id="dec_totals",
        question="December totals?",
        expect_tools=["get_sales_summary"],
        golden=[Golden("get_sales_summary", {}, ["revenue"])],
    )
    good = AskResult("December totals?", "Revenue was $1,234.50 from 10 orders.", [summary])
    g = check_answer(good.answer, good.tool_calls)
    rec_ok = build_record(
        good_case,
        good,
        g,
        [GoldenResult("get_sales_summary", {}, [GoldenCheck("revenue", 1234.5, True, "ok")])],
        check_tools(good_case, good.tool_calls),
        duration_s=1.234,
    )
    bad_case = Case(id="dec_bad", question="Bad?", expect_tools=["get_sales_summary", "get_funnel"])
    bad = AskResult(
        "Bad?", "Revenue was $1,234.50 and we had 999 returns in the long tail of text.", [summary]
    )
    gb = check_answer(bad.answer, bad.tool_calls)
    rec_bad = build_record(
        bad_case, bad, gb, [], check_tools(bad_case, bad.tool_calls), duration_s=0.5
    )
    rec_err = build_record(
        Case(id="boom", question="?"), None, None, [], None, error="RuntimeError: x"
    )
    return rec_ok, rec_bad, rec_err


def test_build_record_fields():
    rec_ok, rec_bad, rec_err = make_records()
    assert rec_ok["ok"] is True and rec_ok["status"] == "pass"
    assert rec_ok["grounding"]["grounded_count"] == 2
    assert rec_ok["grounding"]["ungrounded"] == []
    assert rec_ok["tool_calls"][0]["name"] == "get_sales_summary"
    assert rec_ok["tool_calls"][0]["rows"] == 0
    assert rec_ok["model"] == "gemini-test" and rec_ok["duration_s"] == 1.234
    assert rec_ok["golden"][0]["checks"][0]["path"] == "revenue"

    assert rec_bad["ok"] is False and rec_bad["status"] == "fail"
    (u,) = rec_bad["grounding"]["ungrounded"]
    assert u["raw"] == "999"
    assert "999 returns" in u["context"] and u["context"].startswith("…")
    assert len(u["context"]) <= 3 + 2 * 30 + 2
    assert rec_bad["tools"]["missing"] == ["get_funnel"]

    assert rec_err["status"] == "error" and rec_err["ok"] is False


def test_write_reports_json_and_markdown(tmp_path):
    recs = make_records()
    ts = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    json_path, md_path = write_reports(recs, tmp_path / "reports", generated_at=ts)
    assert json_path.name == "20261024T120000Z.json" and md_path.name == "20261024T120000Z.md"
    data = json.loads(json_path.read_text())
    assert data["summary"] == {"total": 3, "pass": 1, "fail": 1, "error": 1, "skip": 0}
    assert [c["id"] for c in data["cases"]] == ["dec_totals", "dec_bad", "boom"]
    md = md_path.read_text()
    assert "| dec_totals | OK |" in md
    assert "| dec_bad | FAIL |" in md
    assert "| boom | ERROR |" in md
    assert "999" in md and "missing get_funnel" in md


def test_render_console_plain_text():
    out = render_console(make_records())
    lines = out.splitlines()
    assert lines[0].split()[:3] == ["case", "status", "grounded"]
    assert any(line.startswith("dec_totals") and "OK" in line for line in lines)
    assert any(line.startswith("dec_bad") and "FAIL" in line and "999" in line for line in lines)
    assert "1/3 passed, 1 failed, 1 errors, 0 skipped" in out


def test_render_markdown_skip_status():
    rec = build_record(Case(id="later", question="q"), None, None, [], None, status="skip")
    assert "| later | SKIP |" in render_markdown([rec])
