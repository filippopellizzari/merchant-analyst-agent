"""AnalystClient + tools functions against an in-process fake gRPC server."""

from __future__ import annotations

import grpc
import pytest

from merchant_analyst import tools as tools_module
from merchant_analyst.client import AnalystClient


def test_dataset_info_int64_are_ints(fake_tools):
    info = fake_tools.get_dataset_info()
    assert info["total_events"] == 4_295_584
    assert all(isinstance(info[k], int) for k in ("total_events", "total_sessions", "total_purchases"))
    assert info["available_range"] == {"start_date": "2020-11-01", "end_date": "2021-01-31"}
    assert info["caveats"] == ["item names are obfuscated", "sampled data"]
    assert isinstance(info["meta"]["bytes_processed"], int)
    assert info["meta"]["bytes_processed"] == 3_000_000_000_000


def test_sales_summary_rounding_and_meta(fake_tools):
    s = fake_tools.get_sales_summary("2020-12-01", "2020-12-31")
    assert s["revenue"] == 362_165.12
    assert s["average_order_value"] == 63.63
    assert s["conversion_rate"] == 0.0149
    assert s["orders"] == 5_692 and isinstance(s["orders"], int)
    assert s["currency"] == "USD"
    assert s["meta"]["date_range_applied"] == {"start_date": "2020-12-01", "end_date": "2020-12-31"}
    assert s["meta"]["clamped"] is False
    assert s["meta"]["sql_hash"] == "abcdef0123456789"


def test_sales_summary_clamped_flag(fake_tools):
    s = fake_tools.get_sales_summary("2020-01-01", "2021-12-31")
    assert s["meta"]["clamped"] is True
    assert s["meta"]["date_range_applied"] == {"start_date": "2020-11-01", "end_date": "2021-01-31"}


def test_top_products_enum_names_and_rows(fake_tools):
    tp = fake_tools.get_top_products("2020-12-01", "2020-12-31", metric="units", limit=2)
    assert tp["metric"] == "UNITS"
    assert len(tp["rows"]) == 2
    row = tp["rows"][0]
    assert row == {
        "rank": 1,
        "item_name": "Product 1",
        "item_category": "Apparel",
        "revenue": 1000.56,
        "units": 100,
        "orders": 50,
    }
    assert isinstance(row["units"], int) and isinstance(row["orders"], int)


def test_top_products_default_metric_is_revenue(fake_tools):
    tp = fake_tools.get_top_products("2020-12-01", "2020-12-31")
    assert tp["metric"] == "REVENUE"
    assert len(tp["rows"]) == 3  # fake caps at 3 regardless of default limit 10


def test_daily_trend_points_rounded(fake_tools):
    dt = fake_tools.get_daily_trend("2020-12-01", "2020-12-02", metric="CONVERSION_RATE")
    assert dt["metric"] == "CONVERSION_RATE"
    assert dt["points"] == [
        {"date": "2020-12-01", "value": 1234.57},
        {"date": "2020-12-02", "value": 2345.68},
    ]
    # total/minimum/maximum are not in the rounding list: left as-is
    assert dt["total"] == 3580.2467
    assert dt["currency"] == ""


def test_traffic_by_source(fake_tools):
    tr = fake_tools.get_traffic_by_source("2020-11-01", "2020-11-30", limit=5)
    assert [r["source"] for r in tr["rows"]] == ["google", "(direct)"]
    first = tr["rows"][0]
    assert first["revenue"] == 150_001.0
    assert first["conversion_rate"] == 0.0167
    assert isinstance(first["sessions"], int) and first["sessions"] == 150_000


def test_funnel(fake_tools):
    f = fake_tools.get_funnel("2020-11-01", "2021-01-31")
    names = [s["event_name"] for s in f["steps"]]
    assert names == ["view_item", "add_to_cart", "begin_checkout", "purchase"]
    assert f["steps"][3] == {
        "event_name": "purchase",
        "sessions": 5_000,
        "step_rate": 0.625,
        "cumulative_rate": 0.05,
    }


def test_geo_breakdown(fake_tools):
    g = fake_tools.get_geo_breakdown("2020-11-01", "2021-01-31", limit=2)
    assert g["rows"][1] == {
        "rank": 2,
        "country": "Canada",
        "sessions": 20_000,
        "orders": 300,
        "revenue": 20_000.13,
    }


@pytest.mark.parametrize(
    "call",
    [
        lambda t: t.get_sales_summary("2020/12/01", "2020-12-31"),
        lambda t: t.get_sales_summary("2020-12-31", "2020-12-01"),
        lambda t: t.get_top_products("2020-12-01", "2020-12-31", limit=51),
        lambda t: t.get_top_products("2020-12-01", "2020-12-31", metric="SESSIONS"),
        lambda t: t.get_traffic_by_source("2020-12-01", "2020-12-31", limit=-1),
        lambda t: t.get_funnel("Dec 1", "2020-12-31"),
    ],
)
def test_invalid_argument_returns_error_dict(fake_tools, call):
    result = call(fake_tools)
    assert set(result) == {"error"}
    assert isinstance(result["error"], str) and result["error"]


def test_unknown_metric_name_returns_error_without_rpc(fake_tools):
    result = fake_tools.get_daily_trend("2020-12-01", "2020-12-31", metric="PROFIT")
    assert "error" in result
    assert "PROFIT" in result["error"] and "REVENUE" in result["error"]


def test_other_grpc_errors_raise():
    # Nothing listens here; the call must fail with UNAVAILABLE (not be swallowed).
    tools_module.set_client(AnalystClient("localhost:1", timeout=1.0))
    try:
        with pytest.raises(grpc.RpcError) as excinfo:
            tools_module.get_dataset_info()
        assert excinfo.value.code() in (
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.DEADLINE_EXCEEDED,
        )
    finally:
        tools_module.set_client(None)


def test_client_reads_address_from_env(monkeypatch):
    monkeypatch.setenv("TOOL_SERVICE_ADDRESS", "example.invalid:1234")
    with AnalystClient() as c:
        assert c.address == "example.invalid:1234"
        assert c.timeout == 60.0
    monkeypatch.delenv("TOOL_SERVICE_ADDRESS")
    with AnalystClient() as c:
        assert c.address == "localhost:50051"


def test_get_client_is_lazy_singleton(monkeypatch):
    monkeypatch.setenv("TOOL_SERVICE_ADDRESS", "example.invalid:1")
    tools_module.set_client(None)
    try:
        a = tools_module.get_client()
        assert a is tools_module.get_client()
        assert a.address == "example.invalid:1"
    finally:
        tools_module.set_client(None)
