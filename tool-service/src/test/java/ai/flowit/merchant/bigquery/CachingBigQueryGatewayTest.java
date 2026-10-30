package ai.flowit.merchant.bigquery;

import static ai.flowit.merchant.testing.FakeBigQueryGateway.row;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.flowit.merchant.testing.FakeBigQueryGateway;
import com.google.cloud.bigquery.BigQueryException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class CachingBigQueryGatewayTest {

  private static final Map<String, QueryParam> DEC = Map.of(
      "start_suffix", QueryParam.string("20201201"), "end_suffix", QueryParam.string("20201231"));
  private static final Map<String, QueryParam> JAN = Map.of(
      "start_suffix", QueryParam.string("20210101"), "end_suffix", QueryParam.string("20210131"));

  @Test
  void repeatedCallHitsCacheAndReportsZeroBytes() {
    FakeBigQueryGateway fake = new FakeBigQueryGateway()
        .returnRows("sales_summary", List.of(row("revenue", 10.0)))
        .withStats(385_000_000L, false);
    CachingBigQueryGateway gateway = new CachingBigQueryGateway(fake, 10);

    QueryResult first = gateway.run("sales_summary", DEC);
    QueryResult second = gateway.run("sales_summary", DEC);

    assertEquals(1, fake.calls().size());
    assertEquals(385_000_000L, first.bytesProcessed());
    assertFalse(first.cacheHit());
    assertEquals(0L, second.bytesProcessed());
    assertTrue(second.cacheHit());
    assertEquals(first.rows(), second.rows());
  }

  @Test
  void differentStatementOrParamsMiss() {
    FakeBigQueryGateway fake = new FakeBigQueryGateway();
    CachingBigQueryGateway gateway = new CachingBigQueryGateway(fake, 10);

    gateway.run("sales_summary", DEC);
    gateway.run("sales_summary", JAN);
    gateway.run("funnel", DEC);

    assertEquals(3, fake.calls().size());
  }

  @Test
  void failuresAreNotCached() {
    BigQueryException boom = new BigQueryException(503, "boom");
    FakeBigQueryGateway fake = new FakeBigQueryGateway().failWith(boom);
    CachingBigQueryGateway gateway = new CachingBigQueryGateway(fake, 10);

    assertSame(boom, assertThrows(BigQueryException.class, () -> gateway.run("funnel", DEC)));
    fake.failWith(null);
    gateway.run("funnel", DEC);

    assertEquals(2, fake.calls().size());
    assertEquals(1, gateway.size());
  }

  @Test
  void evictsLeastRecentlyUsed() {
    FakeBigQueryGateway fake = new FakeBigQueryGateway();
    CachingBigQueryGateway gateway = new CachingBigQueryGateway(fake, 2);

    gateway.run("a", DEC);
    gateway.run("b", DEC);
    gateway.run("a", DEC); // touch a, so b is the eldest
    gateway.run("c", DEC); // evicts b
    gateway.run("a", DEC);
    gateway.run("b", DEC);

    assertEquals(List.of("a", "b", "c", "b"),
        fake.calls().stream().map(FakeBigQueryGateway.Call::sqlResourceName).toList());
    assertEquals(2, gateway.size());
  }

  @Test
  void concurrentIdenticalCallsShareOneJob() throws Exception {
    CountDownLatch release = new CountDownLatch(1);
    AtomicInteger jobs = new AtomicInteger();
    BigQueryGateway slow = (name, params) -> {
      jobs.incrementAndGet();
      try {
        release.await(5, TimeUnit.SECONDS);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
      }
      return new QueryResult(List.of(row("revenue", 1.0)), 100L, false);
    };
    CachingBigQueryGateway gateway = new CachingBigQueryGateway(slow, 10);

    ExecutorService pool = Executors.newFixedThreadPool(8);
    try {
      List<Future<QueryResult>> futures = new ArrayList<>();
      for (int i = 0; i < 8; i++) {
        futures.add(pool.submit(() -> gateway.run("sales_summary", DEC)));
      }
      Thread.sleep(200);
      release.countDown();
      long hits = 0;
      for (Future<QueryResult> f : futures) {
        if (f.get(5, TimeUnit.SECONDS).cacheHit()) {
          hits++;
        }
      }
      assertEquals(1, jobs.get());
      assertEquals(7, hits);
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void rejectsNonPositiveSize() {
    assertThrows(IllegalArgumentException.class, () -> new CachingBigQueryGateway(new FakeBigQueryGateway(), 0));
  }
}
