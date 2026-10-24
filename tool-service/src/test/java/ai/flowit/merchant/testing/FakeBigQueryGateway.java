package ai.flowit.merchant.testing;

import ai.flowit.merchant.bigquery.BigQueryGateway;
import ai.flowit.merchant.bigquery.QueryParam;
import ai.flowit.merchant.bigquery.QueryResult;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Records every call and returns canned rows per SQL resource name. */
public final class FakeBigQueryGateway implements BigQueryGateway {

  public record Call(String sqlResourceName, Map<String, QueryParam> params) {}

  private final Map<String, List<Map<String, Object>>> canned = new HashMap<>();
  private final List<Call> calls = new ArrayList<>();
  private RuntimeException failure;
  private long bytesProcessed = 1_234L;
  private boolean cacheHit = false;

  public FakeBigQueryGateway returnRows(String sqlResourceName, List<Map<String, Object>> rows) {
    canned.put(sqlResourceName, rows);
    return this;
  }

  public FakeBigQueryGateway failWith(RuntimeException exception) {
    this.failure = exception;
    return this;
  }

  public FakeBigQueryGateway withStats(long bytesProcessed, boolean cacheHit) {
    this.bytesProcessed = bytesProcessed;
    this.cacheHit = cacheHit;
    return this;
  }

  @Override
  public QueryResult run(String sqlResourceName, Map<String, QueryParam> params) {
    calls.add(new Call(sqlResourceName, Map.copyOf(params)));
    if (failure != null) {
      throw failure;
    }
    return new QueryResult(canned.getOrDefault(sqlResourceName, List.of()), bytesProcessed, cacheHit);
  }

  public List<Call> calls() {
    return List.copyOf(calls);
  }

  public Call lastCall() {
    if (calls.isEmpty()) {
      throw new AssertionError("gateway was not called");
    }
    return calls.get(calls.size() - 1);
  }

  /** Builds a row map from alternating key/value pairs; values may be null. */
  public static Map<String, Object> row(Object... keyValues) {
    if (keyValues.length % 2 != 0) {
      throw new IllegalArgumentException("row() needs key/value pairs");
    }
    Map<String, Object> row = new LinkedHashMap<>();
    for (int i = 0; i < keyValues.length; i += 2) {
      row.put((String) keyValues[i], keyValues[i + 1]);
    }
    return row;
  }
}
