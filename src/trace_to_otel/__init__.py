"""trace-to-otel: convert agent JSONL audit logs into OTLP JSON spans.

Public API:

    from trace_to_otel import jsonl_to_otlp, JsonlSource, OtlpExporter, Event

    # One-shot file conversion
    jsonl_to_otlp("runs/audit.jsonl", "runs/spans.otlp.json",
                  service_name="my-agent", semconv="otel-genai")

    # Programmatic
    src = JsonlSource("runs/audit.jsonl")
    exporter = OtlpExporter(service_name="my-agent")
    payload = exporter.spans_from(src)
    exporter.post_to("http://localhost:4318/v1/traces", payload)
"""

from __future__ import annotations

from .jsonl_source import Event, JsonlSource, normalize, parse_lines
from .otlp import OtlpExporter, event_to_span, jsonl_to_otlp, span_id_for, trace_id_for
from .semconv import supported_semconvs

__all__ = [
    "Event",
    "JsonlSource",
    "OtlpExporter",
    "event_to_span",
    "jsonl_to_otlp",
    "normalize",
    "parse_lines",
    "span_id_for",
    "supported_semconvs",
    "trace_id_for",
]

__version__ = "0.1.0"
