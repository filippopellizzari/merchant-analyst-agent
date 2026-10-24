package ai.flowit.merchant.service;

import static ai.flowit.merchant.testing.FakeBigQueryGateway.row;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.flowit.merchant.bigquery.QueryParam;
import ai.flowit.merchant.bigquery.SqlLoader;
import ai.flowit.merchant.testing.FakeBigQueryGateway;
import ai.flowit.merchant.testing.InProcessServerExtension;
import ai.flowit.merchant.v1.DailyTrend;
import ai.flowit.merchant.v1.DatasetInfo;
import ai.flowit.merchant.v1.DateRange;
import ai.flowit.merchant.v1.Funnel;
import ai.flowit.merchant.v1.GeoBreakdown;
import ai.flowit.merchant.v1.GetDailyTrendRequest;
import ai.flowit.merchant.v1.GetDatasetInfoRequest;
import ai.flowit.merchant.v1.GetFunnelRequest;
import ai.flowit.merchant.v1.GetGeoBreakdownRequest;
import ai.flowit.merchant.v1.GetSalesSummaryRequest;
import ai.flowit.merchant.v1.GetTopProductsRequest;
import ai.flowit.merchant.v1.GetTrafficBySourceRequest;
import ai.flowit.merchant.v1.Metric;
import ai.flowit.merchant.v1.QueryMeta;
import ai.flowit.merchant.v1.SalesSummary;
import ai.flowit.merchant.v1.TopProducts;
import ai.flowit.merchant.v1.TrafficBySource;
import com.google.cloud.bigquery.BigQueryException;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;

class MerchantAnalystServiceTest {

  private static final double EPS = 1e-9;
  private static final String TABLE = "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*";

  @RegisterExtension
  final InProcessServerExtension grpc = new InProcessServerExtension();

  private FakeBigQueryGateway gateway;

  @BeforeEach
  void setUp() {
    gateway = grpc.gateway();
  }

  private static DateRange range(String start, String end) {
    return DateRange.newBuilder().setStartDate(start).setEndDate(end).build();
  }

  private static void assertMeta(QueryMeta meta, String sqlName, String start, String end, boolean clamped) {
    assertEquals(start, meta.getDateRangeApplied().getStartDate());
    assertEquals(end, meta.getDateRangeApplied().getEndDate());
    assertEquals(clamped, meta.getClamped());
    assertEquals(new SqlLoader().hash(sqlName), meta.getSqlHash());
    assertEquals(16, meta.getSqlHash().length());
    assertEquals(TABLE, meta.getTable());
  }

  private static void assertStatus(Status.Code expected, Runnable call) {
    StatusRuntimeException e = assertThrows(StatusRuntimeException.class, call::run);
    assertEquals(expected, e.getStatus().getCode(), e.getMessage());
  }

  @Nested
  class DatasetInfoRpc {

    @Test
    void mapsTotalsAndFillsStaticFields() {
      gateway.returnRows("dataset_info", List.of(
          row("total_events", 4_295_584L, "total_sessions", 353_000L, "total_purchases", 5_692L)));

      DatasetInfo info = grpc.stub().getDatasetInfo(GetDatasetInfoRequest.getDefaultInstance());

      assertEquals(TABLE, info.getTable());
      assertEquals("2020-11-01", info.getAvailableRange().getStartDate());
      assertEquals("2021-01-31", info.getAvailableRange().getEndDate());
      assertEquals("USD", info.getCurrency());
      assertEquals(4_295_584L, info.getTotalEvents());
      assertEquals(353_000L, info.getTotalSessions());
      assertEquals(5_692L, info.getTotalPurchases());
      assertFalse(info.getCaveatsList().isEmpty());
      assertTrue(info.getCaveatsList().stream().anyMatch(c -> c.toLowerCase().contains("obfuscated")));
      assertMeta(info.getMeta(), "dataset_info", "2020-11-01", "2021-01-31", false);
      assertEquals(QueryParam.string("20201101"), gateway.lastCall().params().get("start_suffix"));
      assertEquals(QueryParam.string("20210131"), gateway.lastCall().params().get("end_suffix"));
    }
  }

  @Nested
  class SalesSummaryRpc {

