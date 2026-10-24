"""proto_to_dict on hand-built messages."""

from __future__ import annotations

from merchant_analyst.client import metric_from_name, proto_to_dict
from merchant_analyst.pb.merchant.v1 import analyst_pb2


def test_query_meta_int64_and_bools():
    meta = analyst_pb2.QueryMeta(
        date_range_applied=analyst_pb2.DateRange(start_date="2020-11-01", end_date="2021-01-31"),
        clamped=True,
        sql_hash="0123456789abcdef",
        bytes_processed=2**40,
        cache_hit=True,
        table="t",
    )
    d = proto_to_dict(meta)
    assert d == {
        "date_range_applied": {"start_date": "2020-11-01", "end_date": "2021-01-31"},
        "clamped": True,
        "sql_hash": "0123456789abcdef",
        "bytes_processed": 2**40,
        "cache_hit": True,
        "table": "t",
    }
    assert type(d["bytes_processed"]) is int


def test_defaults_present_and_unset_submessage_omitted():
    d = proto_to_dict(analyst_pb2.SalesSummary())
    assert d["revenue"] == 0.0 and d["orders"] == 0 and d["currency"] == ""
    assert "meta" not in d


def test_enum_name_and_unspecified():
    assert proto_to_dict(analyst_pb2.TopProducts())["metric"] == "METRIC_UNSPECIFIED"
    assert proto_to_dict(analyst_pb2.DailyTrend(metric=analyst_pb2.PURCHASERS))["metric"] == (
        "PURCHASERS"
    )


def test_nested_repeated_rows_rounding():
    tp = analyst_pb2.TopProducts(
        metric=analyst_pb2.ORDERS,
        currency="USD",
        rows=[
            analyst_pb2.ProductRow(
                rank=1, item_name="A", item_category="C", revenue=10.005, units=3, orders=2
            ),
            analyst_pb2.ProductRow(rank=2, item_name="B", revenue=1e9 + 0.129, units=2**35),
        ],
        meta=analyst_pb2.QueryMeta(bytes_processed=7),
    )
    d = proto_to_dict(tp)
    assert d["metric"] == "ORDERS"
    assert d["rows"][0]["revenue"] == round(10.005, 2)
    assert d["rows"][1]["revenue"] == 1_000_000_000.13
    assert d["rows"][1]["units"] == 2**35 and type(d["rows"][1]["units"]) is int
    assert d["rows"][1]["orders"] == 0
    assert d["meta"] == {"clamped": False, "sql_hash": "", "bytes_processed": 7, "cache_hit": False, "table": ""}


def test_rate_fields_four_dp_and_daily_value_two_dp():
    f = analyst_pb2.Funnel(
        steps=[
            analyst_pb2.FunnelStep(
                event_name="purchase", sessions=5, step_rate=0.123456, cumulative_rate=0.0500049
            )
        ]
    )
    step = proto_to_dict(f)["steps"][0]
    assert step["step_rate"] == 0.1235
    assert step["cumulative_rate"] == 0.05

    src = analyst_pb2.SourceRow(conversion_rate=0.01666666, revenue=99.999)
    d = proto_to_dict(src)
    assert d["conversion_rate"] == 0.0167 and d["revenue"] == 100.0

    dt = analyst_pb2.DailyTrend(
        points=[analyst_pb2.DailyPoint(date="2020-12-01", value=3.14159)],
        total=3.14159,
        minimum=3.14159,
        maximum=3.14159,
    )
    d = proto_to_dict(dt)
    assert d["points"] == [{"date": "2020-12-01", "value": 3.14}]
    assert d["total"] == 3.14159  # untouched
    assert d["points"][0].keys() == {"date", "value"}


def test_repeated_strings():
    d = proto_to_dict(analyst_pb2.DatasetInfo(caveats=["a", "b"]))
    assert d["caveats"] == ["a", "b"]
    assert d["total_events"] == 0


def test_metric_from_name():
    assert metric_from_name("revenue") == analyst_pb2.REVENUE
    assert metric_from_name(" Conversion_Rate ") == analyst_pb2.CONVERSION_RATE
    try:
        metric_from_name("PROFIT")
    except ValueError as exc:
        assert "allowed" in str(exc) and "METRIC_UNSPECIFIED" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
