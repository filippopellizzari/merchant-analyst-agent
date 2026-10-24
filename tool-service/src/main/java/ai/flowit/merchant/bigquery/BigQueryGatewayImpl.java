package ai.flowit.merchant.bigquery;

import ai.flowit.merchant.config.ServiceConfig;
import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.BigQueryError;
import com.google.cloud.bigquery.BigQueryException;
import com.google.cloud.bigquery.BigQueryOptions;
import com.google.cloud.bigquery.Field;
import com.google.cloud.bigquery.FieldList;
import com.google.cloud.bigquery.FieldValue;
import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.Job;
import com.google.cloud.bigquery.JobId;
import com.google.cloud.bigquery.JobInfo;
import com.google.cloud.bigquery.JobStatistics.QueryStatistics;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.QueryParameterValue;
import com.google.cloud.bigquery.StandardSQLTypeName;
import com.google.cloud.bigquery.TableResult;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** {@link BigQueryGateway} backed by the Google Cloud BigQuery client. */
public final class BigQueryGatewayImpl implements BigQueryGateway {

  private static final Logger log = LoggerFactory.getLogger(BigQueryGatewayImpl.class);
  private static final String JOB_PREFIX = "merchant-analyst-";

  private final BigQuery bigQuery;
  private final SqlLoader sqlLoader;
  private final long maxBytesBilled;
  private final boolean useCache;

  public BigQueryGatewayImpl(BigQuery bigQuery, SqlLoader sqlLoader, long maxBytesBilled, boolean useCache) {
    this.bigQuery = Objects.requireNonNull(bigQuery, "bigQuery");
    this.sqlLoader = Objects.requireNonNull(sqlLoader, "sqlLoader");
    this.maxBytesBilled = maxBytesBilled;
    this.useCache = useCache;
  }

  /** Builds a gateway using Application Default Credentials and the configured project. */
  public static BigQueryGatewayImpl create(ServiceConfig config, SqlLoader sqlLoader) {
    BigQuery client = BigQueryOptions.newBuilder()
        .setProjectId(config.requireProject())
        .build()
        .getService();
    return new BigQueryGatewayImpl(client, sqlLoader, config.maxBytesBilled(), config.useCache());
  }

  @Override
  public QueryResult run(String sqlResourceName, Map<String, QueryParam> params) {
    String sql = sqlLoader.load(sqlResourceName);
    QueryJobConfiguration.Builder builder = QueryJobConfiguration.newBuilder(sql)
        .setUseLegacySql(false)
        .setMaximumBytesBilled(maxBytesBilled)
        .setUseQueryCache(useCache);
    params.forEach((name, param) -> builder.addNamedParameter(name, toParameterValue(param)));

    JobId jobId = JobId.of(JOB_PREFIX + sqlResourceName + "-" + UUID.randomUUID());
    long startedAt = System.nanoTime();
    Job job = bigQuery.create(JobInfo.of(jobId, builder.build()));
    Job completed;
    TableResult result;
    try {
      completed = job.waitFor();
      if (completed == null) {
        throw new BigQueryException(404, "BigQuery job " + jobId.getJob() + " no longer exists");
      }
      BigQueryError error = completed.getStatus().getError();
      if (error != null) {
        throw new BigQueryException(400, error.getMessage(), error);
      }
      result = completed.getQueryResults();
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new BigQueryException(0, "Interrupted while waiting for BigQuery job " + jobId.getJob());
    }
    QueryStatistics stats = completed.getStatistics();
    long bytesProcessed = stats.getTotalBytesProcessed() == null ? 0L : stats.getTotalBytesProcessed();
    boolean cacheHit = Boolean.TRUE.equals(stats.getCacheHit());
    List<Map<String, Object>> rows = toRows(result.getSchema() == null ? null : result.getSchema().getFields(),
        result.iterateAll());

    log.info("bq query={} rows={} bytesProcessed={} cacheHit={} elapsedMs={}", sqlResourceName, rows.size(),
        bytesProcessed, cacheHit, (System.nanoTime() - startedAt) / 1_000_000);
    return new QueryResult(rows, bytesProcessed, cacheHit);
  }

  static QueryParameterValue toParameterValue(QueryParam param) {
    return switch (param.kind()) {
      case STRING -> QueryParameterValue.string(param.asString());
      case INT64 -> QueryParameterValue.int64(param.asLong());
    };
  }

  /** Converts BigQuery rows to plain maps keyed by column name using the schema's standard SQL types. */
  static List<Map<String, Object>> toRows(FieldList fields, Iterable<FieldValueList> values) {
    List<Map<String, Object>> rows = new ArrayList<>();
    if (fields == null) {
      return rows;
    }
    for (FieldValueList row : values) {
      Map<String, Object> mapped = new LinkedHashMap<>();
      for (int i = 0; i < fields.size(); i++) {
        Field field = fields.get(i);
        mapped.put(field.getName(), toJavaValue(field, row.get(i)));
      }
      rows.add(mapped);
    }
    return rows;
  }

  private static Object toJavaValue(Field field, FieldValue value) {
    if (value == null || value.isNull()) {
      return null;
    }
    StandardSQLTypeName type = field.getType().getStandardType();
    return switch (type) {
      case INT64 -> value.getLongValue();
      case FLOAT64, NUMERIC, BIGNUMERIC -> value.getDoubleValue();
      case BOOL -> value.getBooleanValue();
      default -> value.getStringValue();
    };
  }
}
