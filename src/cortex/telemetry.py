"""OpenTelemetry wiring — disabled (no-op) unless OTEL_EXPORTER_OTLP_ENDPOINT set."""

import logging

from opentelemetry import trace

logger = logging.getLogger("cortex.telemetry")

_provider = None


def init_tracing(service_name: str, endpoint: str) -> None:
    """Configure OTLP/HTTP export when `endpoint` is set; else keep the
    global no-op tracer. Idempotent — repeated calls are ignored."""
    global _provider
    if _provider is not None or not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _provider = TracerProvider(
        resource=Resource({SERVICE_NAME: service_name})
    )
    _provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        )
    )
    trace.set_tracer_provider(_provider)
    logger.info("OTel tracing enabled → %s (service=%s)", endpoint, service_name)


def tracer() -> trace.Tracer:
    return trace.get_tracer("cortex")


async def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.shutdown()
