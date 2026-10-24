package ai.flowit.merchant.service;

import ai.flowit.merchant.bigquery.BigQueryGateway;
import ai.flowit.merchant.bigquery.QueryParam;
import ai.flowit.merchant.bigquery.QueryResult;
import ai.flowit.merchant.bigquery.SqlLoader;
import ai.flowit.merchant.v1.DailyPoint;
import ai.flowit.merchant.v1.DailyTrend;
import ai.flowit.merchant.v1.DatasetInfo;
import ai.flowit.merchant.v1.Funnel;
import ai.flowit.merchant.v1.FunnelStep;
import ai.flowit.merchant.v1.GeoBreakdown;
import ai.flowit.merchant.v1.GeoRow;
import ai.flowit.merchant.v1.GetDailyTrendRequest;
import ai.flowit.merchant.v1.GetDatasetInfoRequest;
import ai.flowit.merchant.v1.GetFunnelRequest;
import ai.flowit.merchant.v1.GetGeoBreakdownRequest;
import ai.flowit.merchant.v1.GetSalesSummaryRequest;
import ai.flowit.merchant.v1.GetTopProductsRequest;
import ai.flowit.merchant.v1.GetTrafficBySourceRequest;
import ai.flowit.merchant.v1.MerchantAnalystGrpc;
import ai.flowit.merchant.v1.Metric;
import ai.flowit.merchant.v1.ProductRow;
import ai.flowit.merchant.v1.QueryMeta;
import ai.flowit.merchant.v1.SalesSummary;
import ai.flowit.merchant.v1.SourceRow;
import ai.flowit.merchant.v1.TopProducts;
import ai.flowit.merchant.v1.TrafficBySource;
import com.google.cloud.bigquery.BigQueryException;
import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import io.grpc.stub.StreamObserver;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** gRPC implementation of {@code merchant.v1.MerchantAnalyst} on top of hand-written SQL. */
public final class MerchantAnalystService extends MerchantAnalystGrpc.MerchantAnalystImplBase {

  private static final Logger log = LoggerFactory.getLogger(MerchantAnalystService.class);

  public static final String TABLE = "bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*";
  public static final String CURRENCY = "USD";

  public static final String SQL_DATASET_INFO = "dataset_info";
  public static final String SQL_SALES_SUMMARY = "sales_summary";
  public static final String SQL_TOP_PRODUCTS = "top_products";
  public static final String SQL_DAILY_TREND = "daily_trend";
  public static final String SQL_TRAFFIC_BY_SOURCE = "traffic_by_source";
  public static final String SQL_FUNNEL = "funnel";
  public static final String SQL_GEO_BREAKDOWN = "geo_breakdown";

  public static final String PARAM_LIMIT = "limit";
  public static final String PARAM_METRIC = "metric";

  public static final List<String> FUNNEL_STEPS = List.of("view_item", "add_to_cart", "begin_checkout", "purchase");

  public static final List<String> CAVEATS = List.of(
      "Data is the public, obfuscated GA4 export of the Google Merchandise Store; user and session "
          + "identifiers are anonymised and some values are deliberately masked or set to '(not set)'.",
      "The sample covers only " + DateRanges.START + " to " + DateRanges.END + "; requests outside that "
          + "window are clamped to it.",
      "Figures are computed from raw events and may differ from the Google Analytics UI, which applies "
          + "its own sessionisation, deduplication and currency handling.",
      "Revenue is reported as exported in USD; refunds are not deducted.");

  private static final Set<Metric> TOP_PRODUCT_METRICS = EnumSet.of(Metric.REVENUE, Metric.UNITS, Metric.ORDERS);
  private static final Set<Metric> TREND_METRICS = EnumSet.of(
      Metric.REVENUE, Metric.ORDERS, Metric.UNITS, Metric.SESSIONS, Metric.PURCHASERS, Metric.CONVERSION_RATE);

  private final BigQueryGateway gateway;
  private final SqlLoader sqlLoader;

  public MerchantAnalystService(BigQueryGateway gateway, SqlLoader sqlLoader) {
    this.gateway = Objects.requireNonNull(gateway, "gateway");
    this.sqlLoader = Objects.requireNonNull(sqlLoader, "sqlLoader");
  }

  // ---------------------------------------------------------------------------------------------
  // RPCs
  // ---------------------------------------------------------------------------------------------

