package ai.flowit.merchant.server;

import ai.flowit.merchant.bigquery.BigQueryGateway;
import ai.flowit.merchant.bigquery.BigQueryGatewayImpl;
import ai.flowit.merchant.bigquery.CachingBigQueryGateway;
import ai.flowit.merchant.bigquery.SqlLoader;
import ai.flowit.merchant.config.ServiceConfig;
import ai.flowit.merchant.service.MerchantAnalystService;
import ai.flowit.merchant.v1.MerchantAnalystGrpc;
import io.grpc.BindableService;
import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.health.v1.HealthCheckResponse.ServingStatus;
import io.grpc.protobuf.services.HealthStatusManager;
import io.grpc.protobuf.services.ProtoReflectionServiceV1;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** Netty gRPC server hosting {@link MerchantAnalystService}, health checks and reflection. */
public final class ToolServiceServer {

  private static final Logger log = LoggerFactory.getLogger(ToolServiceServer.class);
  private static final long SHUTDOWN_GRACE_SECONDS = 15;

  private final int port;
  private final BindableService service;
  private final HealthStatusManager health = new HealthStatusManager();
  private Server server;

  public ToolServiceServer(int port, BindableService service) {
    this.port = port;
    this.service = service;
  }

  public static void main(String[] args) throws IOException, InterruptedException {
    ServiceConfig config = ServiceConfig.fromEnv();
    SqlLoader sqlLoader = new SqlLoader();
    BigQueryGateway gateway = BigQueryGatewayImpl.create(config, sqlLoader);
    if (config.useCache()) {
      gateway = new CachingBigQueryGateway(gateway, CachingBigQueryGateway.DEFAULT_MAX_ENTRIES);
    }
    ToolServiceServer server = new ToolServiceServer(config.port(), new MerchantAnalystService(gateway, sqlLoader));
    server.start();
    log.info("tool-service listening on port {} (project={}, maxBytesBilled={}, useCache={})",
        config.port(), config.project(), config.maxBytesBilled(), config.useCache());
    server.blockUntilShutdown();
  }

  public void start() throws IOException {
    server = ServerBuilder.forPort(port)
        .addService(service)
        .addService(ProtoReflectionServiceV1.newInstance())
        .addService(health.getHealthService())
        .build()
        .start();
    health.setStatus("", ServingStatus.SERVING);
    health.setStatus(MerchantAnalystGrpc.SERVICE_NAME, ServingStatus.SERVING);
    Runtime.getRuntime().addShutdownHook(new Thread(this::stop, "grpc-shutdown"));
  }

  public void stop() {
    if (server == null) {
      return;
    }
    log.info("Shutting down tool-service");
    health.enterTerminalState();
    server.shutdown();
    try {
      if (!server.awaitTermination(SHUTDOWN_GRACE_SECONDS, TimeUnit.SECONDS)) {
        log.warn("Server did not terminate within {}s, forcing shutdown", SHUTDOWN_GRACE_SECONDS);
        server.shutdownNow();
      }
    } catch (InterruptedException e) {
      server.shutdownNow();
      Thread.currentThread().interrupt();
    }
  }

  public void blockUntilShutdown() throws InterruptedException {
    if (server != null) {
      server.awaitTermination();
    }
  }

  public int port() {
    return server == null ? port : server.getPort();
  }
}
