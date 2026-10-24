import textwrap
from dataclasses import dataclass, field

import pytest

import merchant_eval.golden as golden_mod
from merchant_eval.golden import (
    Case,
    Golden,
    check_golden,
    check_tools,
    load_cases,
    resolve_path,
    value_in_answer,
)


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)


TOP = {
    "metric": "REVENUE",
    "rows": [
        {"rank": 1, "item_name": "Google Hoodie", "revenue": 1234.5, "units": 40},
        {"rank": 2, "item_name": "Mug", "revenue": 600.0, "units": 120},
    ],
    "meta": {"clamped": False},
}
SUMMARY = {"revenue": 98765.43, "orders": 2345, "conversion_rate": 0.0526}
FUNNEL = {
    "steps": [{"event_name": "view_item", "sessions": 1000}] * 3
    + [{"event_name": "purchase", "sessions": 52, "cumulative_rate": 0.052}]
}


@pytest.fixture
def fake_tools(monkeypatch):
    calls = []

    def get_top_products(start_date, end_date, metric="REVENUE", limit=10):
        calls.append(("get_top_products", start_date, end_date, metric, limit))
        return TOP

    def get_sales_summary(start_date, end_date):
        calls.append(("get_sales_summary", start_date, end_date))
        return SUMMARY

    def get_funnel(start_date, end_date):
        return FUNNEL

    monkeypatch.setattr(
        golden_mod,
        "tool_registry",
        {
            "get_top_products": get_top_products,
            "get_sales_summary": get_sales_summary,
            "get_funnel": get_funnel,
        },
    )
    return calls


# --- path resolution ---------------------------------------------------------


def test_resolve_paths():
    assert resolve_path(TOP, "rows[0].item_name") == "Google Hoodie"
    assert resolve_path(TOP, "rows[1].revenue") == 600.0
    assert resolve_path(SUMMARY, "revenue") == 98765.43
    assert resolve_path(FUNNEL, "steps[3].sessions") == 52
    assert resolve_path(FUNNEL, "steps[-1].event_name") == "purchase"
    assert resolve_path(TOP, "meta.clamped") is False


@pytest.mark.parametrize(
    "path", ["rows[9].revenue", "nope", "rows.revenue", "rows[0].x", "rows[a]"]
)
def test_resolve_path_errors(path):
    with pytest.raises(KeyError):
        resolve_path(TOP, path)


# --- value_in_answer -----------------------------------------------------------


@pytest.mark.parametrize(
    "answer,expected,ok",
    [
        ("Revenue: $1,234.50", 1234.5, True),
        ("Revenue: $1,235", 1234.5, True),
        ("Revenue: $1.2k", 1234.5, True),
        ("Revenue: $1,234.51", 1234.5, False),
        ("Revenue: $1,300", 1234.5, False),
        ("2,345 orders", 2345, True),
        ("2,344 orders", 2345, False),
        ("conversion 5.26%", 0.0526, True),
        ("conversion 5.3%", 0.0526, True),
        ("conversion 0.0526", 0.0526, True),
        ("conversion 6%", 0.0526, False),
        ("Top item: the google hoodie!", "Google Hoodie", True),
        ("Top item: the hoodie", "Google Hoodie", False),
    ],
)
def test_value_in_answer(answer, expected, ok):
    assert value_in_answer(answer, expected)[0] is ok


# --- check_golden with injected tools -------------------------------------


def test_check_golden_calls_tool_with_args_and_checks_paths(fake_tools):
    g = Golden(
        tool="get_top_products",
        args={
            "start_date": "2020-12-01",
            "end_date": "2020-12-31",
            "metric": "REVENUE",
            "limit": 5,
        },
        answer_must_contain=["rows[0].item_name", "rows[0].revenue", "rows[1].units"],
    )
    r = check_golden("The Google Hoodie led with $1,234.50; the Mug sold 120 units.", g)
    assert fake_tools == [("get_top_products", "2020-12-01", "2020-12-31", "REVENUE", 5)]
    assert r.ok and [c.ok for c in r.checks] == [True, True, True]
    assert r.checks[0].expected == "Google Hoodie"


