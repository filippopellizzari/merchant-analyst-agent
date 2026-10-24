package ai.flowit.merchant.config;

import java.util.Map;

/**
 * Runtime configuration read from environment variables.
 *
 * <ul>
 *   <li>{@code GCP_PROJECT} - project that is billed for the BigQuery jobs (required for the real gateway)</li>
 *   <li>{@code TOOL_SERVICE_PORT} - gRPC listen port, default 50051</li>
 *   <li>{@code BQ_MAX_BYTES_BILLED} - per-query cap passed to BigQuery, default 2 GB</li>
 *   <li>{@code BQ_USE_CACHE} - whether BigQuery may serve cached results, default true</li>
 * </ul>
 */
public record ServiceConfig(String project, int port, long maxBytesBilled, boolean useCache) {

  public static final String ENV_PROJECT = "GCP_PROJECT";
  public static final String ENV_PORT = "TOOL_SERVICE_PORT";
  public static final String ENV_MAX_BYTES_BILLED = "BQ_MAX_BYTES_BILLED";
  public static final String ENV_USE_CACHE = "BQ_USE_CACHE";

  public static final int DEFAULT_PORT = 50051;
  public static final long DEFAULT_MAX_BYTES_BILLED = 2_000_000_000L;
  public static final boolean DEFAULT_USE_CACHE = true;

  public static ServiceConfig fromEnv() {
    return fromMap(System.getenv());
  }

  public static ServiceConfig fromMap(Map<String, String> env) {
    String project = blankToNull(env.get(ENV_PROJECT));
    int port = parseInt(env.get(ENV_PORT), ENV_PORT, DEFAULT_PORT);
    long maxBytes = parseLong(env.get(ENV_MAX_BYTES_BILLED), ENV_MAX_BYTES_BILLED, DEFAULT_MAX_BYTES_BILLED);
    boolean useCache = parseBoolean(env.get(ENV_USE_CACHE), ENV_USE_CACHE, DEFAULT_USE_CACHE);
    if (port < 1 || port > 65535) {
      throw new IllegalArgumentException(ENV_PORT + " must be in 1..65535, got " + port);
    }
    if (maxBytes <= 0) {
      throw new IllegalArgumentException(ENV_MAX_BYTES_BILLED + " must be positive, got " + maxBytes);
    }
    return new ServiceConfig(project, port, maxBytes, useCache);
  }

  /** Returns the project or fails loudly when it is missing. */
  public String requireProject() {
    if (project == null) {
      throw new IllegalStateException(ENV_PROJECT + " environment variable is required");
    }
    return project;
  }

  private static String blankToNull(String value) {
    return value == null || value.isBlank() ? null : value.trim();
  }

  private static int parseInt(String raw, String name, int fallback) {
    String value = blankToNull(raw);
    if (value == null) {
      return fallback;
    }
    try {
      return Integer.parseInt(value);
    } catch (NumberFormatException e) {
      throw new IllegalArgumentException(name + " must be an integer, got '" + value + "'", e);
    }
  }

  private static long parseLong(String raw, String name, long fallback) {
    String value = blankToNull(raw);
    if (value == null) {
      return fallback;
    }
    try {
      return Long.parseLong(value.replace("_", ""));
    } catch (NumberFormatException e) {
      throw new IllegalArgumentException(name + " must be an integer, got '" + value + "'", e);
    }
  }

  private static boolean parseBoolean(String raw, String name, boolean fallback) {
    String value = blankToNull(raw);
    if (value == null) {
      return fallback;
    }
    return switch (value.toLowerCase()) {
      case "true", "1", "yes", "on" -> true;
      case "false", "0", "no", "off" -> false;
      default -> throw new IllegalArgumentException(name + " must be a boolean, got '" + value + "'");
    };
  }
}
