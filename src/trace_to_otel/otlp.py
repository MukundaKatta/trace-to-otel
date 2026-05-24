"""Build OTLP/JSON span payloads from normalized agent Events.

The output matches the OTLP/HTTP 1.0 JSON schema. You can POST it directly to
any OpenTelemetry collector that accepts ``/v1/traces`` with
``Content-Type: application/json``.

We deliberately do not depend on opentelemetry-api. The shape is small and
public, and the whole point of this library is "drop into any collector
without dragging the OTel SDK into your runtime".
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable
from urllib import request as _urlrequest

from . import semconv as sc
from .jsonl_source import Event


_LIB_NAME = "trace-to-otel"
_LIB_VERSION = "0.1.0"


def _hex_pad(s: str, width: int) -> str:
    s = s.lstrip("0x").lower()
    if len(s) >= width:
        return s[-width:]
    return s.rjust(width, "0")


def trace_id_for(session_id: str | None) -> str:
    """Derive a stable 32-hex-char trace id from a session id.

    OTLP wants a 16-byte (32 hex char) trace id. We hash the session id so that
    every event in the same session lands on the same trace, and so that two
    runs of the same agent do not collide unless the session id matches.
    """
    seed = session_id or "trace-to-otel-unknown-session"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def span_id_for(event: Event, index: int) -> str:
    """Derive a stable 16-hex-char span id for an event."""
    if event.span_id:
        return _hex_pad(hashlib.sha256(event.span_id.encode("utf-8")).hexdigest(), 16)
    # Compose a key that is unique-per-event so two tool calls in the same
    # second do not collide.
    parts = [
        str(event.session_id),
        str(event.ts),
        str(event.kind),
        str(event.tool),
        str(event.args_hash),
        str(index),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _to_nano(ts_seconds: float | None) -> int:
    if ts_seconds is None:
        return 0
    return int(ts_seconds * 1_000_000_000)


def _attr(key: str, value: Any) -> dict[str, Any]:
    """Wrap a value in the OTLP attribute envelope."""
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        # OTLP encodes intValue as a string.
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def event_to_span(
    event: Event,
    index: int,
    *,
    semconv: str = "otel-genai",
    default_duration_ms: float = 1.0,
) -> dict[str, Any]:
    """Convert one normalized Event into an OTLP JSON span dict."""
    start_ns = _to_nano(event.ts)
    if event.latency_ms is not None:
        duration_ns = int(event.latency_ms * 1_000_000)
    else:
        duration_ns = int(default_duration_ms * 1_000_000)
    end_ns = start_ns + duration_ns if start_ns else 0

    attrs: list[dict[str, Any]] = []
    attrs.append(_attr(sc.attr_key(sc.EVENT_KIND, semconv), event.kind))
    if event.tool:
        attrs.append(_attr(sc.attr_key(sc.TOOL_NAME, semconv), event.tool))
    if event.session_id:
        attrs.append(_attr(sc.attr_key(sc.SESSION_ID, semconv), event.session_id))
    if event.usd:
        attrs.append(_attr(sc.attr_key(sc.COST_USD, semconv), float(event.usd)))
    if event.args_hash:
        attrs.append(_attr(sc.attr_key(sc.ARGS_HASH, semconv), event.args_hash))
    if event.url:
        attrs.append(_attr(sc.attr_key(sc.URL, semconv), event.url))
    if event.error:
        attrs.append(_attr(sc.attr_key(sc.ERROR_MESSAGE, semconv), event.error))

    # Extra fields that often appear in gen_ai shapes. We only emit if present.
    extra = event.extra or {}
    for key_in, logical in (
        ("input_tokens", sc.INPUT_TOKENS),
        ("output_tokens", sc.OUTPUT_TOKENS),
        ("total_tokens", sc.TOTAL_TOKENS),
        ("model", sc.MODEL),
        ("system", sc.SYSTEM),
    ):
        v = extra.get(key_in)
        if v is None:
            continue
        attrs.append(_attr(sc.attr_key(logical, semconv), v))

    span: dict[str, Any] = {
        "traceId": trace_id_for(event.session_id),
        "spanId": span_id_for(event, index),
        "name": f"{event.kind}.{event.tool}" if event.tool else event.kind,
        "kind": sc.SPAN_KIND_INTERNAL,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attrs,
        "status": {
            "code": sc.STATUS_ERROR if event.is_error else sc.STATUS_OK,
        },
    }
    if event.error:
        span["status"]["message"] = event.error
    if event.parent_id:
        span["parentSpanId"] = _hex_pad(
            hashlib.sha256(event.parent_id.encode("utf-8")).hexdigest(), 16
        )
    return span


class OtlpExporter:
    """Turn an iterable of Events into an OTLP/JSON payload."""

    def __init__(
        self,
        *,
        service_name: str = "agent",
        semconv: str = "otel-genai",
        default_duration_ms: float = 1.0,
    ) -> None:
        if semconv not in sc.supported_semconvs():
            raise ValueError(
                f"unknown semconv {semconv!r}; expected one of {sc.supported_semconvs()}"
            )
        self.service_name = service_name
        self.semconv = semconv
        self.default_duration_ms = default_duration_ms

    def spans_from(self, events: Iterable[Event]) -> dict[str, Any]:
        """Build a complete OTLP/JSON ExportTraceServiceRequest dict."""
        spans = [
            event_to_span(
                ev,
                idx,
                semconv=self.semconv,
                default_duration_ms=self.default_duration_ms,
            )
            for idx, ev in enumerate(events)
        ]
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            _attr("service.name", self.service_name),
                            _attr("telemetry.sdk.name", _LIB_NAME),
                            _attr("telemetry.sdk.version", _LIB_VERSION),
                            _attr("telemetry.sdk.language", "python"),
                        ],
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": _LIB_NAME, "version": _LIB_VERSION},
                            "spans": spans,
                        },
                    ],
                },
            ],
        }

    def post_to(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
    ) -> int:
        """POST an OTLP/JSON payload to a collector. Returns the HTTP status code.

        No retry. No batching. If you need either, run a real OTel collector in
        front. The point of this method is "demo it works" not "be a client".
        """
        body = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = _urlrequest.Request(url, data=body, headers=req_headers, method="POST")
        with _urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-provided URL
            return resp.status


def jsonl_to_otlp(
    src: str,
    dst: str,
    *,
    service_name: str = "agent",
    semconv: str = "otel-genai",
    session_key: str | None = None,
    indent: int | None = 2,
) -> dict[str, Any]:
    """One-shot: read a JSONL file and write OTLP/JSON to ``dst``.

    Returns the OTLP dict so callers can introspect or POST it.
    """
    from .jsonl_source import JsonlSource

    source = JsonlSource(src, session_key=session_key)
    exporter = OtlpExporter(service_name=service_name, semconv=semconv)
    payload = exporter.spans_from(source)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=indent)
        fh.write("\n")
    return payload
