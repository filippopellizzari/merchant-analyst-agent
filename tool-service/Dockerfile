# Build from the repository root so ../proto is in the context:
#   docker build -f tool-service/Dockerfile -t merchant-tool-service .
FROM eclipse-temurin:21-jdk AS build
WORKDIR /workspace
COPY proto/ proto/
COPY tool-service/ tool-service/
WORKDIR /workspace/tool-service
RUN ./mvnw -q -B -DskipTests package

FROM gcr.io/distroless/java21-debian12
WORKDIR /app
COPY --from=build /workspace/tool-service/target/tool-service-*.jar /app/tool-service.jar
COPY --from=build /workspace/tool-service/target/dependency/ /app/lib/
ENV TOOL_SERVICE_PORT=50051
EXPOSE 50051
ENTRYPOINT ["java", "-cp", "/app/tool-service.jar:/app/lib/*", "ai.flowit.merchant.server.ToolServiceServer"]
