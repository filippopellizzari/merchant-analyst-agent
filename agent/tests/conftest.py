"""Shared fixtures: an in-process gRPC server with a fake MerchantAnalyst servicer."""

from __future__ import annotations

from concurrent import futures

import grpc
import pytest

from merchant_analyst import tools
from merchant_analyst.client import AnalystClient
from merchant_analyst.pb.merchant.v1 import analyst_pb2, analyst_pb2_grpc

DATASET_START = "2020-11-01"
DATASET_END = "2021-01-31"


def _meta(start: str, end: str, clamped: bool = False) -> analyst_pb2.QueryMeta:
    return analyst_pb2.QueryMeta(
        date_range_applied=analyst_pb2.DateRange(start_date=start, end_date=end),
        clamped=clamped,
        sql_hash="abcdef0123456789",
        bytes_processed=3_000_000_000_000,  # > 2**31: must survive as int
        cache_hit=False,
        table="bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*",
    )


def _clamp(rng: analyst_pb2.DateRange) -> tuple[str, str, bool]:
    start = rng.start_date or DATASET_START
    end = rng.end_date or DATASET_END
    clamped = False
    if start < DATASET_START:
        start, clamped = DATASET_START, True
    if end > DATASET_END:
        end, clamped = DATASET_END, True
    return start, end, clamped


def _validate(rng: analyst_pb2.DateRange, context: grpc.ServicerContext) -> None:
    for value in (rng.start_date, rng.end_date):
        if value and (len(value) != 10 or value[4] != "-" or value[7] != "-"):
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, f"date {value!r} is not ISO YYYY-MM-DD"
            )
    if rng.start_date and rng.end_date and rng.start_date > rng.end_date:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "start_date must be <= end_date")


def _validate_limit(limit: int, context: grpc.ServicerContext) -> None:
    if limit and not (1 <= limit <= 50):
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "limit must be in 1..50")


class FakeAnalyst(analyst_pb2_grpc.MerchantAnalystServicer):
    """Deterministic canned responses; validates arguments like the real service."""

    def GetDatasetInfo(self, request, context):
        return analyst_pb2.DatasetInfo(
            table="bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*",
            available_range=analyst_pb2.DateRange(start_date=DATASET_START, end_date=DATASET_END),
            currency="USD",
            total_events=4_295_584,
            total_sessions=369_000,
            total_purchases=5_692,
            caveats=["item names are obfuscated", "sampled data"],
            meta=_meta(DATASET_START, DATASET_END),
        )

    def GetSalesSummary(self, request, context):
        _validate(request.date_range, context)
        start, end, clamped = _clamp(request.date_range)
        return analyst_pb2.SalesSummary(
            revenue=362_165.123456,
            currency="USD",
            orders=5_692,
            units=27_777,
            purchasers=4_419,
            sessions=369_000,
            purchasing_sessions=5_500,
            average_order_value=63.627,
            conversion_rate=0.0149051,
            meta=_meta(start, end, clamped),
        )

    def GetTopProducts(self, request, context):
        _validate(request.date_range, context)
        _validate_limit(request.limit, context)
        if request.metric not in (
            analyst_pb2.METRIC_UNSPECIFIED,
            analyst_pb2.REVENUE,
            analyst_pb2.UNITS,
            analyst_pb2.ORDERS,
        ):
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "metric must be REVENUE, UNITS or ORDERS"
            )
        start, end, clamped = _clamp(request.date_range)
        metric = request.metric or analyst_pb2.REVENUE
        limit = request.limit or 10
        rows = [
            analyst_pb2.ProductRow(
                rank=i + 1,
                item_name=f"Product {i + 1}",
                item_category="Apparel",
                revenue=1000.556 - i,
                units=100 - i,
                orders=50 - i,
            )
            for i in range(min(limit, 3))
        ]
        return analyst_pb2.TopProducts(
            metric=metric, rows=rows, currency="USD", meta=_meta(start, end, clamped)
        )

    def GetDailyTrend(self, request, context):
        _validate(request.date_range, context)
        start, end, clamped = _clamp(request.date_range)
        metric = request.metric or analyst_pb2.REVENUE
        return analyst_pb2.DailyTrend(
            metric=metric,
            points=[
                analyst_pb2.DailyPoint(date="2020-12-01", value=1234.5678),
                analyst_pb2.DailyPoint(date="2020-12-02", value=2345.6789),
            ],
            total=3580.2467,
            minimum=1234.5678,
            maximum=2345.6789,
            currency="USD" if metric == analyst_pb2.REVENUE else "",
            meta=_meta(start, end, clamped),
        )

    def GetTrafficBySource(self, request, context):
        _validate(request.date_range, context)
        _validate_limit(request.limit, context)
        start, end, clamped = _clamp(request.date_range)
        return analyst_pb2.TrafficBySource(
            rows=[
                analyst_pb2.SourceRow(
                    rank=1,
                    source="google",
                    medium="organic",
                    sessions=150_000,
                    purchasers=2_000,
                    orders=2_500,
                    revenue=150_000.999,
                    conversion_rate=0.016666,
                ),
                analyst_pb2.SourceRow(
                    rank=2,
                    source="(direct)",
                    medium="(none)",
                    sessions=100_000,
                    purchasers=1_000,
                    orders=1_200,
                    revenue=80_000.001,
                    conversion_rate=0.012,
                ),
            ],
            currency="USD",
            meta=_meta(start, end, clamped),
        )

    def GetFunnel(self, request, context):
        _validate(request.date_range, context)
        start, end, clamped = _clamp(request.date_range)
        return analyst_pb2.Funnel(
            steps=[
                analyst_pb2.FunnelStep(
                    event_name="view_item", sessions=100_000, step_rate=1.0, cumulative_rate=1.0
                ),
                analyst_pb3_step("add_to_cart", 20_000, 0.2, 0.2),
                analyst_pb3_step("begin_checkout", 8_000, 0.4, 0.08),
                analyst_pb3_step("purchase", 5_000, 0.625, 0.05),
            ],
            meta=_meta(start, end, clamped),
        )

    def GetGeoBreakdown(self, request, context):
        _validate(request.date_range, context)
        _validate_limit(request.limit, context)
        start, end, clamped = _clamp(request.date_range)
        return analyst_pb2.GeoBreakdown(
            rows=[
                analyst_pb2.GeoRow(
                    rank=1, country="United States", sessions=200_000, orders=4_000, revenue=250_000.0
                ),
                analyst_pb2.GeoRow(
                    rank=2, country="Canada", sessions=20_000, orders=300, revenue=20_000.126
                ),
            ],
            currency="USD",
            meta=_meta(start, end, clamped),
        )


def analyst_pb3_step(name: str, sessions: int, step: float, cum: float) -> analyst_pb2.FunnelStep:
    return analyst_pb2.FunnelStep(
        event_name=name, sessions=sessions, step_rate=step, cumulative_rate=cum
    )


@pytest.fixture(scope="session")
def grpc_address():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    analyst_pb2_grpc.add_MerchantAnalystServicer_to_server(FakeAnalyst(), server)
    port = server.add_insecure_port("localhost:0")
    server.start()
    try:
        yield f"localhost:{port}"
    finally:
        server.stop(grace=None)


@pytest.fixture
def client(grpc_address):
    with AnalystClient(grpc_address, timeout=5.0) as c:
        yield c


@pytest.fixture
def fake_tools(client):
    """Point the module-level tools client at the fake server for the duration of a test."""
    tools.set_client(client)
    try:
        yield tools
    finally:
        tools.set_client(None)
