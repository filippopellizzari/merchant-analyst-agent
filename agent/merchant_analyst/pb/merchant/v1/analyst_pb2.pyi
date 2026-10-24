from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Metric(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    METRIC_UNSPECIFIED: _ClassVar[Metric]
    REVENUE: _ClassVar[Metric]
    ORDERS: _ClassVar[Metric]
    UNITS: _ClassVar[Metric]
    SESSIONS: _ClassVar[Metric]
    PURCHASERS: _ClassVar[Metric]
    CONVERSION_RATE: _ClassVar[Metric]
METRIC_UNSPECIFIED: Metric
REVENUE: Metric
ORDERS: Metric
UNITS: Metric
SESSIONS: Metric
PURCHASERS: Metric
CONVERSION_RATE: Metric

class DateRange(_message.Message):
    __slots__ = ("start_date", "end_date")
    START_DATE_FIELD_NUMBER: _ClassVar[int]
    END_DATE_FIELD_NUMBER: _ClassVar[int]
    start_date: str
    end_date: str
    def __init__(self, start_date: _Optional[str] = ..., end_date: _Optional[str] = ...) -> None: ...

class QueryMeta(_message.Message):
    __slots__ = ("date_range_applied", "clamped", "sql_hash", "bytes_processed", "cache_hit", "table")
    DATE_RANGE_APPLIED_FIELD_NUMBER: _ClassVar[int]
    CLAMPED_FIELD_NUMBER: _ClassVar[int]
    SQL_HASH_FIELD_NUMBER: _ClassVar[int]
    BYTES_PROCESSED_FIELD_NUMBER: _ClassVar[int]
    CACHE_HIT_FIELD_NUMBER: _ClassVar[int]
    TABLE_FIELD_NUMBER: _ClassVar[int]
    date_range_applied: DateRange
    clamped: bool
    sql_hash: str
    bytes_processed: int
    cache_hit: bool
    table: str
    def __init__(self, date_range_applied: _Optional[_Union[DateRange, _Mapping]] = ..., clamped: _Optional[bool] = ..., sql_hash: _Optional[str] = ..., bytes_processed: _Optional[int] = ..., cache_hit: _Optional[bool] = ..., table: _Optional[str] = ...) -> None: ...

class GetDatasetInfoRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DatasetInfo(_message.Message):
    __slots__ = ("table", "available_range", "currency", "total_events", "total_sessions", "total_purchases", "caveats", "meta")
    TABLE_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_RANGE_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    TOTAL_EVENTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SESSIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_PURCHASES_FIELD_NUMBER: _ClassVar[int]
    CAVEATS_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    table: str
    available_range: DateRange
    currency: str
    total_events: int
    total_sessions: int
    total_purchases: int
    caveats: _containers.RepeatedScalarFieldContainer[str]
    meta: QueryMeta
    def __init__(self, table: _Optional[str] = ..., available_range: _Optional[_Union[DateRange, _Mapping]] = ..., currency: _Optional[str] = ..., total_events: _Optional[int] = ..., total_sessions: _Optional[int] = ..., total_purchases: _Optional[int] = ..., caveats: _Optional[_Iterable[str]] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...

class GetSalesSummaryRequest(_message.Message):
    __slots__ = ("date_range",)
    DATE_RANGE_FIELD_NUMBER: _ClassVar[int]
    date_range: DateRange
    def __init__(self, date_range: _Optional[_Union[DateRange, _Mapping]] = ...) -> None: ...

class SalesSummary(_message.Message):
    __slots__ = ("revenue", "currency", "orders", "units", "purchasers", "sessions", "purchasing_sessions", "average_order_value", "conversion_rate", "meta")
    REVENUE_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    ORDERS_FIELD_NUMBER: _ClassVar[int]
    UNITS_FIELD_NUMBER: _ClassVar[int]
    PURCHASERS_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    PURCHASING_SESSIONS_FIELD_NUMBER: _ClassVar[int]
    AVERAGE_ORDER_VALUE_FIELD_NUMBER: _ClassVar[int]
    CONVERSION_RATE_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    revenue: float
    currency: str
    orders: int
    units: int
    purchasers: int
    sessions: int
    purchasing_sessions: int
    average_order_value: float
    conversion_rate: float
    meta: QueryMeta
    def __init__(self, revenue: _Optional[float] = ..., currency: _Optional[str] = ..., orders: _Optional[int] = ..., units: _Optional[int] = ..., purchasers: _Optional[int] = ..., sessions: _Optional[int] = ..., purchasing_sessions: _Optional[int] = ..., average_order_value: _Optional[float] = ..., conversion_rate: _Optional[float] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...

class GetTopProductsRequest(_message.Message):
    __slots__ = ("date_range", "metric", "limit")
    DATE_RANGE_FIELD_NUMBER: _ClassVar[int]
    METRIC_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    date_range: DateRange
    metric: Metric
    limit: int
    def __init__(self, date_range: _Optional[_Union[DateRange, _Mapping]] = ..., metric: _Optional[_Union[Metric, str]] = ..., limit: _Optional[int] = ...) -> None: ...

class ProductRow(_message.Message):
    __slots__ = ("rank", "item_name", "item_category", "revenue", "units", "orders")
    RANK_FIELD_NUMBER: _ClassVar[int]
    ITEM_NAME_FIELD_NUMBER: _ClassVar[int]
    ITEM_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    REVENUE_FIELD_NUMBER: _ClassVar[int]
    UNITS_FIELD_NUMBER: _ClassVar[int]
    ORDERS_FIELD_NUMBER: _ClassVar[int]
    rank: int
    item_name: str
    item_category: str
    revenue: float
    units: int
    orders: int
    def __init__(self, rank: _Optional[int] = ..., item_name: _Optional[str] = ..., item_category: _Optional[str] = ..., revenue: _Optional[float] = ..., units: _Optional[int] = ..., orders: _Optional[int] = ...) -> None: ...

class TopProducts(_message.Message):
    __slots__ = ("metric", "rows", "currency", "meta")
    METRIC_FIELD_NUMBER: _ClassVar[int]
    ROWS_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    metric: Metric
    rows: _containers.RepeatedCompositeFieldContainer[ProductRow]
    currency: str
    meta: QueryMeta
    def __init__(self, metric: _Optional[_Union[Metric, str]] = ..., rows: _Optional[_Iterable[_Union[ProductRow, _Mapping]]] = ..., currency: _Optional[str] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...

class GetDailyTrendRequest(_message.Message):
    __slots__ = ("date_range", "metric")
    DATE_RANGE_FIELD_NUMBER: _ClassVar[int]
    METRIC_FIELD_NUMBER: _ClassVar[int]
    date_range: DateRange
    metric: Metric
    def __init__(self, date_range: _Optional[_Union[DateRange, _Mapping]] = ..., metric: _Optional[_Union[Metric, str]] = ...) -> None: ...

class DailyPoint(_message.Message):
    __slots__ = ("date", "value")
    DATE_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    date: str
    value: float
    def __init__(self, date: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...

class DailyTrend(_message.Message):
    __slots__ = ("metric", "points", "total", "minimum", "maximum", "currency", "meta")
    METRIC_FIELD_NUMBER: _ClassVar[int]
    POINTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    MINIMUM_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    metric: Metric
    points: _containers.RepeatedCompositeFieldContainer[DailyPoint]
    total: float
    minimum: float
    maximum: float
    currency: str
    meta: QueryMeta
    def __init__(self, metric: _Optional[_Union[Metric, str]] = ..., points: _Optional[_Iterable[_Union[DailyPoint, _Mapping]]] = ..., total: _Optional[float] = ..., minimum: _Optional[float] = ..., maximum: _Optional[float] = ..., currency: _Optional[str] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...

class GetTrafficBySourceRequest(_message.Message):
    __slots__ = ("date_range", "limit")
    DATE_RANGE_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    date_range: DateRange
    limit: int
    def __init__(self, date_range: _Optional[_Union[DateRange, _Mapping]] = ..., limit: _Optional[int] = ...) -> None: ...

class SourceRow(_message.Message):
    __slots__ = ("rank", "source", "medium", "sessions", "purchasers", "orders", "revenue", "conversion_rate")
    RANK_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    MEDIUM_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    PURCHASERS_FIELD_NUMBER: _ClassVar[int]
    ORDERS_FIELD_NUMBER: _ClassVar[int]
    REVENUE_FIELD_NUMBER: _ClassVar[int]
    CONVERSION_RATE_FIELD_NUMBER: _ClassVar[int]
    rank: int
    source: str
    medium: str
    sessions: int
    purchasers: int
    orders: int
    revenue: float
    conversion_rate: float
    def __init__(self, rank: _Optional[int] = ..., source: _Optional[str] = ..., medium: _Optional[str] = ..., sessions: _Optional[int] = ..., purchasers: _Optional[int] = ..., orders: _Optional[int] = ..., revenue: _Optional[float] = ..., conversion_rate: _Optional[float] = ...) -> None: ...

class TrafficBySource(_message.Message):
    __slots__ = ("rows", "currency", "meta")
    ROWS_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    rows: _containers.RepeatedCompositeFieldContainer[SourceRow]
    currency: str
    meta: QueryMeta
    def __init__(self, rows: _Optional[_Iterable[_Union[SourceRow, _Mapping]]] = ..., currency: _Optional[str] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...

class GetFunnelRequest(_message.Message):
    __slots__ = ("date_range",)
    DATE_RANGE_FIELD_NUMBER: _ClassVar[int]
    date_range: DateRange
    def __init__(self, date_range: _Optional[_Union[DateRange, _Mapping]] = ...) -> None: ...

class FunnelStep(_message.Message):
    __slots__ = ("event_name", "sessions", "step_rate", "cumulative_rate")
    EVENT_NAME_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    STEP_RATE_FIELD_NUMBER: _ClassVar[int]
    CUMULATIVE_RATE_FIELD_NUMBER: _ClassVar[int]
    event_name: str
    sessions: int
    step_rate: float
    cumulative_rate: float
    def __init__(self, event_name: _Optional[str] = ..., sessions: _Optional[int] = ..., step_rate: _Optional[float] = ..., cumulative_rate: _Optional[float] = ...) -> None: ...

class Funnel(_message.Message):
    __slots__ = ("steps", "meta")
    STEPS_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    steps: _containers.RepeatedCompositeFieldContainer[FunnelStep]
    meta: QueryMeta
    def __init__(self, steps: _Optional[_Iterable[_Union[FunnelStep, _Mapping]]] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...

class GetGeoBreakdownRequest(_message.Message):
    __slots__ = ("date_range", "limit")
    DATE_RANGE_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    date_range: DateRange
    limit: int
    def __init__(self, date_range: _Optional[_Union[DateRange, _Mapping]] = ..., limit: _Optional[int] = ...) -> None: ...

class GeoRow(_message.Message):
    __slots__ = ("rank", "country", "sessions", "orders", "revenue")
    RANK_FIELD_NUMBER: _ClassVar[int]
    COUNTRY_FIELD_NUMBER: _ClassVar[int]
    SESSIONS_FIELD_NUMBER: _ClassVar[int]
    ORDERS_FIELD_NUMBER: _ClassVar[int]
    REVENUE_FIELD_NUMBER: _ClassVar[int]
    rank: int
    country: str
    sessions: int
    orders: int
    revenue: float
    def __init__(self, rank: _Optional[int] = ..., country: _Optional[str] = ..., sessions: _Optional[int] = ..., orders: _Optional[int] = ..., revenue: _Optional[float] = ...) -> None: ...

class GeoBreakdown(_message.Message):
    __slots__ = ("rows", "currency", "meta")
    ROWS_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    META_FIELD_NUMBER: _ClassVar[int]
    rows: _containers.RepeatedCompositeFieldContainer[GeoRow]
    currency: str
    meta: QueryMeta
    def __init__(self, rows: _Optional[_Iterable[_Union[GeoRow, _Mapping]]] = ..., currency: _Optional[str] = ..., meta: _Optional[_Union[QueryMeta, _Mapping]] = ...) -> None: ...
