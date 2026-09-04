"""Technical telemetry (architecture 26.8): OpenTelemetry traces and metrics for developers and
operators, exported over OTLP/HTTP only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Application
traces (`ProcessingTrace`) remain the administrator's view; every span carries the processing
trace id (`protect.trace_id`) so the two layers can be joined in Grafana or any OTLP backend.

`configure_telemetry(service)` runs once at process start. It installs the SDK providers and
instruments SQLAlchemy, httpx and redis. The API adds the FastAPI instrumentation itself.
The bus records one span and two metrics per handled message (`shared.bus`).
"""

import os
from typing import Any

from opentelemetry import metrics, trace

from shared.config import get_settings
from shared.database import get_engine
from shared.logger import get_logger
from shared.version import __version__

log = get_logger("telemetry")

tracer = trace.get_tracer("smartparks-protect")
meter = metrics.get_meter("smartparks-protect")
bus_messages = meter.create_counter(
    "protect.bus.messages",
    unit="1",
    description="Bus messages handled, by topic, worker and outcome",
)
bus_handler_duration = meter.create_histogram(
    "protect.bus.handler.duration",
    unit="s",
    description="Time a worker spent on one bus message, by topic and worker",
)

_configured = False


def telemetry_enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def configure_telemetry(service: str) -> bool:
    """Install the OpenTelemetry SDK for this process. Returns False, and changes nothing,
    when no OTLP endpoint is configured."""
    global _configured
    if _configured:
        return True
    if not telemetry_enabled():
        return False
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": f"protect-{service}",
            "service.version": __version__,
            "deployment.environment.name": get_settings().environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]
        )
    )
    SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()
    _configured = True
    log.info(
        "telemetry enabled", service=service, endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
    )
    return True


def annotate_span(**attributes: Any) -> None:
    """Attributes on the current span, if any (a no-op without the SDK)."""
    span = trace.get_current_span()
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(
                key, str(value) if not isinstance(value, bool | int | float) else value
            )