    @Test
    void mapsRowAndDerivesAovAndConversion() {
      gateway.returnRows("sales_summary", List.of(row(
          "revenue", 1000.0, "orders", 8L, "units", 20L, "purchasers", 7L,
          "sessions", 400L, "purchasing_sessions", 10L)));
      gateway.withStats(98_765L, true);

      SalesSummary summary = grpc.stub().getSalesSummary(GetSalesSummaryRequest.newBuilder()
          .setDateRange(range("2020-12-01", "2020-12-31")).build());

      assertEquals(1000.0, summary.getRevenue(), EPS);
      assertEquals("USD", summary.getCurrency());
      assertEquals(8L, summary.getOrders());
      assertEquals(20L, summary.getUnits());
      assertEquals(7L, summary.getPurchasers());
      assertEquals(400L, summary.getSessions());
      assertEquals(10L, summary.getPurchasingSessions());
      assertEquals(125.0, summary.getAverageOrderValue(), EPS);
      assertEquals(0.025, summary.getConversionRate(), EPS);
      assertMeta(summary.getMeta(), "sales_summary", "2020-12-01", "2020-12-31", false);
      assertEquals(98_765L, summary.getMeta().getBytesProcessed());
      assertTrue(summary.getMeta().getCacheHit());

      FakeBigQueryGateway.Call call = gateway.lastCall();
      assertEquals("sales_summary", call.sqlResourceName());
      assertEquals(QueryParam.string("20201201"), call.params().get("start_suffix"));
      assertEquals(QueryParam.string("20201231"), call.params().get("end_suffix"));
    }

    @Test
    void zeroOrdersAndSessionsYieldZeroRatios() {
      gateway.returnRows("sales_summary", List.of(row(
          "revenue", 0.0, "orders", 0L, "units", 0L, "purchasers", 0L, "sessions", 0L, "purchasing_sessions", 0L)));

      SalesSummary summary = grpc.stub().getSalesSummary(GetSalesSummaryRequest.getDefaultInstance());

      assertEquals(0.0, summary.getAverageOrderValue(), EPS);
      assertEquals(0.0, summary.getConversionRate(), EPS);
    }

    @Test
    void emptyResultYieldsZeros() {
      SalesSummary summary = grpc.stub().getSalesSummary(GetSalesSummaryRequest.getDefaultInstance());

      assertEquals(0L, summary.getOrders());
      assertEquals(0.0, summary.getRevenue(), EPS);
    }

    @Test
    void clampsOutOfWindowRangeAndFlagsMeta() {
      gateway.returnRows("sales_summary", List.of(row("revenue", 1.0)));

      SalesSummary summary = grpc.stub().getSalesSummary(GetSalesSummaryRequest.newBuilder()
          .setDateRange(range("2020-01-01", "2021-12-31")).build());

      assertMeta(summary.getMeta(), "sales_summary", "2020-11-01", "2021-01-31", true);
      assertEquals(QueryParam.string("20201101"), gateway.lastCall().params().get("start_suffix"));
      assertEquals(QueryParam.string("20210131"), gateway.lastCall().params().get("end_suffix"));
    }

    @Test
    void badDatesAreInvalidArgument() {
      assertStatus(Status.Code.INVALID_ARGUMENT, () -> grpc.stub().getSalesSummary(
          GetSalesSummaryRequest.newBuilder().setDateRange(range("2020-13-01", "2020-12-31")).build()));
      assertStatus(Status.Code.INVALID_ARGUMENT, () -> grpc.stub().getSalesSummary(
          GetSalesSummaryRequest.newBuilder().setDateRange(range("2020-12-31", "2020-12-01")).build()));
      assertTrue(gateway.calls().isEmpty(), "gateway must not be called for invalid input");
    }

    @Test
    void bigQueryFailureIsUnavailableWithoutSql() {
      gateway.failWith(new BigQueryException(503, "backendError: SELECT secret FROM table"));

      StatusRuntimeException e = assertThrows(StatusRuntimeException.class,
          () -> grpc.stub().getSalesSummary(GetSalesSummaryRequest.getDefaultInstance()));

      assertEquals(Status.Code.UNAVAILABLE, e.getStatus().getCode());
      assertFalse(e.getStatus().getDescription().contains("SELECT"));
    }