  @Override
  public void getDatasetInfo(GetDatasetInfoRequest request, StreamObserver<DatasetInfo> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.full();
      QueryResult result = gateway.run(SQL_DATASET_INFO, range.toParams());
      Map<String, Object> row = single(result);
      return DatasetInfo.newBuilder()
          .setTable(TABLE)
          .setAvailableRange(range.toProto())
          .setCurrency(CURRENCY)
          .setTotalEvents(Rows.getLong(row, "total_events"))
          .setTotalSessions(Rows.getLong(row, "total_sessions"))
          .setTotalPurchases(Rows.getLong(row, "total_purchases"))
          .addAllCaveats(CAVEATS)
          .setMeta(meta(SQL_DATASET_INFO, range, result))
          .build();
    });
  }

  @Override
  public void getSalesSummary(GetSalesSummaryRequest request, StreamObserver<SalesSummary> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.resolve(request.getDateRange());
      QueryResult result = gateway.run(SQL_SALES_SUMMARY, range.toParams());
      Map<String, Object> row = single(result);
      double revenue = Rows.getDouble(row, "revenue");
      long orders = Rows.getLong(row, "orders");
      long sessions = Rows.getLong(row, "sessions");
      long purchasingSessions = Rows.getLong(row, "purchasing_sessions");
      return SalesSummary.newBuilder()
          .setRevenue(revenue)
          .setCurrency(CURRENCY)
          .setOrders(orders)
          .setUnits(Rows.getLong(row, "units"))
          .setPurchasers(Rows.getLong(row, "purchasers"))
          .setSessions(sessions)
          .setPurchasingSessions(purchasingSessions)
          .setAverageOrderValue(Rows.ratio(revenue, orders))
          .setConversionRate(Rows.ratio(purchasingSessions, sessions))
          .setMeta(meta(SQL_SALES_SUMMARY, range, result))
          .build();
    });
  }

  @Override
  public void getTopProducts(GetTopProductsRequest request, StreamObserver<TopProducts> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.resolve(request.getDateRange());
      int limit = DateRanges.resolveLimit(request.getLimit());
      Metric metric = resolveMetric(request.getMetric(), TOP_PRODUCT_METRICS);

      Map<String, QueryParam> params = new HashMap<>(range.toParams());
      params.put(PARAM_METRIC, QueryParam.string(metric.name()));
      params.put(PARAM_LIMIT, QueryParam.int64(limit));
      QueryResult result = gateway.run(SQL_TOP_PRODUCTS, params);

      TopProducts.Builder builder = TopProducts.newBuilder().setMetric(metric).setCurrency(CURRENCY);
      int rank = 1;
      for (Map<String, Object> row : result.rows()) {
        builder.addRows(ProductRow.newBuilder()
            .setRank(rank++)
            .setItemName(Rows.getString(row, "item_name"))
            .setItemCategory(Rows.getString(row, "item_category"))
            .setRevenue(Rows.getDouble(row, "revenue"))
            .setUnits(Rows.getLong(row, "units"))
            .setOrders(Rows.getLong(row, "orders")));
      }
      return builder.setMeta(meta(SQL_TOP_PRODUCTS, range, result)).build();
    });
  }

  @Override
  public void getDailyTrend(GetDailyTrendRequest request, StreamObserver<DailyTrend> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.resolve(request.getDateRange());
      Metric metric = resolveMetric(request.getMetric(), TREND_METRICS);
      QueryResult result = gateway.run(SQL_DAILY_TREND, range.toParams());

      String column = trendColumn(metric);
      DailyTrend.Builder builder = DailyTrend.newBuilder().setMetric(metric);
      double sum = 0d;
      double min = Double.POSITIVE_INFINITY;
      double max = Double.NEGATIVE_INFINITY;
      for (Map<String, Object> row : result.rows()) {
        double value = Rows.getDouble(row, column);
        builder.addPoints(DailyPoint.newBuilder().setDate(Rows.getString(row, "date")).setValue(value));
        sum += value;
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
      int count = builder.getPointsCount();
      double total = metric == Metric.CONVERSION_RATE ? Rows.ratio(sum, count) : sum;
      return builder
          .setTotal(total)
          .setMinimum(count == 0 ? 0d : min)
          .setMaximum(count == 0 ? 0d : max)
          .setCurrency(metric == Metric.REVENUE ? CURRENCY : "")
          .setMeta(meta(SQL_DAILY_TREND, range, result))
          .build();
    });
  }

  @Override
  public void getTrafficBySource(GetTrafficBySourceRequest request, StreamObserver<TrafficBySource> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.resolve(request.getDateRange());
      int limit = DateRanges.resolveLimit(request.getLimit());

      Map<String, QueryParam> params = new HashMap<>(range.toParams());
      params.put(PARAM_LIMIT, QueryParam.int64(limit));
      QueryResult result = gateway.run(SQL_TRAFFIC_BY_SOURCE, params);

      TrafficBySource.Builder builder = TrafficBySource.newBuilder().setCurrency(CURRENCY);
      int rank = 1;
      for (Map<String, Object> row : result.rows()) {
        builder.addRows(SourceRow.newBuilder()
            .setRank(rank++)
            .setSource(Rows.getString(row, "source"))
            .setMedium(Rows.getString(row, "medium"))
            .setSessions(Rows.getLong(row, "sessions"))
            .setPurchasers(Rows.getLong(row, "purchasers"))
            .setOrders(Rows.getLong(row, "orders"))
            .setRevenue(Rows.getDouble(row, "revenue"))
            .setConversionRate(Rows.getDouble(row, "conversion_rate")));
      }
      return builder.setMeta(meta(SQL_TRAFFIC_BY_SOURCE, range, result)).build();
    });
  }

  @Override
  public void getFunnel(GetFunnelRequest request, StreamObserver<Funnel> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.resolve(request.getDateRange());
      QueryResult result = gateway.run(SQL_FUNNEL, range.toParams());

      Map<String, Long> sessionsByStep = new HashMap<>();
      for (Map<String, Object> row : result.rows()) {
        sessionsByStep.put(Rows.getString(row, "event_name"), Rows.getLong(row, "sessions"));
      }

      Funnel.Builder builder = Funnel.newBuilder();
      long first = sessionsByStep.getOrDefault(FUNNEL_STEPS.get(0), 0L);
      long previous = first;
      for (int i = 0; i < FUNNEL_STEPS.size(); i++) {
        String step = FUNNEL_STEPS.get(i);
        long sessions = sessionsByStep.getOrDefault(step, 0L);
        double stepRate = i == 0 ? 1d : Rows.ratio(sessions, previous);
        double cumulativeRate = i == 0 ? 1d : Rows.ratio(sessions, first);
        builder.addSteps(FunnelStep.newBuilder()
            .setEventName(step)
            .setSessions(sessions)
            .setStepRate(stepRate)
            .setCumulativeRate(cumulativeRate));
        previous = sessions;
      }
      return builder.setMeta(meta(SQL_FUNNEL, range, result)).build();
    });
  }

  @Override
  public void getGeoBreakdown(GetGeoBreakdownRequest request, StreamObserver<GeoBreakdown> observer) {
    respond(observer, () -> {
      DateRanges.Applied range = DateRanges.resolve(request.getDateRange());
      int limit = DateRanges.resolveLimit(request.getLimit());

      Map<String, QueryParam> params = new HashMap<>(range.toParams());
      params.put(PARAM_LIMIT, QueryParam.int64(limit));
      QueryResult result = gateway.run(SQL_GEO_BREAKDOWN, params);

      GeoBreakdown.Builder builder = GeoBreakdown.newBuilder().setCurrency(CURRENCY);
      int rank = 1;
      for (Map<String, Object> row : result.rows()) {
        builder.addRows(GeoRow.newBuilder()
            .setRank(rank++)
            .setCountry(Rows.getString(row, "country"))
            .setSessions(Rows.getLong(row, "sessions"))
            .setOrders(Rows.getLong(row, "orders"))
            .setRevenue(Rows.getDouble(row, "revenue")));
      }
      return builder.setMeta(meta(SQL_GEO_BREAKDOWN, range, result)).build();
    });
  }

  // ---------------------------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------------------------

  /** Runs the body and maps failures to gRPC statuses without leaking SQL or stack traces. */
  private <T> void respond(StreamObserver<T> observer, Supplier<T> body) {
    try {
      T response = body.get();
      observer.onNext(response);
      observer.onCompleted();
    } catch (StatusRuntimeException e) {
      observer.onError(e);
    } catch (BigQueryException e) {
      log.warn("BigQuery query failed: code={} reason={} message={}", e.getCode(), e.getReason(), e.getMessage());
      observer.onError(Status.UNAVAILABLE
          .withDescription("BigQuery query failed; please retry later")
          .asRuntimeException());
    } catch (RuntimeException e) {
      log.error("Unexpected failure while serving request", e);
      observer.onError(Status.INTERNAL
          .withDescription("Internal error while executing the query")
          .asRuntimeException());
    }
  }

  private QueryMeta meta(String sqlName, DateRanges.Applied range, QueryResult result) {
    return QueryMeta.newBuilder()
        .setDateRangeApplied(range.toProto())
        .setClamped(range.clamped())
        .setSqlHash(sqlLoader.hash(sqlName))
        .setBytesProcessed(result.bytesProcessed())
        .setCacheHit(result.cacheHit())
        .setTable(TABLE)
        .build();
  }

  private static Map<String, Object> single(QueryResult result) {
    return result.rows().isEmpty() ? Map.of() : result.rows().get(0);
  }

  private static Metric resolveMetric(Metric requested, Set<Metric> allowed) {
    if (requested == Metric.METRIC_UNSPECIFIED) {
      return Metric.REVENUE;
    }
    if (requested == Metric.UNRECOGNIZED || !allowed.contains(requested)) {
      throw DateRanges.invalid("metric " + requested + " is not supported here; allowed: " + allowed);
    }
    return requested;
  }

  private static String trendColumn(Metric metric) {
    return switch (metric) {
      case REVENUE -> "revenue";
      case ORDERS -> "orders";
      case UNITS -> "units";
      case SESSIONS -> "sessions";
      case PURCHASERS -> "purchasers";
      case CONVERSION_RATE -> "conversion_rate";
      default -> throw DateRanges.invalid("metric " + metric + " has no daily trend");
    };
  }
}
