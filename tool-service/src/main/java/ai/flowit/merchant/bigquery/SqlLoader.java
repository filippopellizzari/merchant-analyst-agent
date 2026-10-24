package ai.flowit.merchant.bigquery;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Loads SQL statements from the classpath ({@code sql/<name>.sql}) and hashes them for provenance. */
public final class SqlLoader {

  public static final int HASH_LENGTH = 16;
  private static final String RESOURCE_PREFIX = "sql/";
  private static final String RESOURCE_SUFFIX = ".sql";

  private final Map<String, String> cache = new ConcurrentHashMap<>();

  /** Returns the SQL text for the given resource name, or throws if the resource does not exist. */
  public String load(String name) {
    return cache.computeIfAbsent(name, SqlLoader::read);
  }

  /** First {@value #HASH_LENGTH} hex characters of the SHA-256 of the SQL text. */
  public String hash(String name) {
    return hashText(load(name));
  }

  public static String hashText(String sql) {
    try {
      MessageDigest digest = MessageDigest.getInstance("SHA-256");
      byte[] bytes = digest.digest(sql.getBytes(StandardCharsets.UTF_8));
      return HexFormat.of().formatHex(bytes).substring(0, HASH_LENGTH);
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException("SHA-256 not available", e);
    }
  }

  public static String resourcePath(String name) {
    return RESOURCE_PREFIX + name + RESOURCE_SUFFIX;
  }

  private static String read(String name) {
    if (name == null || name.isBlank() || name.contains("/") || name.contains("..")) {
      throw new IllegalArgumentException("Invalid SQL resource name: " + name);
    }
    String path = resourcePath(name);
    ClassLoader loader = SqlLoader.class.getClassLoader();
    try (InputStream in = loader.getResourceAsStream(path)) {
      if (in == null) {
        throw new IllegalArgumentException("SQL resource not found on classpath: " + path);
      }
      return new String(in.readAllBytes(), StandardCharsets.UTF_8);
    } catch (IOException e) {
      throw new UncheckedIOException("Failed to read SQL resource " + path, e);
    }
  }
}
