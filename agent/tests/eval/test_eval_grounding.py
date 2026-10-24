"""Matcher tests with hand-built tool calls (duck-typed; no agent import)."""

from dataclasses import dataclass, field

import pytest

from merchant_eval.grounding import (
    SourceNumber,
    check_answer,
    collect_tool_numbers,
    ground,
)
from merchant_eval.numbers import NumberMention, extract_numbers


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)


META = {
    "date_range_applied": {"start_date": "2020-12-01", "end_date": "2020-12-31"},
    "clamped": False,
    "sql_hash": "3f9a1c2b4d5e6f70",
    "bytes_processed": 123456789,
    "cache_hit": True,
    "table": "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*",
}

SUMMARY = ToolCall(
    name="get_sales_summary",
    args={"start_date": "2020-12-01", "end_date": "2020-12-31"},
    response={
        "revenue": 123456.78,
        "currency": "USD",
        "orders": 2345,
        "units": 6789,
        "purchasers": 2100,
        "sessions": 44567,
        "purchasing_sessions": 2345,
        "average_order_value": 52.65,
        "conversion_rate": 0.0526,
        "meta": META,
    },
)

TOP = ToolCall(
    name="get_top_products",
    args={"start_date": "2020-12-01", "end_date": "2020-12-31", "metric": "REVENUE", "limit": 3},
    response={
        "metric": "REVENUE",
        "currency": "USD",
        "rows": [
            {
                "rank": 1,
                "item_name": "Hoodie",
                "item_category": "Apparel",
                "revenue": 1000.0,
                "units": 40,
                "orders": 35,
            },
            {
                "rank": 2,
                "item_name": "Mug",
                "item_category": "Drinkware",
                "revenue": 600.5,
                "units": 120,
                "orders": 100,
            },
            {
                "rank": 3,
                "item_name": "Cap",
                "item_category": "Apparel",
                "revenue": 399.5,
                "units": 30,
                "orders": 28,
            },
        ],
        "meta": META,
    },
)


def mention(value, kind="count", decimals=0, scale=1.0, raw=None):
    return NumberMention(
        raw=raw or str(value),
        value=value,
        kind=kind,
        start=0,
        end=1,
        decimals=decimals,
        scale=scale,
    )


def one(text):
    (m,) = extract_numbers(text)
    return m


# --- collect_tool_numbers -------------------------------------------------


def test_collect_flattens_numeric_leaves_with_paths():
    sources = collect_tool_numbers([SUMMARY, TOP])
    paths = {s.path: s.value for s in sources}
    assert paths["get_sales_summary[0].response.revenue"] == 123456.78
    assert paths["get_sales_summary[0].response.conversion_rate"] == 0.0526
    assert paths["get_top_products[1].response.rows[2].revenue"] == 399.5
    assert paths["get_top_products[1].args.limit"] == 3


def test_collect_excludes_bools_hashes_bytes_dates_and_strings():
    sources = collect_tool_numbers([SUMMARY])
    paths = {s.path for s in sources}
    assert not any("sql_hash" in p or "bytes_processed" in p for p in paths)
    assert not any("clamped" in p or "cache_hit" in p for p in paths)
    assert not any("date_range_applied" in p for p in paths)
    assert not any("currency" in p or "table" in p for p in paths)


def test_collect_adds_structural_row_counts():
    sources = collect_tool_numbers([TOP])
    counts = [s for s in sources if s.kind == "count"]
    assert [(s.path, s.value) for s in counts] == [
        ("get_top_products[0].response.rows.length", 3.0)
    ]


def test_collect_includes_numeric_strings_but_not_date_like():
    tc = ToolCall("x", {}, {"a": "42", "b": "20201201", "c": "2020-12-01", "d": "n/a"})
    assert [(s.path, s.value) for s in collect_tool_numbers([tc])] == [("x[0].response.a", 42.0)]


# --- ground: exact / rounded -----------------------------------------------


def test_exact_int():
    sources = collect_tool_numbers([SUMMARY])
    m = ground(one("2,345 orders"), sources)
    assert m is not None and m.kind == "exact"
    assert m.source_paths == ["get_sales_summary[0].response.orders"]


def test_int_mention_does_not_match_nearby_int():
    sources = collect_tool_numbers([SUMMARY])
    assert ground(one("2,346 orders"), sources) is None


def test_rounded_money():
    sources = collect_tool_numbers([SUMMARY])
    assert ground(one("$123,456.78"), sources).kind == "exact"
    assert ground(one("$123,457"), sources).kind == "rounded"
    assert ground(one("$123,456.8"), sources).kind == "rounded"


def test_more_decimals_than_source_never_matches_unless_equal():
    sources = [SourceNumber(value=52.65, path="aov", tool="t", call_index=0)]
    assert ground(one("$52.650"), sources) is not None
    assert ground(one("$52.651"), sources) is None


