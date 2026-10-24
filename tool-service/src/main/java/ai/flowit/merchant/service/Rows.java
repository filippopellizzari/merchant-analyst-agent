package ai.flowit.merchant.service;

import java.util.Map;

/** Lenient accessors for row maps returned by the gateway (BigQuery types vary by column). */
final class Rows {

  private Rows() {}

  static long getLong(Map<String, Object> row, String key) {
    Object value = row.get(key);
    if (value == null) {
      return 0L;
    }
    if (value instanceof Number n) {
      return n.longValue();
    }
    return Long.parseLong(value.toString().trim());
  }

  static double getDouble(Map<String, Object> row, String key) {
    Object value = row.get(key);
    if (value == null) {
      return 0d;
    }
    if (value instanceof Number n) {
      return n.doubleValue();
    }
    return Double.parseDouble(value.toString().trim());
  }

  static String getString(Map<String, Object> row, String key) {
    Object value = row.get(key);
    return value == null ? "" : value.toString();
  }

  static double ratio(double numerator, double denominator) {
    return denominator == 0d ? 0d : numerator / denominator;
  }
}
