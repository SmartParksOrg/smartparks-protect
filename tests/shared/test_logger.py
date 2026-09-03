import json
import logging

from shared.logger import ContextFilter, JsonFormatter, get_logger, request_id_var, trace_id_var


def _record_through(filter_: ContextFilter, formatter: logging.Formatter, **fields) -> dict:
    log = get_logger("test.logger")
    handler = logging.Handler()
    captured: list[logging.LogRecord] = []
    handler.emit = captured.append  # type: ignore[method-assign]
    handler.addFilter(filter_)
    log.logger.addHandler(handler)
    log.logger.setLevel(logging.INFO)
    try:
        log.info("hello", **fields)
    finally:
        log.logger.removeHandler(handler)
    assert len(captured) == 1
    return json.loads(formatter.format(captured[0]))


def test_json_record_has_service_and_context_ids():
    request_token = request_id_var.set("req-1")
    trace_token = trace_id_var.set("trace-1")
    try:
        payload = _record_through(ContextFilter("api"), JsonFormatter(), source_event_id=42)
    finally:
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)
    assert payload["service"] == "api"
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-1"
    assert payload["trace_id"] == "trace-1"
    assert payload["source_event_id"] == 42


def test_json_record_omits_unset_ids():
    payload = _record_through(ContextFilter("worker"), JsonFormatter())
    assert "request_id" not in payload
    assert "trace_id" not in payload


def test_reserved_field_names_are_renamed_not_fatal():
    payload = _record_through(ContextFilter("decoder"), JsonFormatter(), created=3, name="x")
    assert payload["created_"] == 3 and payload["name_"] == "x"
    assert payload["logger"] == "test.logger"