def test_check_golden_reports_failed_path(fake_tools):
    g = Golden("get_sales_summary", {"start_date": "a", "end_date": "b"}, ["revenue", "orders"])
    r = check_golden("Revenue was $98,765.43 from 9,999 orders.", g)
    assert not r.ok
    assert [(c.path, c.ok) for c in r.checks] == [("revenue", True), ("orders", False)]


def test_check_golden_bad_path_is_failure_not_crash(fake_tools):
    g = Golden("get_sales_summary", {"start_date": "a", "end_date": "b"}, ["rows[0].revenue"])
    r = check_golden("whatever", g)
    assert not r.ok and r.error is None and r.checks[0].ok is False


def test_check_golden_unknown_tool_is_error(fake_tools):
    r = check_golden("x", Golden("get_moon_phase", {}, ["phase"]))
    assert not r.ok and "get_moon_phase" in r.error


def test_check_golden_tool_error_dict_is_error(monkeypatch):
    monkeypatch.setattr(
        golden_mod, "tool_registry", {"get_top_products": lambda **kw: {"error": "bad metric"}}
    )
    r = check_golden("x", Golden("get_top_products", {"metric": "NOPE"}, ["rows[0].revenue"]))
    assert not r.ok and r.checks == [] and "bad metric" in r.error


def test_check_golden_with_saved_response_does_not_call_tool(fake_tools):
    g = Golden("get_sales_summary", {"start_date": "a", "end_date": "b"}, ["orders"])
    r = check_golden("2,345 orders", g, response=SUMMARY)
    assert r.ok and fake_tools == []


# --- tool expectations -----------------------------------------------------


def test_check_tools_missing_and_forbidden():
    case = Case(
        id="c",
        question="q",
        expect_tools=["get_sales_summary", "get_funnel"],
        forbid_tools=["get_top_products"],
    )
    calls = [ToolCall("get_sales_summary"), ToolCall("get_top_products")]
    te = check_tools(case, calls)
    assert te.missing == ["get_funnel"]
    assert te.forbidden_called == ["get_top_products"]
    assert not te.ok
    assert check_tools(Case(id="c", question="q", expect_tools=["get_sales_summary"]), calls).ok


def test_check_tools_clamped_expectation():
    case = Case(id="c", question="q", expect_tools=["get_sales_summary"], expect_clamped=True)
    not_clamped = [ToolCall("get_sales_summary", {}, {"meta": {"clamped": False}})]
    clamped = [ToolCall("get_sales_summary", {}, {"meta": {"clamped": True}})]
    assert not check_tools(case, not_clamped).ok
    assert check_tools(case, clamped).ok
    assert check_tools(case, clamped).clamped is True


# --- load_cases --------------------------------------------------------------


def test_load_cases(tmp_path):
    p = tmp_path / "cases.yaml"
    p.write_text(
        textwrap.dedent("""
        cases:
          - id: dec_top5
            question: Top 5 products by revenue in December 2020?
            expect_tools: [get_top_products]
            golden:
              - tool: get_top_products
                args: {start_date: "2020-12-01", end_date: "2020-12-31", metric: REVENUE, limit: 5}
                answer_must_contain: ["rows[0].item_name", "rows[0].revenue"]
            notes: ranking
          - id: describe
            question: What data is this?
            expect_tools: [get_dataset_info]
            expect_clamped: false
    """)
    )
    cases = load_cases(p)
    assert [c.id for c in cases] == ["dec_top5", "describe"]
    c = cases[0]
    assert c.golden[0].tool == "get_top_products"
    assert c.golden[0].args["limit"] == 5
    assert c.golden[0].args["metric"] == "REVENUE"
    assert c.golden[0].answer_must_contain == ["rows[0].item_name", "rows[0].revenue"]
    assert c.notes == "ranking" and c.expect_clamped is None
    assert cases[1].golden == [] and cases[1].expect_clamped is False


def test_load_cases_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "cases.yaml"
    p.write_text("cases:\n  - {id: a, question: q}\n  - {id: a, question: q}\n")
    with pytest.raises(ValueError):
        load_cases(p)
