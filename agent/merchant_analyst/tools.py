"""ADK tool functions for the merchant analyst.

Each function is a plain Python callable; ADK turns the signature and docstring into a
Gemini function declaration, so the docstrings are the model-facing contract.

Shared definitions (all RPCs run fixed SQL over the public GA4 Google Merchandise Store
sample, bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*):

- Dataset window: 2020-11-01 to 2021-01-31 inclusive. Dates are ISO ``YYYY-MM-DD``.
  Ranges that partially overlap the window are clamped by the server; the response ``meta``
  then has ``clamped: true`` and ``date_range_applied`` shows the range actually used.
  Ranges entirely outside the window are rejected and the tool returns ``{"error": ...}``.
- revenue: sum of ecommerce purchase revenue in USD on purchase events.
- orders: number of distinct transaction ids on purchase events.
- units: sum of item quantities on purchase events.
- sessions: number of distinct (user_pseudo_id, ga_session_id) pairs.
- purchasers: distinct users with at least one purchase.
- conversion_rate: purchasing sessions / sessions, as a fraction between 0 and 1.
- Lists are capped at ``limit`` rows (1..50, default 10).

On an invalid argument the tool returns ``{"error": "<message>"}`` rather than raising,
so the caller can correct the input and retry. Other failures (service unreachable,
deadline exceeded, internal errors) raise.
"""

from __future__ import annotations

import threading
from typing import Any

import grpc

from merchant_analyst.client import AnalystClient, proto_to_dict

_client: AnalystClient | None = None
_client_lock = threading.Lock()


def get_client() -> AnalystClient:
    """Return the module-level client, creating it lazily from ``TOOL_SERVICE_ADDRESS``."""
    global _client
    with _client_lock:
        if _client is None:
            _client = AnalystClient()
        return _client


def set_client(client: AnalystClient | None) -> None:
    """Replace the module-level client (tests inject a client bound to a fake server)."""
    global _client
    with _client_lock:
        _client = client