    @Test
    void unexpectedFailureIsInternal() {
      gateway.failWith(new IllegalStateException("boom"));

      assertStatus(Status.Code.INTERNAL, () -> grpc.stub().getSalesSummary(GetSalesSummaryRequest.getDefaultInstance()));
    }
  }

  @Nested
  class TopProductsRpc {

    @Test
    void ranksRowsInOrderAndPassesMetricAndLimit() {
      gateway.returnRows("top_products", List.of(
          row("item_name", "Hoodie", "item_category", "Apparel", "revenue", 500.5, "units", 30L, "orders", 25L),
          row("item_name", "Mug", "item_category", "Drinkware", "revenue", 120.0, "units", 60L, "orders", 50L)));

      TopProducts products = grpc.stub().getTopProducts(GetTopProductsRequest.newBuilder()
          .setMetric(Metric.UNITS).setLimit(5).build());

      assertEquals(Metric.UNITS, products.getMetric());
      assertEquals("USD", products.getCurrency());
      assertEquals(2, products.getRowsCount());
      assertEquals(1, products.getRows(0).getRank());
      assertEquals("Hoodie", products.getRows(0).getItemName());
      assertEquals("Apparel", products.getRows(0).getItemCategory());
      assertEquals(500.5, products.getRows(0).getRevenue(), EPS);
      assertEquals(30L, products.getRows(0).getUnits());
      assertEquals(25L, products.getRows(0).getOrders());
      assertEquals(2, products.getRows(1).getRank());
      assertEquals("Mug", products.getRows(1).getItemName());
      assertMeta(products.getMeta(), "top_products", "2020-11-01", "2021-01-31", false);

      FakeBigQueryGateway.Call call = gateway.lastCall();
      assertEquals(QueryParam.string("UNITS"), call.params().get("metric"));
      assertEquals(QueryParam.int64(5), call.params().get("limit"));
    }

    @Test
    void defaultsToRevenueAndLimitTen() {
      TopProducts products = grpc.stub().getTopProducts(GetTopProductsRequest.getDefaultInstance());

      assertEquals(Metric.REVENUE, products.getMetric());
      assertEquals(QueryParam.string("REVENUE"), gateway.lastCall().params().get("metric"));
      assertEquals(QueryParam.int64(10), gateway.lastCall().params().get("limit"));
    }

    @Test
    void rejectsInvalidLimitAndUnsupportedMetric() {
      assertStatus(Status.Code.INVALID_ARGUMENT,
          () -> grpc.stub().getTopProducts(GetTopProductsRequest.newBuilder().setLimit(51).build()));
      assertStatus(Status.Code.INVALID_ARGUMENT,
          () -> grpc.stub().getTopProducts(GetTopProductsRequest.newBuilder().setLimit(-3).build()));
      assertStatus(Status.Code.INVALID_ARGUMENT,
          () -> grpc.stub().getTopProducts(GetTopProductsRequest.newBuilder().setMetric(Metric.SESSIONS).build()));
      assertStatus(Status.Code.INVALID_ARGUMENT,
          () -> grpc.stub().getTopProducts(GetTopProductsRequest.newBuilder().setMetric(Metric.CONVERSION_RATE).build()));
      assertTrue(gateway.calls().isEmpty());
    }
  }

  @Nested
  class DailyTrendRpc {

    private void cannedDays() {
      gateway.returnRows("daily_trend", List.of(
          row("date", "2020-12-01", "revenue", 100.0, "orders", 2L, "units", 5L, "sessions", 50L,
              "purchasers", 2L, "conversion_rate", 0.04),
          row("date", "2020-12-02", "revenue", 300.0, "orders", 6L, "units", 9L, "sessions", 100L,
              "purchasers", 5L, "conversion_rate", 0.06),
          row("date", "2020-12-03", "revenue", 50.0, "orders", 1L, "units", 1L, "sessions", 25L,
              "purchasers", 1L, "conversion_rate", 0.02)));
    }

    @Test
    void revenueTrendSumsTotalAndTracksMinMax() {
      cannedDays();

      DailyTrend trend = grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder()
          .setDateRange(range("2020-12-01", "2020-12-03")).build());

