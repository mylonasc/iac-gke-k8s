import logging
import os

logger = logging.getLogger(__name__)


def init_tracing(app) -> None:
    enabled = os.getenv("TRACING_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        logger.info("tracing.disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except Exception:
        logger.exception("tracing.init_failed")
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.warning("tracing.disabled_no_exporter_endpoint")
        return

    sample_ratio_raw = os.getenv("TRACING_SAMPLE_RATIO", "0.1")
    try:
        sample_ratio = float(sample_ratio_raw)
    except ValueError:
        sample_ratio = 0.1

    service_name = os.getenv("OTEL_SERVICE_NAME", "sandboxed-react-agent-backend")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(
        resource=resource, sampler=TraceIdRatioBased(sample_ratio)
    )
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()

    logger.info(
        "tracing.enabled",
        extra={
            "otel_endpoint": endpoint,
            "otel_service_name": service_name,
            "tracing_sample_ratio": sample_ratio,
        },
    )