def _call(fn, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return proto_to_dict(fn(*args, **kwargs))
    except ValueError as exc:  # bad metric name, caught before hitting the wire
        return {"error": str(exc)}
    except grpc.RpcError as exc:
        if exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
            return {"error": exc.details() or "invalid argument"}
        raise


def get_dataset_info() -> dict[str, Any]:
    """Describe the dataset: table, available date window, currency, totals and caveats.

    Call this when unsure which dates are available. The window is 2020-11-01 to
    2021-01-31 (inclusive) and all money is in USD.

    Returns:
        dict with ``table``, ``available_range`` (``start_date``/``end_date``), ``currency``,
        ``total_events``, ``total_sessions``, ``total_purchases`` (ints), ``caveats`` (list of
        strings) and ``meta``.
    """
    return _call(get_client().get_dataset_info)


def get_sales_summary(start_date: str, end_date: str) -> dict[str, Any]:
    """Headline commerce KPIs for an inclusive date range.

    Args:
        start_date: First day, ISO ``YYYY-MM-DD``. Dataset window: 2020-11-01 to 2021-01-31.
        end_date: Last day (inclusive), ISO ``YYYY-MM-DD``.

    Returns:
        dict with ``revenue`` (USD, sum of purchase revenue on purchase events),
        ``currency``, ``orders`` (distinct transaction ids), ``units`` (sum of item
        quantities), ``purchasers`` (distinct users with a purchase), ``sessions``
        (distinct user/session pairs), ``purchasing_sessions``, ``average_order_value``
        (revenue / orders, 0 if no orders), ``conversion_rate`` (purchasing sessions /
        sessions, fraction 0..1) and ``meta`` (``date_range_applied``, ``clamped``).
        Or ``{"error": message}`` if the dates are invalid.
    """
    return _call(get_client().get_sales_summary, start_date, end_date)


def get_top_products(
    start_date: str, end_date: str, metric: str = "REVENUE", limit: int = 10
) -> dict[str, Any]:
    """Best-selling items in an inclusive date range, ranked by a metric.

    Args:
        start_date: First day, ISO ``YYYY-MM-DD``. Dataset window: 2020-11-01 to 2021-01-31.
        end_date: Last day (inclusive), ISO ``YYYY-MM-DD``.
        metric: Ranking metric. Allowed: ``"REVENUE"`` (default, USD item revenue on
            purchase events), ``"UNITS"`` (sum of item quantities), ``"ORDERS"`` (distinct
            transaction ids containing the item).
        limit: Maximum number of rows, 1..50 (default 10).

    Returns:
        dict with ``metric``, ``currency`` and ``rows``: list of ``rank``, ``item_name``,
        ``item_category``, ``revenue`` (USD), ``units``, ``orders``; plus ``meta``.
        Or ``{"error": message}`` for an invalid metric, limit or date.
    """
    return _call(get_client().get_top_products, start_date, end_date, metric, limit)


def get_daily_trend(start_date: str, end_date: str, metric: str = "REVENUE") -> dict[str, Any]:
    """One value per calendar day for a metric over an inclusive date range.

    Args:
        start_date: First day, ISO ``YYYY-MM-DD``. Dataset window: 2020-11-01 to 2021-01-31.
        end_date: Last day (inclusive), ISO ``YYYY-MM-DD``.
        metric: Allowed: ``"REVENUE"`` (default, USD), ``"ORDERS"`` (distinct transaction
            ids), ``"UNITS"``, ``"SESSIONS"`` (distinct user/session pairs), ``"PURCHASERS"``
            (distinct purchasing users), ``"CONVERSION_RATE"`` (purchasing sessions /
            sessions, fraction 0..1).

    Returns:
        dict with ``metric``, ``points`` (list of ``date`` ``YYYY-MM-DD`` and ``value``),
        ``total`` (sum of the points; mean for CONVERSION_RATE), ``minimum``, ``maximum``,
        ``currency`` (``"USD"`` for REVENUE, else empty) and ``meta``.
        Or ``{"error": message}`` for an invalid metric or date.
    """
    return _call(get_client().get_daily_trend, start_date, end_date, metric)


def get_traffic_by_source(start_date: str, end_date: str, limit: int = 10) -> dict[str, Any]:
    """Sessions, purchasers, orders and revenue per traffic source / medium.

    Rows are ordered by sessions descending.

    Args:
        start_date: First day, ISO ``YYYY-MM-DD``. Dataset window: 2020-11-01 to 2021-01-31.
        end_date: Last day (inclusive), ISO ``YYYY-MM-DD``.
        limit: Maximum number of rows, 1..50 (default 10).

    Returns:
        dict with ``currency`` and ``rows``: list of ``rank``, ``source``, ``medium``,
        ``sessions`` (distinct user/session pairs), ``purchasers``, ``orders`` (distinct
        transaction ids), ``revenue`` (USD), ``conversion_rate`` (purchasing sessions /
        sessions, fraction 0..1); plus ``meta``. Or ``{"error": message}``.
    """
    return _call(get_client().get_traffic_by_source, start_date, end_date, limit)


def get_funnel(start_date: str, end_date: str) -> dict[str, Any]:
    """Purchase funnel view_item -> add_to_cart -> begin_checkout -> purchase, by sessions.

    Args:
        start_date: First day, ISO ``YYYY-MM-DD``. Dataset window: 2020-11-01 to 2021-01-31.
        end_date: Last day (inclusive), ISO ``YYYY-MM-DD``.

    Returns:
        dict with ``steps``: list of ``event_name``, ``sessions`` (distinct sessions with
        that event), ``step_rate`` (sessions / previous step's sessions, 1.0 for the first
        step, fraction 0..1) and ``cumulative_rate`` (sessions / first step's sessions,
        fraction 0..1); plus ``meta``. Or ``{"error": message}``.
    """
    return _call(get_client().get_funnel, start_date, end_date)


def get_geo_breakdown(start_date: str, end_date: str, limit: int = 10) -> dict[str, Any]:
    """Sessions, orders and revenue per country, ordered by revenue descending.

    Args:
        start_date: First day, ISO ``YYYY-MM-DD``. Dataset window: 2020-11-01 to 2021-01-31.
        end_date: Last day (inclusive), ISO ``YYYY-MM-DD``.
        limit: Maximum number of rows, 1..50 (default 10).

    Returns:
        dict with ``currency`` and ``rows``: list of ``rank``, ``country``, ``sessions``
        (distinct user/session pairs), ``orders`` (distinct transaction ids), ``revenue``
        (USD); plus ``meta``. Or ``{"error": message}``.
    """
    return _call(get_client().get_geo_breakdown, start_date, end_date, limit)


ALL_TOOLS = [
    get_dataset_info,
    get_sales_summary,
    get_top_products,
    get_daily_trend,
    get_traffic_by_source,
    get_funnel,
    get_geo_breakdown,
]
