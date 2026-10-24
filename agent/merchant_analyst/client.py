"""Thin gRPC client for the MerchantAnalyst tool service plus proto -> dict conversion."""

from __future__ import annotations

import os
from typing import Any, Self

import grpc
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import Message

from merchant_analyst.pb.merchant.v1 import analyst_pb2, analyst_pb2_grpc

DEFAULT_ADDRESS = "localhost:50051"
DEFAULT_TIMEOUT_S = 60.0

# Field-name based rounding (keys are proto field names).
MONEY_FIELDS = frozenset({"revenue", "average_order_value"})
RATE_FIELDS = frozenset({"conversion_rate", "step_rate", "cumulative_rate"})
DAILY_VALUE_FIELDS = frozenset({"value"})  # DailyPoint.value

_FLOAT_TYPES = (FieldDescriptor.TYPE_DOUBLE, FieldDescriptor.TYPE_FLOAT)


def _is_repeated(field: FieldDescriptor) -> bool:
    # protobuf >= 6 exposes `is_repeated`; `label` was removed from the upb descriptor in 7.x.
    is_repeated = getattr(field, "is_repeated", None)
    if is_repeated is not None:
        return bool(is_repeated)
    return getattr(field, "label", None) == getattr(FieldDescriptor, "LABEL_REPEATED", 3)


def _round_float(field_name: str, value: float) -> float:
    if field_name in MONEY_FIELDS or field_name in DAILY_VALUE_FIELDS:
        return round(value, 2)
    if field_name in RATE_FIELDS:
        return round(value, 4)
    return value


def _convert_scalar(field: FieldDescriptor, value: Any) -> Any:
    if field.type == FieldDescriptor.TYPE_ENUM:
        enum_value = field.enum_type.values_by_number.get(value)
        return enum_value.name if enum_value is not None else int(value)
    if field.type in _FLOAT_TYPES:
        return _round_float(field.name, float(value))
    if field.type == FieldDescriptor.TYPE_BYTES:
        return bytes(value)
    # int32/int64/uint*/sint*/fixed*/bool/string: Python protobuf already yields the
    # native type (int64 is an `int`, never a string).
    return value


def proto_to_dict(msg: Message) -> dict[str, Any]:
    """Convert a protobuf message into plain Python types.

    - Keys are proto field names (snake_case).
    - int64 fields are Python ``int`` (unlike ``MessageToDict``, which stringifies them).
    - Enums become their symbolic names (``"REVENUE"``).
    - Money fields (``revenue``, ``average_order_value``) are rounded to 2 dp, rate fields
      (``conversion_rate``, ``step_rate``, ``cumulative_rate``) to 4 dp, ``value`` of daily
      points to 2 dp; other floats are left untouched.
    - Scalar fields are always present (proto3 defaults included); unset singular
      sub-messages are omitted; repeated fields become lists.
    """
    out: dict[str, Any] = {}
    for field in msg.DESCRIPTOR.fields:
        if _is_repeated(field):
            values = getattr(msg, field.name)
            if field.type == FieldDescriptor.TYPE_MESSAGE:
                if field.message_type.GetOptions().map_entry:
                    out[field.name] = {
                        k: proto_to_dict(v) if isinstance(v, Message) else v
                        for k, v in values.items()
                    }
                else:
                    out[field.name] = [proto_to_dict(v) for v in values]
            else:
                out[field.name] = [_convert_scalar(field, v) for v in values]
        elif field.type == FieldDescriptor.TYPE_MESSAGE:
            if msg.HasField(field.name):
                out[field.name] = proto_to_dict(getattr(msg, field.name))
        else:
            out[field.name] = _convert_scalar(field, getattr(msg, field.name))
    return out


def date_range(start_date: str | None, end_date: str | None) -> analyst_pb2.DateRange:
    return analyst_pb2.DateRange(start_date=start_date or "", end_date=end_date or "")


def metric_from_name(metric: str) -> int:
    """Map a metric name (case-insensitive) to the ``Metric`` enum value.

    Raises ``ValueError`` listing the allowed names when the metric is unknown.
    """
    name = (metric or "").strip().upper()
    try:
        return analyst_pb2.Metric.Value(name)
    except ValueError:
        allowed = [
            v.name for v in analyst_pb2.Metric.DESCRIPTOR.values if v.name != "METRIC_UNSPECIFIED"
        ]
        raise ValueError(f"unknown metric {metric!r}; allowed: {', '.join(allowed)}") from None


class AnalystClient:
    """Blocking gRPC client for ``merchant.v1.MerchantAnalyst``.

    Address comes from ``TOOL_SERVICE_ADDRESS`` (default ``localhost:50051``). Every call
    uses ``timeout`` seconds. Use as a context manager or call ``close()``.
    """

    def __init__(
        self,
        address: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        channel: grpc.Channel | None = None,
    ) -> None:
        self.address = address or os.environ.get("TOOL_SERVICE_ADDRESS", DEFAULT_ADDRESS)
        self.timeout = timeout
        self._channel = channel or grpc.insecure_channel(self.address)
        self._stub = analyst_pb2_grpc.MerchantAnalystStub(self._channel)

    # -- lifecycle -----------------------------------------------------------------------
    def close(self) -> None:
        self._channel.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- RPCs ------------------------------------------------------------------------------
    def get_dataset_info(self) -> analyst_pb2.DatasetInfo:
        return self._stub.GetDatasetInfo(analyst_pb2.GetDatasetInfoRequest(), timeout=self.timeout)

    def get_sales_summary(self, start_date: str, end_date: str) -> analyst_pb2.SalesSummary:
        req = analyst_pb2.GetSalesSummaryRequest(date_range=date_range(start_date, end_date))
        return self._stub.GetSalesSummary(req, timeout=self.timeout)

    def get_top_products(
        self, start_date: str, end_date: str, metric: str = "REVENUE", limit: int = 10
    ) -> analyst_pb2.TopProducts:
        req = analyst_pb2.GetTopProductsRequest(
            date_range=date_range(start_date, end_date),
            metric=metric_from_name(metric),
            limit=limit,
        )
        return self._stub.GetTopProducts(req, timeout=self.timeout)

    def get_daily_trend(
        self, start_date: str, end_date: str, metric: str = "REVENUE"
    ) -> analyst_pb2.DailyTrend:
        req = analyst_pb2.GetDailyTrendRequest(
            date_range=date_range(start_date, end_date), metric=metric_from_name(metric)
        )
        return self._stub.GetDailyTrend(req, timeout=self.timeout)

    def get_traffic_by_source(
        self, start_date: str, end_date: str, limit: int = 10
    ) -> analyst_pb2.TrafficBySource:
        req = analyst_pb2.GetTrafficBySourceRequest(
            date_range=date_range(start_date, end_date), limit=limit
        )
        return self._stub.GetTrafficBySource(req, timeout=self.timeout)

    def get_funnel(self, start_date: str, end_date: str) -> analyst_pb2.Funnel:
        req = analyst_pb2.GetFunnelRequest(date_range=date_range(start_date, end_date))
        return self._stub.GetFunnel(req, timeout=self.timeout)

    def get_geo_breakdown(
        self, start_date: str, end_date: str, limit: int = 10
    ) -> analyst_pb2.GeoBreakdown:
        req = analyst_pb2.GetGeoBreakdownRequest(
            date_range=date_range(start_date, end_date), limit=limit
        )
        return self._stub.GetGeoBreakdown(req, timeout=self.timeout)