      assertEquals(Metric.REVENUE, trend.getMetric());
      assertEquals("USD", trend.getCurrency());
      assertEquals(3, trend.getPointsCount());
      assertEquals("2020-12-01", trend.getPoints(0).getDate());
      assertEquals(100.0, trend.getPoints(0).getValue(), EPS);
      assertEquals(300.0, trend.getPoints(1).getValue(), EPS);
      assertEquals(450.0, trend.getTotal(), EPS);
      assertEquals(50.0, trend.getMinimum(), EPS);
      assertEquals(300.0, trend.getMaximum(), EPS);
      assertMeta(trend.getMeta(), "daily_trend", "2020-12-01", "2020-12-03", false);
    }

    @Test
    void sessionsTrendHasNoCurrency() {
      cannedDays();

      DailyTrend trend = grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder().setMetric(Metric.SESSIONS).build());

      assertEquals(Metric.SESSIONS, trend.getMetric());
      assertEquals("", trend.getCurrency());
      assertEquals(175.0, trend.getTotal(), EPS);
      assertEquals(25.0, trend.getMinimum(), EPS);
      assertEquals(100.0, trend.getMaximum(), EPS);
    }

    @Test
    void ordersUnitsPurchasersPickTheirColumns() {
      cannedDays();

      assertEquals(9.0, grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder().setMetric(Metric.ORDERS).build()).getTotal(), EPS);
      assertEquals(15.0, grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder().setMetric(Metric.UNITS).build()).getTotal(), EPS);
      assertEquals(8.0, grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder().setMetric(Metric.PURCHASERS).build()).getTotal(), EPS);
    }

    @Test
    void conversionRateTotalIsTheMean() {
      cannedDays();

      DailyTrend trend = grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder()
          .setMetric(Metric.CONVERSION_RATE).build());

      assertEquals(0.04, trend.getTotal(), EPS);
      assertEquals(0.02, trend.getMinimum(), EPS);
      assertEquals(0.06, trend.getMaximum(), EPS);
      assertEquals("", trend.getCurrency());
    }

    @Test
    void emptyTrendHasZeroAggregates() {
      DailyTrend trend = grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder()
          .setMetric(Metric.CONVERSION_RATE).build());

      assertEquals(0, trend.getPointsCount());
      assertEquals(0.0, trend.getTotal(), EPS);
      assertEquals(0.0, trend.getMinimum(), EPS);
      assertEquals(0.0, trend.getMaximum(), EPS);
    }

    @Test
    void rejectsBadDates() {
      assertStatus(Status.Code.INVALID_ARGUMENT, () -> grpc.stub().getDailyTrend(GetDailyTrendRequest.newBuilder()
          .setDateRange(range("not-a-date", "")).build()));
    }
  }

  @Nested
  class TrafficBySourceRpc {

    @Test
    void mapsRowsWithRank() {
      gateway.returnRows("traffic_by_source", List.of(
          row("source", "google", "medium", "organic", "sessions", 1000L, "purchasers", 30L, "orders", 35L,
              "revenue", 2500.25, "conversion_rate", 0.032),
          row("source", "(direct)", "medium", "(none)", "sessions", 800L, "purchasers", 10L, "orders", 11L,
              "revenue", 900.0, "conversion_rate", 0.0125)));

      TrafficBySource traffic = grpc.stub().getTrafficBySource(GetTrafficBySourceRequest.newBuilder()
          .setDateRange(range("2021-01-01", "2021-01-31")).setLimit(2).build());

      assertEquals("USD", traffic.getCurrency());
      assertEquals(2, traffic.getRowsCount());
      assertEquals(1, traffic.getRows(0).getRank());
      assertEquals("google", traffic.getRows(0).getSource());
      assertEquals("organic", traffic.getRows(0).getMedium());
      assertEquals(1000L, traffic.getRows(0).getSessions());
      assertEquals(30L, traffic.getRows(0).getPurchasers());
      assertEquals(35L, traffic.getRows(0).getOrders());
      assertEquals(2500.25, traffic.getRows(0).getRevenue(), EPS);
      assertEquals(0.032, traffic.getRows(0).getConversionRate(), EPS);
      assertEquals(2, traffic.getRows(1).getRank());
      assertEquals("(direct)", traffic.getRows(1).getSource());
      assertMeta(traffic.getMeta(), "traffic_by_source", "2021-01-01", "2021-01-31", false);
      assertEquals(QueryParam.int64(2), gateway.lastCall().params().get("limit"));
    }

    @Test
    void rejectsInvalidLimit() {
      assertStatus(Status.Code.INVALID_ARGUMENT,
          () -> grpc.stub().getTrafficBySource(GetTrafficBySourceRequest.newBuilder().setLimit(100).build()));
    }
  }

  @Nested
  class FunnelRpc {

    @Test
    void computesStepAndCumulativeRatesInFixedOrder() {
      // Rows come back in arbitrary order and may omit steps with zero sessions.
      gateway.returnRows("funnel", List.of(
          row("event_name", "purchase", "sessions", 50L),
          row("event_name", "view_item", "sessions", 1000L),
          row("event_name", "add_to_cart", "sessions", 400L),
          row("event_name", "begin_checkout", "sessions", 200L)));

      Funnel funnel = grpc.stub().getFunnel(GetFunnelRequest.newBuilder()
          .setDateRange(range("2020-11-01", "2020-11-30")).build());

      assertEquals(List.of("view_item", "add_to_cart", "begin_checkout", "purchase"),
          funnel.getStepsList().stream().map(s -> s.getEventName()).toList());
      assertEquals(1000L, funnel.getSteps(0).getSessions());
      assertEquals(1.0, funnel.getSteps(0).getStepRate(), EPS);
      assertEquals(1.0, funnel.getSteps(0).getCumulativeRate(), EPS);
      assertEquals(0.4, funnel.getSteps(1).getStepRate(), EPS);
      assertEquals(0.4, funnel.getSteps(1).getCumulativeRate(), EPS);
      assertEquals(0.5, funnel.getSteps(2).getStepRate(), EPS);
      assertEquals(0.2, funnel.getSteps(2).getCumulativeRate(), EPS);
      assertEquals(0.25, funnel.getSteps(3).getStepRate(), EPS);
      assertEquals(0.05, funnel.getSteps(3).getCumulativeRate(), EPS);
      assertMeta(funnel.getMeta(), "funnel", "2020-11-01", "2020-11-30", false);
    }

    @Test
    void missingStepsAreZeroWithoutDivisionByZero() {
      gateway.returnRows("funnel", List.of(row("event_name", "view_item", "sessions", 10L)));

      Funnel funnel = grpc.stub().getFunnel(GetFunnelRequest.getDefaultInstance());

      assertEquals(4, funnel.getStepsCount());
      assertEquals(0L, funnel.getSteps(1).getSessions());
      assertEquals(0.0, funnel.getSteps(1).getStepRate(), EPS);
      assertEquals(0.0, funnel.getSteps(2).getStepRate(), EPS);
      assertEquals(0.0, funnel.getSteps(3).getCumulativeRate(), EPS);
    }
  }

  @Nested
  class GeoBreakdownRpc {

    @Test
    void mapsRowsWithRank() {
      gateway.returnRows("geo_breakdown", List.of(
          row("country", "United States", "sessions", 5000L, "orders", 300L, "revenue", 20000.0),
          row("country", "Canada", "sessions", 700L, "orders", 40L, "revenue", 2500.0)));

      GeoBreakdown geo = grpc.stub().getGeoBreakdown(GetGeoBreakdownRequest.newBuilder().setLimit(2).build());

      assertEquals("USD", geo.getCurrency());
      assertEquals(2, geo.getRowsCount());
      assertEquals(1, geo.getRows(0).getRank());
      assertEquals("United States", geo.getRows(0).getCountry());
      assertEquals(5000L, geo.getRows(0).getSessions());
      assertEquals(300L, geo.getRows(0).getOrders());
      assertEquals(20000.0, geo.getRows(0).getRevenue(), EPS);
      assertEquals(2, geo.getRows(1).getRank());
      assertEquals("Canada", geo.getRows(1).getCountry());
      assertMeta(geo.getMeta(), "geo_breakdown", "2020-11-01", "2021-01-31", false);
      assertEquals(QueryParam.int64(2), gateway.lastCall().params().get("limit"));
    }

    @Test
    void rejectsInvalidLimit() {
      assertStatus(Status.Code.INVALID_ARGUMENT,
          () -> grpc.stub().getGeoBreakdown(GetGeoBreakdownRequest.newBuilder().setLimit(51).build()));
    }
  }
}
