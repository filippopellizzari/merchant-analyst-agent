package ai.flowit.merchant.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Map;
import org.junit.jupiter.api.Test;

class ServiceConfigTest {

  @Test
  void usesDefaultsWhenEnvIsEmpty() {
    ServiceConfig config = ServiceConfig.fromMap(Map.of());

    assertNull(config.project());
    assertEquals(50051, config.port());
    assertEquals(2_000_000_000L, config.maxBytesBilled());
    assertTrue(config.useCache());
    assertThrows(IllegalStateException.class, config::requireProject);
  }

  @Test
  void readsAllValuesFromEnv() {
    ServiceConfig config = ServiceConfig.fromMap(Map.of(
        "GCP_PROJECT", "my-project",
        "TOOL_SERVICE_PORT", "6000",
        "BQ_MAX_BYTES_BILLED", "500000",
        "BQ_USE_CACHE", "false"));

    assertEquals("my-project", config.requireProject());
    assertEquals(6000, config.port());
    assertEquals(500_000L, config.maxBytesBilled());
    assertFalse(config.useCache());
  }

  @Test
  void rejectsMalformedValues() {
    assertThrows(IllegalArgumentException.class, () -> ServiceConfig.fromMap(Map.of("TOOL_SERVICE_PORT", "abc")));
    assertThrows(IllegalArgumentException.class, () -> ServiceConfig.fromMap(Map.of("TOOL_SERVICE_PORT", "70000")));
    assertThrows(IllegalArgumentException.class, () -> ServiceConfig.fromMap(Map.of("BQ_MAX_BYTES_BILLED", "-1")));
    assertThrows(IllegalArgumentException.class, () -> ServiceConfig.fromMap(Map.of("BQ_USE_CACHE", "maybe")));
  }
}
