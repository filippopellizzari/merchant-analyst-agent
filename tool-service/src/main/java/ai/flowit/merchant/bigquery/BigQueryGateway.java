package ai.flowit.merchant.bigquery;

import java.util.Map;

/** Executes one of the hand-written SQL statements shipped in {@code src/main/resources/sql}. */
public interface BigQueryGateway {

  /**
   * Runs the statement named {@code sqlResourceName} (without the {@code .sql} suffix) with the given
   * named parameters.
   *
   * @throws com.google.cloud.bigquery.BigQueryException when BigQuery rejects or fails the job
   */
  QueryResult run(String sqlResourceName, Map<String, QueryParam> params);
}