def test_money_tolerance_half_cent():
    sources = [SourceNumber(value=52.654, path="aov", tool="t", call_index=0)]
    assert ground(one("$52.65"), sources) is not None
    assert ground(one("$52.66"), sources) is None


# --- ground: percent <-> fraction -----------------------------------------


def test_percent_matches_rate_source():
    sources = collect_tool_numbers([SUMMARY])
    m = ground(one("5.26%"), sources)
    assert m.kind == "percent"
    assert m.source_paths == ["get_sales_summary[0].response.conversion_rate"]
    assert ground(one("5.3%"), sources).kind == "percent"
    assert ground(one("5%"), sources).kind == "percent"
    assert ground(one("5.2%"), sources) is None


def test_fraction_mention_matches_rate_source():
    sources = collect_tool_numbers([SUMMARY])
    assert ground(one("rate 0.0526"), sources).kind == "exact"
    assert ground(one("rate 0.053"), sources).kind == "rounded"


def test_percent_mention_does_not_match_fraction_directly():
    # "0.05%" is not 0.0526 (which is 5.26%)
    sources = [SourceNumber(value=0.0526, path="r", tool="t", call_index=0)]
    assert ground(one("0.05%"), sources) is None


def test_hundred_percent_matches_rate_one():
    sources = [SourceNumber(value=1.0, path="steps[0].step_rate", tool="t", call_index=0)]
    assert ground(one("100%"), sources).kind == "percent"


# --- ground: scale ---------------------------------------------------------


def test_k_scale():
    sources = collect_tool_numbers([SUMMARY])
    m = ground(one("44.6k sessions"), sources)
    assert m.kind == "scale"
    assert m.source_paths == ["get_sales_summary[0].response.sessions"]
    assert ground(one("45k sessions"), sources).kind == "scale"
    assert ground(one("44.5k sessions"), sources) is None
    assert ground(one("$123.5k"), sources).kind == "scale"
    assert ground(one("$0.12M"), sources).kind == "scale"


# --- ground: derivations ---------------------------------------------------


def test_difference_a_minus_b():
    sources = collect_tool_numbers([TOP])
    m = ground(one("$399.50 more"), sources)  # exact match wins first
    assert m.kind == "exact"
    m = ground(one("$600 more"), sources)  # rows[1].revenue 600.5 rounds to 600
    assert m.kind == "rounded"
    m = ground(one("$201 gap"), sources)  # 600.5 - 399.5 = 201
    assert m.kind == "derived" and "−" in m.explanation
    assert set(m.source_paths) == {
        "get_top_products[0].response.rows[1].revenue",
        "get_top_products[0].response.rows[2].revenue",
    }


def test_percent_change():
    a = SourceNumber(value=1000.0, path="nov.revenue", tool="t", call_index=0)
    b = SourceNumber(value=1125.0, path="dec.revenue", tool="t", call_index=1)
    m = ground(one("+12.5%"), [a, b])
    assert m.kind == "derived"
    assert "(b−a)/a" in m.explanation or "(a−b)/b" in m.explanation
    assert ground(one("-11.1%"), [a, b]).kind == "derived"  # (1000-1125)/1125
    assert ground(one("12.6%"), [a, b]) is None


def test_ratio_as_percent_and_plain():
    a = SourceNumber(value=2345.0, path="purchasing_sessions", tool="t", call_index=0)
    b = SourceNumber(value=44567.0, path="sessions", tool="t", call_index=0)
    assert ground(one("5.26%"), [a, b]).kind == "derived"
    assert ground(one("ratio 0.0526"), [a, b]).kind == "derived"
    assert ground(one("19.0 sessions per order"), [a, b]).kind == "derived"


def test_sum_of_siblings():
    sources = collect_tool_numbers([TOP])
    m = ground(one("$2,000 combined"), sources)  # 1000 + 600.5 + 399.5
    assert m.kind == "derived" and "sum" in m.explanation
    assert m.source_paths == ["get_top_products[0].response.rows[*].revenue"]
    m = ground(one("190 units"), sources)  # 40 + 120 + 30
    assert m.kind == "derived"


def test_rate_complement_drop_off():
    tc = ToolCall(
        "get_funnel",
        {},
        {
            "steps": [
                {
                    "event_name": "view_item",
                    "sessions": 1000,
                    "step_rate": 1.0,
                    "cumulative_rate": 1.0,
                },
                {
                    "event_name": "add_to_cart",
                    "sessions": 300,
                    "step_rate": 0.3,
                    "cumulative_rate": 0.3,
                },
                {
                    "event_name": "purchase",
                    "sessions": 52,
                    "step_rate": 0.1733,
                    "cumulative_rate": 0.052,
                },
            ]
        },
    )
    sources = collect_tool_numbers([tc])
    m = ground(one("a drop-off of 82.7%"), sources)  # 1 - 0.1733
    assert m.kind == "derived" and "1 −" in m.explanation
    assert ground(one("70% abandon"), sources).kind == "derived"  # 1 - 0.3
    assert ground(one("lost 700 sessions"), sources).kind == "derived"  # 1000 - 300
    assert ground(one("83% abandon"), sources).kind == "derived"  # rounds from 82.67
    assert ground(one("84% abandon"), sources) is None


