package ai.flowit.merchant.bigquery;

import java.util.List;
import java.util.Map;

/**
 * Result of a query: rows keyed by column name plus the BigQuery job statistics
 * needed for {@code QueryMeta}.
 */
public record QueryResult(List<Map<String, Object>> rows, long bytesProcessed, boolean cacheHit) {

  public QueryResult {
    rows = List.copyOf(rows);
  }

  public static QueryResult empty() {
    return new QueryResult(List.of(), 0L, false);
  }
}
