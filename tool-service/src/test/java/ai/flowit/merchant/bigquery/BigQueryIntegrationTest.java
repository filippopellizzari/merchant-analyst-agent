package ai.flowit.merchant.bigquery;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.flowit.merchant.config.ServiceConfig;
import ai.flowit.merchant.service.DateRanges;
import ai.flowit.merchant.service.MerchantAnalystService;
import ai.flowit.merchant.v1.DateRange;
import ai.flowit.merchant.v1.GetSalesSummaryRequest;
import ai.flowit.merchant.v1.MerchantAnalystGrpc;
import ai.flowit.merchant.v1.SalesSummary;
import io.grpc.ManagedChannel;
import io.grpc.Server;
import io.grpc.inprocess.InProcessChannelBuilder;
import io.grpc.inprocess.InProcessServerBuilder;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * Hits the real public dataset. Only runs with {@code -Pbq} and when {@code GCP_PROJECT} is set
 * (Application Default Credentials must be available).
 */
@Tag("bq")
@EnabledIfEnvironmentVariable(named = ServiceConfig.ENV_PROJECT, matches = ".+")
class BigQueryIntegrationTest {

  @Test
  void salesSummaryForOneWeekReturnsPlausibleNumbers() throws Exception {
    ServiceConfig config = ServiceConfig.fromEnv();
    SqlLoader loader = new SqlLoader();
    BigQueryGatewayImpl gateway = BigQueryGatewayImpl.create(config, loader);

    String name = InProcessServerBuilder.generateName();
    Server server = InProcessServerBuilder.forName(name)
        .addService(new MerchantAnalystService(gateway, loader))
        .build()
        .start();
    ManagedChannel channel = InProcessChannelBuilder.forName(name).build();
    try {
      SalesSummary summary = MerchantAnalystGrpc.newBlockingStub(channel)
          .withDeadlineAfter(120, TimeUnit.SECONDS)
          .getSalesSummary(GetSalesSummaryRequest.newBuilder()
              .setDateRange(DateRange.newBuilder().setStartDate("2020-12-01").setEndDate("2020-12-07"))
              .build());

      assertTrue(summary.getSessions() > 0, "sessions");
      assertTrue(summary.getOrders() > 0, "orders");
      assertTrue(summary.getRevenue() > 0, "revenue");
      assertTrue(summary.getPurchasingSessions() <= summary.getSessions());
      assertTrue(summary.getConversionRate() > 0 && summary.getConversionRate() < 1);
      assertEquals("2020-12-01", summary.getMeta().getDateRangeApplied().getStartDate());
      assertEquals("2020-12-07", summary.getMeta().getDateRangeApplied().getEndDate());
      assertEquals(MerchantAnalystService.TABLE, summary.getMeta().getTable());
      assertEquals(16, summary.getMeta().getSqlHash().length());
      assertTrue(summary.getMeta().getBytesProcessed() > 0 || summary.getMeta().getCacheHit());
      assertTrue(DateRanges.START.isBefore(DateRanges.END));
    } finally {
      channel.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
      server.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
    }
  }
}
