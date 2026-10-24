package ai.flowit.merchant.bigquery;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.flowit.merchant.service.DateRanges;
import ai.flowit.merchant.service.MerchantAnalystService;
import ai.flowit.merchant.testing.FakeBigQueryGateway;
import ai.flowit.merchant.v1.GetDailyTrendRequest;
import ai.flowit.merchant.v1.GetDatasetInfoRequest;
import ai.flowit.merchant.v1.GetFunnelRequest;
import ai.flowit.merchant.v1.GetGeoBreakdownRequest;
import ai.flowit.merchant.v1.GetSalesSummaryRequest;
import ai.flowit.merchant.v1.GetTopProductsRequest;
import ai.flowit.merchant.v1.GetTrafficBySourceRequest;
import io.grpc.stub.StreamObserver;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.function.BiConsumer;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SqlLoaderTest {

  private static final Pattern PARAM = Pattern.compile("@([A-Za-z_][A-Za-z0-9_]*)");
  private static final List<String> ALL_SQL = List.of(
      MerchantAnalystService.SQL_DATASET_INFO,
      MerchantAnalystService.SQL_SALES_SUMMARY,
      MerchantAnalystService.SQL_TOP_PRODUCTS,
      MerchantAnalystService.SQL_DAILY_TREND,
      MerchantAnalystService.SQL_TRAFFIC_BY_SOURCE,
      MerchantAnalystService.SQL_FUNNEL,
      MerchantAnalystService.SQL_GEO_BREAKDOWN);

  private final SqlLoader loader = new SqlLoader();

  @ParameterizedTest
  @ValueSource(strings = {"dataset_info", "sales_summary", "top_products", "daily_trend",
      "traffic_by_source", "funnel", "geo_breakdown"})
  void everyRpcSqlResourceExistsAndScansTheWindow(String name) {
    String sql = loader.load(name);

    assertFalse(sql.isBlank(), name + " is empty");
    assertTrue(sql.contains("`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`"), name + " must query the sample table");
    assertTrue(sql.contains("_TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix"), name + " must restrict _TABLE_SUFFIX");
  }

  @Test
  void hashIsSixteenHexCharsAndStable() {
    String hash = loader.hash("sales_summary");

    assertEquals(16, hash.length());
    assertTrue(hash.matches("[0-9a-f]{16}"), hash);
    assertEquals(hash, SqlLoader.hashText(loader.load("sales_summary")));
    assertNotEquals(hash, loader.hash("funnel"));
  }

  @Test
  void hashIsSha256Prefix() {
    // printf 'SELECT 1' | shasum -a 256 | cut -c1-16
    assertEquals("e004ebd5b5532a4b", SqlLoader.hashText("SELECT 1"));
  }

  @Test
  void missingResourceFails() {
    assertThrows(IllegalArgumentException.class, () -> loader.load("does_not_exist"));
    assertThrows(IllegalArgumentException.class, () -> loader.load("../pom"));
  }

  @Test
  void everyParamReferencedInSqlIsSuppliedByTheService() {
    FakeBigQueryGateway gateway = new FakeBigQueryGateway();
    MerchantAnalystService service = new MerchantAnalystService(gateway, loader);
    Map<String, Runnable> invocations = new LinkedHashMap<>();
    invocations.put(MerchantAnalystService.SQL_DATASET_INFO,
        () -> service.getDatasetInfo(GetDatasetInfoRequest.getDefaultInstance(), observer()));
    invocations.put(MerchantAnalystService.SQL_SALES_SUMMARY,
        () -> service.getSalesSummary(GetSalesSummaryRequest.getDefaultInstance(), observer()));
    invocations.put(MerchantAnalystService.SQL_TOP_PRODUCTS,
        () -> service.getTopProducts(GetTopProductsRequest.getDefaultInstance(), observer()));
    invocations.put(MerchantAnalystService.SQL_DAILY_TREND,
        () -> service.getDailyTrend(GetDailyTrendRequest.getDefaultInstance(), observer()));
    invocations.put(MerchantAnalystService.SQL_TRAFFIC_BY_SOURCE,
        () -> service.getTrafficBySource(GetTrafficBySourceRequest.getDefaultInstance(), observer()));
    invocations.put(MerchantAnalystService.SQL_FUNNEL,
        () -> service.getFunnel(GetFunnelRequest.getDefaultInstance(), observer()));
    invocations.put(MerchantAnalystService.SQL_GEO_BREAKDOWN,
        () -> service.getGeoBreakdown(GetGeoBreakdownRequest.getDefaultInstance(), observer()));
    assertEquals(Set.copyOf(ALL_SQL), invocations.keySet(), "every SQL resource must be exercised");

    BiConsumer<String, Set<String>> check = (name, supplied) -> {
      Set<String> referenced = referencedParams(loader.load(name));
      assertEquals(referenced, supplied, "params for " + name + " differ (referenced vs supplied)");
      assertTrue(referenced.contains(DateRanges.PARAM_START_SUFFIX), name);
      assertTrue(referenced.contains(DateRanges.PARAM_END_SUFFIX), name);
    };

    for (Map.Entry<String, Runnable> entry : invocations.entrySet()) {
      entry.getValue().run();
      FakeBigQueryGateway.Call call = gateway.lastCall();
      assertEquals(entry.getKey(), call.sqlResourceName());
      check.accept(entry.getKey(), new TreeSet<>(call.params().keySet()));
    }
  }

  private static Set<String> referencedParams(String sql) {
    Set<String> names = new TreeSet<>();
    Matcher matcher = PARAM.matcher(sql);
    while (matcher.find()) {
      names.add(matcher.group(1));
    }
    return names;
  }

  private static <T> StreamObserver<T> observer() {
    return new StreamObserver<>() {
      @Override
      public void onNext(T value) {}

      @Override
      public void onError(Throwable t) {
        throw new AssertionError("unexpected error", t);
      }

      @Override
      public void onCompleted() {}
    };
  }
}
