import contextlib
import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime


_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
_SESSION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_id", default=None
)
_TOOL_CALL_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tool_call_id", default=None
)


_STANDARD_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _read_pod_metadata() -> dict[str, str]:
    pod_name = os.getenv("POD_NAME") or os.getenv("HOSTNAME") or "unknown"
    pod_namespace = os.getenv("POD_NAMESPACE") or "unknown"
    node_name = os.getenv("NODE_NAME") or "unknown"
    return {
        "pod_name": pod_name,
        "pod_namespace": pod_namespace,
        "node_name": node_name,
    }


_POD_METADATA = _read_pod_metadata()
_LOGGING_CONFIGURED = False


def _trace_context_fields() -> dict[str, str]:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if not span:
            return {}
        span_context = span.get_span_context()
        if not span_context or not span_context.is_valid:
            return {}
        return {
            "trace_id": f"{span_context.trace_id:032x}",
            "span_id": f"{span_context.span_id:016x}",
        }
    except Exception:
        return {}


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


@contextlib.contextmanager
def bind_context(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    tool_call_id: str | None = None,
):
    tokens: list[
        tuple[contextvars.ContextVar[str | None], contextvars.Token[str | None]]
    ] = []
    if request_id is not None:
        tokens.append((_REQUEST_ID, _REQUEST_ID.set(request_id)))
    if session_id is not None:
        tokens.append((_SESSION_ID, _SESSION_ID.set(session_id)))
    if tool_call_id is not None:
        tokens.append((_TOOL_CALL_ID, _TOOL_CALL_ID.set(tool_call_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            **_POD_METADATA,
            "request_id": _REQUEST_ID.get(),
            "session_id": _SESSION_ID.get(),
            "tool_call_id": _TOOL_CALL_ID.get(),
        }
        event.update(_trace_context_fields())

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_KEYS or key.startswith("_"):
                continue
            event[key] = value

        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)

        return json.dumps(event, ensure_ascii=True)


def configure_logging() -> None:
    global _LOGGING_CONFIGURED
    root_logger = logging.getLogger()
    if _LOGGING_CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(level)

    _LOGGING_CONFIGURED = True
