package ai.flowit.merchant.testing;

import ai.flowit.merchant.bigquery.SqlLoader;
import ai.flowit.merchant.service.MerchantAnalystService;
import ai.flowit.merchant.v1.MerchantAnalystGrpc;
import io.grpc.ManagedChannel;
import io.grpc.Server;
import io.grpc.inprocess.InProcessChannelBuilder;
import io.grpc.inprocess.InProcessServerBuilder;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.extension.AfterEachCallback;
import org.junit.jupiter.api.extension.BeforeEachCallback;
import org.junit.jupiter.api.extension.ExtensionContext;

/** Starts an in-process gRPC server around a fake gateway for each test and exposes a blocking stub. */
public final class InProcessServerExtension implements BeforeEachCallback, AfterEachCallback {

  private FakeBigQueryGateway gateway;
  private Server server;
  private ManagedChannel channel;
  private MerchantAnalystGrpc.MerchantAnalystBlockingStub stub;

  @Override
  public void beforeEach(ExtensionContext context) throws IOException {
    gateway = new FakeBigQueryGateway();
    String name = InProcessServerBuilder.generateName();
    server = InProcessServerBuilder.forName(name)
        .directExecutor()
        .addService(new MerchantAnalystService(gateway, new SqlLoader()))
        .build()
        .start();
    channel = InProcessChannelBuilder.forName(name).directExecutor().build();
    stub = MerchantAnalystGrpc.newBlockingStub(channel);
  }

  @Override
  public void afterEach(ExtensionContext context) throws InterruptedException {
    channel.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
    server.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
  }

  public FakeBigQueryGateway gateway() {
    return gateway;
  }

  public MerchantAnalystGrpc.MerchantAnalystBlockingStub stub() {
    return stub;
  }
}
