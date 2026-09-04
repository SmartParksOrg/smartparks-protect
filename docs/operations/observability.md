# Observability

Two layers (architecture 26.8). Application traces explain what happened in domain language and are always on: every message, command, delivery and export has a processing trace with steps and a structured error, searchable in the Trace explorer and reachable from the object it produced. Technical telemetry, spans and metrics from inside the services, is for developers and operators and is off until you point it at a collector.

## System health

Server admin, System health shows the pipeline per area (architecture 26.2): ingestion, decoding, rules and automation, integrations, device control, exports, backup and recovery. Each area has a status and indicators with a link to where you drill down: Needs attention for rejected messages and unknown devices, the Trace explorer of a project for failures by error code, the automation and integration pages for failed deliveries, Backup and recovery for the copies. Workers, stream lag, dead letters and data sources are below the areas. The rules service raises system alerts for stale workers, dead letters, consumer lag and backup problems; they reach you by email or Telegram through a server-level automation.

## Trace explorer

Network, Trace explorer in a project searches processing traces by device, DevEUI, data source, status, error code and time. A trace opens as a timeline: steps in order, each with its duration drawn against the whole, the component, the input and output references and the structured error where it stopped. Every position, measurement, event, alert, command and delivery links to its trace.

Traces are kept per class (architecture 26.9): routine telemetry `TRACE_RETENTION_ROUTINE_DAYS` (30), failed flows `TRACE_RETENTION_FAILED_DAYS` (180), commands `TRACE_RETENTION_COMMAND_DAYS` (365), audit-class traces `TRACE_RETENTION_AUDIT_DAYS` (730). The rules service applies the policy once a day in bounded batches.

## OpenTelemetry

Every Python service can export traces and metrics over OTLP/HTTP. Set `OTEL_EXPORTER_OTLP_ENDPOINT` and restart; nothing else changes. Instrumented: every API request (FastAPI), every database statement (SQLAlchemy), outbound HTTP (httpx), Redis, and one span per bus message per worker (`bus <topic>`) with the processing trace id as the attribute `protect.trace_id`, so a technical trace and an application trace can be joined by that id.

Metrics: `protect.bus.messages` (counter by topic, worker and outcome: ok, retry, crashed, dead_letter) and `protect.bus.handler.duration` (histogram in seconds by topic and worker), next to the request metrics of the FastAPI instrumentation. Stream lag and dead-letter counts are on the System health page and in the API.

### A collector on the server or a laptop

The compose profile `observability` starts `grafana/otel-lgtm`, one container with an OpenTelemetry collector, Prometheus, Tempo, Loki and Grafana:

```bash
# .env
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318
COMPOSE_PROFILES=observability
docker compose up -d
```

Grafana is on `http://localhost:3001` (admin / admin, change it). Traces are under Explore, Tempo; metrics under Explore, Prometheus. The container keeps its data in the `lgtm-data` volume. It is sized for a development machine or a small server; a production deployment points the endpoint at its own collector or a hosted service instead, which is a single variable change.

On a server the ports of the collector are bound to localhost only; reach Grafana through an SSH tunnel: `ssh -L 3001:127.0.0.1:3001 <server>`.

## Logs

Every service writes one JSON line per event to stdout with `service`, `trace_id` and `request_id`; `docker compose logs -f <service>` follows them and Loki in the observability profile can collect them from Docker. The scheduled backup jobs log to `logs/` in the application directory.
