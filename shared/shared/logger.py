"""Structured logging shared by all services.

Every record carries `service`, and `trace_id` and `request_id` when they are set in the current
context. Output is one JSON object per line on stdout (`LOG_FORMAT=json`) or a readable line
(`LOG_FORMAT=text`) for development. Use `get_logger(service_name)` once per module and pass extra
fields as keyword arguments: `log.info("source event stored", source_event_id=42)`.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}
_CONTEXT_KEYS = ("request_id", "trace_id")
_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", record.name),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key in _CONTEXT_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS
            and key != "service"
            and not key.startswith("_")
            and value is not None
        }
        suffix = " " + " ".join(f"{k}={v}" for k, v in extras.items()) if extras else ""
        line = (
            f"{datetime.fromtimestamp(record.created, tz=UTC).strftime('%H:%M:%S')} "
            f"{record.levelname:<8} {getattr(record, 'service', record.name)}: "
            f"{record.getMessage()}{suffix}"
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class ContextFilter(logging.Filter):
    """Attaches the service name and the current request and trace ids to every record."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "service"):
            record.service = self.service
        record.request_id = request_id_var.get()
        record.trace_id = trace_id_var.get()
        return True


def configure_logging(service: str, level: str = "INFO", log_format: str = "json") -> None:
    """Configure the root logger once per process. Later calls only adjust the level."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if log_format == "json" else TextFormatter())
    handler.addFilter(ContextFilter(service))
    root.handlers = [handler]
    _CONFIGURED = True


class StructuredLogger(logging.LoggerAdapter[logging.Logger]):
    """Lets callers pass extra fields as keyword arguments. A field that collides with a
    LogRecord attribute (`created`, `name`, `message`, ...) gets a trailing underscore instead of
    making the logging call itself raise."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        extra = dict(self.extra or {})
        for key in list(kwargs):
            if key not in ("exc_info", "stack_info", "stacklevel", "extra"):
                value = kwargs.pop(key)
                extra[f"{key}_" if key in _STANDARD_ATTRS else key] = value
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name), {})
