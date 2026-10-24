package ai.flowit.merchant.bigquery;

import java.util.Objects;

/** A typed named query parameter, independent of the BigQuery client types so it can be used in tests. */
public record QueryParam(Kind kind, Object value) {

  public enum Kind {
    STRING,
    INT64
  }

  public QueryParam {
    Objects.requireNonNull(kind, "kind");
    Objects.requireNonNull(value, "value");
  }

  public static QueryParam string(String value) {
    return new QueryParam(Kind.STRING, value);
  }

  public static QueryParam int64(long value) {
    return new QueryParam(Kind.INT64, value);
  }

  public String asString() {
    return String.valueOf(value);
  }

  public long asLong() {
    if (value instanceof Number n) {
      return n.longValue();
    }
    return Long.parseLong(String.valueOf(value));
  }
}
