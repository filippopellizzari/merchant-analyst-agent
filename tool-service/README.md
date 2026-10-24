# tool-service

Java 21 gRPC service implementing `merchant.v1.MerchantAnalyst` (see `../proto/merchant/v1/analyst.proto`).
Every RPC runs one hand-written, parameterised SQL statement from `src/main/resources/sql/` against
`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` and attaches `QueryMeta` provenance
(applied date range, clamped flag, SQL hash, bytes processed, cache hit).

## Prerequisites

- JDK 21 (`export JAVA_HOME=$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home` on macOS/Homebrew)
- Google Application Default Credentials for running against BigQuery (`gcloud auth application-default login`)

The Maven wrapper downloads Maven 3.9.9; protoc and the gRPC plugin are fetched by the build from Maven Central.

## Build and test

```bash
./mvnw -q test                      # unit tests (fake BigQuery gateway, in-process gRPC)
./mvnw -q -DskipTests package       # target/tool-service-*.jar + target/dependency/
GCP_PROJECT=my-project ./mvnw -Pbq test   # also runs the @Tag("bq") test against the real dataset
```

## Run

```bash
export GCP_PROJECT=my-project
./mvnw -q -DskipTests exec:java
# or, after package:
java -cp "target/tool-service-0.1.0-SNAPSHOT.jar:target/dependency/*" ai.flowit.merchant.server.ToolServiceServer
```

Docker (build from the repository root so the proto is in the context):

```bash
docker build -f tool-service/Dockerfile -t merchant-tool-service .
docker run --rm -p 50051:50051 -e GCP_PROJECT=my-project \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/creds.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/creds.json merchant-tool-service
```

## Environment variables

| Variable              | Default         | Purpose                                              |
|-----------------------|-----------------|------------------------------------------------------|
| `GCP_PROJECT`         | (required)      | Project billed for BigQuery jobs                      |
| `TOOL_SERVICE_PORT`   | `50051`         | gRPC listen port                                      |
| `BQ_MAX_BYTES_BILLED` | `2000000000`    | `maximumBytesBilled` cap per query (2 GB)             |
| `BQ_USE_CACHE`        | `true`          | Allow BigQuery to serve cached results                |

## Calling it

Server reflection and the standard health service are registered, so `grpcurl` works without the proto:

```bash
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext localhost:50051 grpc.health.v1.Health/Check
grpcurl -plaintext -d '{"date_range":{"start_date":"2020-12-01","end_date":"2020-12-31"}}' \
  localhost:50051 merchant.v1.MerchantAnalyst/GetSalesSummary
grpcurl -plaintext -d '{"metric":"UNITS","limit":5}' \
  localhost:50051 merchant.v1.MerchantAnalyst/GetTopProducts
```

Date ranges are inclusive `YYYY-MM-DD`; missing bounds are filled with the dataset window
(2020-11-01 .. 2021-01-31) and out-of-window bounds are clamped (`meta.clamped = true`).
Invalid dates, `start_date > end_date`, limits outside 1..50 and unsupported metrics return
`INVALID_ARGUMENT`; BigQuery failures return `UNAVAILABLE`.

## Layout

```
src/main/java/ai/flowit/merchant/
  config/ServiceConfig            env-based configuration
  bigquery/BigQueryGateway        interface used by the service
  bigquery/BigQueryGatewayImpl    Google client implementation (named params, bytes cap, cache flag)
  bigquery/SqlLoader              loads sql/<name>.sql from the classpath, SHA-256 prefix for sql_hash
  service/DateRanges              window constants, fill/clamp/validate, _TABLE_SUFFIX params
  service/MerchantAnalystService  the 7 RPCs
  server/ToolServiceServer        Netty server + reflection + health, graceful shutdown
src/main/resources/sql/*.sql      one statement per RPC
src/test/java/...                 JUnit 5 tests with FakeBigQueryGateway and an in-process gRPC server
```
