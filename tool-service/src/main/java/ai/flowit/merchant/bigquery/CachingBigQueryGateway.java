package ai.flowit.merchant.bigquery;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

/**
 * In-memory LRU result cache in front of another {@link BigQueryGateway}.
 *
 * <p>BigQuery does not cache queries over wildcard tables ({@code events_*}), so every call would scan
 * the dataset again. The sample dataset is static, so results never go stale. Concurrent identical calls
 * share one job; failures are not cached. Cached results report {@code bytesProcessed=0, cacheHit=true}.
 */
public final class CachingBigQueryGateway implements BigQueryGateway {

  public static final int DEFAULT_MAX_ENTRIES = 1_000;

  private record Key(String sqlResourceName, Map<String, QueryParam> params) {}

  private final BigQueryGateway delegate;
  private final Map<Key, CompletableFuture<QueryResult>> entries;

  public CachingBigQueryGateway(BigQueryGateway delegate, int maxEntries) {
    this.delegate = Objects.requireNonNull(delegate, "delegate");
    if (maxEntries < 1) {
      throw new IllegalArgumentException("maxEntries must be positive, got " + maxEntries);
    }
    this.entries = new LinkedHashMap<>(16, 0.75f, true) {
      @Override
      protected boolean removeEldestEntry(Map.Entry<Key, CompletableFuture<QueryResult>> eldest) {
        return size() > maxEntries;
      }
    };
  }

  @Override
  public QueryResult run(String sqlResourceName, Map<String, QueryParam> params) {
    Key key = new Key(sqlResourceName, Map.copyOf(params));
    CompletableFuture<QueryResult> mine = new CompletableFuture<>();
    CompletableFuture<QueryResult> existing;
    synchronized (entries) {
      existing = entries.putIfAbsent(key, mine);
    }
    if (existing != null) {
      QueryResult cached = await(existing);
      return new QueryResult(cached.rows(), 0L, true);
    }
    try {
      QueryResult result = delegate.run(sqlResourceName, params);
      mine.complete(result);
      return result;
    } catch (RuntimeException e) {
      synchronized (entries) {
        entries.remove(key, mine);
      }
      mine.completeExceptionally(e);
      throw e;
    }
  }

  int size() {
    synchronized (entries) {
      return entries.size();
    }
  }

  private static QueryResult await(CompletableFuture<QueryResult> future) {
    try {
      return future.join();
    } catch (CompletionException e) {
      if (e.getCause() instanceof RuntimeException cause) {
        throw cause;
      }
      throw e;
    }
  }
}