def test_sum_pair_and_depth_zero_disables_derivations():
    sources = collect_tool_numbers([TOP])
    assert ground(one("$1,600.50"), sources).kind == "derived"  # 1000 + 600.5
    assert ground(one("$1,600.50"), sources, max_derivation_depth=0) is None


def test_rank_fields_are_not_used_in_derivations():
    tc = ToolCall(
        "get_geo_breakdown",
        {},
        {
            "rows": [
                {"rank": 1, "country": "US", "revenue": 1000.0},
                {"rank": 2, "country": "CA", "revenue": 600.5},
                {"rank": 3, "country": "IN", "revenue": 399.5},
            ]
        },
    )
    sources = collect_tool_numbers([tc])
    # rank 1 + rank 2 = 3 would otherwise "ground" any 3; here 3 is rank 3 / the row count
    assert ground(mention(3.0), sources).kind in ("exact", "structural")
    # rank 2 + rank 3 = 5 must not ground 5
    assert ground(mention(5.0), sources) is None


def test_sums_and_differences_require_like_fields():
    a = SourceNumber(
        value=44567.0,
        path="t[0].response.sessions",
        tool="t",
        call_index=0,
        key="sessions",
        is_int=True,
    )
    b = SourceNumber(
        value=52.65,
        path="t[0].response.average_order_value",
        tool="t",
        call_index=0,
        key="average_order_value",
    )
    assert ground(one("44.5k"), [a, b]) is None  # 44567 - 52.65 is unit nonsense
    # but a ratio within the same object is fine
    assert ground(one("846.5"), [a, b]).kind == "derived"


def test_difference_across_calls_same_field():
    a = SourceNumber(
        value=1000.0, path="s[0].response.revenue", tool="s", call_index=0, key="revenue"
    )
    b = SourceNumber(
        value=1125.0, path="s[1].response.revenue", tool="s", call_index=1, key="revenue"
    )
    m = ground(one("$125"), [a, b])
    assert m.kind == "derived" and "b−a" in m.explanation


# --- ground: structural ----------------------------------------------------


def test_structural_row_count_and_limit():
    sources = collect_tool_numbers([TOP])
    m = ground(one("top 3 products"), sources)
    assert m is not None
    assert m.kind in ("exact", "structural")
    rows_only = ToolCall("get_funnel", {}, {"steps": [{"sessions": 100}] * 4})
    m = ground(mention(4.0), collect_tool_numbers([rows_only]))
    assert m.kind == "structural" and m.source_paths == ["get_funnel[0].response.steps.length"]


def test_large_int_does_not_match_row_count():
    rows_only = ToolCall("x", {}, {"rows": [{"v": 1.5}] * 12})
    assert ground(mention(12.0), collect_tool_numbers([rows_only])) is None


# --- negatives -------------------------------------------------------------


def test_hallucinated_number_is_ungrounded():
    sources = collect_tool_numbers([SUMMARY, TOP])
    assert ground(one("999 orders"), sources) is None
    assert ground(one("$77,777.77"), sources) is None


# --- check_answer ----------------------------------------------------------


def test_check_answer_report():
    answer = (
        "In December 2020 the store made $123,456.78 from 2,345 orders "
        "(conversion 5.26%, AOV $52.65). The top 3 products were Hoodie ($1,000.00), "
        "Mug ($600.50) and Cap ($399.50). Together they made $2,000. "
        "Hallucinated: 999 refunds."
    )
    rep = check_answer(answer, [SUMMARY, TOP])
    assert len(rep.mentions) == 10
    assert [m.raw for m in rep.ungrounded] == ["999"]
    assert len(rep.grounded) == 9
    assert not rep.ok
    assert rep.grounded[0][1].kind == "exact"


def test_check_answer_no_tools_everything_ungrounded():
    rep = check_answer("Next month will be $50,000.", [])
    assert [m.raw for m in rep.ungrounded] == ["$50,000"]
    assert not rep.ok


def test_check_answer_no_numbers_is_ok():
    rep = check_answer("The dataset covers the Google Merchandise Store.", [])
    assert rep.ok and rep.mentions == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$123,456.78", True),
        ("$123.46k", True),
        ("5.26%", True),
        ("2,345", True),
        ("3", True),  # limit / row count
        ("$1,600.50", True),  # derived sum
        ("$123,500", False),
        ("12", False),
    ],
)
def test_matrix(text, expected):
    rep = check_answer(f"value {text} end", [SUMMARY, TOP])
    assert rep.ok is expected, rep
