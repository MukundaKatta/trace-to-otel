# trace-to-otel

[![PyPI version](https://img.shields.io/pypi/v/trace-to-otel.svg)](https://pypi.org/project/trace-to-otel/)
[![Python](https://img.shields.io/pypi/pyversions/trace-to-otel.svg)](https://pypi.org/project/trace-to-otel/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Convert an agent JSONL audit log (from `agenttrace`, `agentleash`, `agentsnap`, `agent-step-log`, or any generic log with a `parent_id`) into OTLP/JSON spans you can POST to any OpenTelemetry collector. Zero runtime dependencies. No need to drop the OpenTelemetry SDK into your runtime.

```bash
pip install trace-to-otel
```

## What it does

You have a JSONL file your agent wrote:

```json
{"ts":1779638601.262143,"session_id":"abc12","kind":"session_open"}
{"ts":1779638601.265488,"session_id":"abc12","kind":"tool_ok","tool":"locus.payments.charge","usd":4.99,"extra":{"latency_ms":12}}
{"ts":1779638601.266174,"session_id":"abc12","kind":"budget_denied","tool":"locus.payments.charge","usd":7.0,"error":"budget exceeded"}
```

You want to see it in Grafana, Datadog, Jaeger, Honeycomb, or any OTel-aware backend. `trace-to-otel` turns those lines into a standard OTLP/JSON payload:

```bash
python -m trace_to_otel examples/sample_audit.jsonl spans.otlp.json
```

```json
{
  "resourceSpans": [{
    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "agent"}}]},
    "scopeSpans": [{
      "scope": {"name": "trace-to-otel", "version": "0.1.0"},
      "spans": [{
        "traceId": "...",
        "spanId": "...",
        "name": "tool_ok.locus.payments.charge",
        "startTimeUnixNano": "1779638601265488000",
        "endTimeUnixNano": "1779638601277488000",
        "kind": 1,
        "status": {"code": 1},
        "attributes": [
          {"key": "tool.name", "value": {"stringValue": "locus.payments.charge"}},
          {"key": "gen_ai.usage.cost_usd", "value": {"doubleValue": 4.99}},
          {"key": "session.id", "value": {"stringValue": "abc12"}}
        ]
      }]
    }]
  }]
}
```

Pipe that file at any OTLP/HTTP collector (`http://localhost:4318/v1/traces`) and your audit log lights up in whatever tracing UI you already use.

## Programmatic API

```python
from trace_to_otel import JsonlSource, OtlpExporter, jsonl_to_otlp

# One-shot file conversion
jsonl_to_otlp(
    src="runs/audit.jsonl",
    dst="runs/spans.otlp.json",
    service_name="my-agent",
    semconv="otel-genai",
)

# Streaming / programmatic
src = JsonlSource("runs/audit.jsonl", session_key="session_id")
exporter = OtlpExporter(service_name="my-agent", semconv="otel-genai")
payload = exporter.spans_from(src)

# Optionally POST to a real collector with no SDK
exporter.post_to("http://localhost:4318/v1/traces", payload)
```

## Recognized log shapes

| shape | recognized fields |
|---|---|
| agenttrace | `kind`, `tool`, `latency_ms`, `cost_usd`, `parent_span_id`, `session_id` |
| agentleash | `ts`, `session_id`, `kind`, `tool`, `args_hash`, `usd`, `error`, `extra.latency_ms` |
| agentsnap | top-level object with a `steps` list |
| agent-step-log | `ts`, `step`, `role`, `content` |
| generic | any JSONL with `parent_id` or `parent_span_id` |

## Semantic conventions

Pick the attribute-key set that matches your backend:

| `semconv=` | cost key | tool key | session key |
|---|---|---|---|
| `otel-genai` (default) | `gen_ai.usage.cost_usd` | `tool.name` | `session.id` |
| `openinference` | `openinference.llm.token.cost` | `openinference.tool.name` | `session.id` |

The `otel-genai` preset matches the OpenTelemetry GenAI semantic conventions ([spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/)). `openinference` matches the Arize OpenInference conventions, which Phoenix and Arize use.

If you need to translate between the two on the Rust side, the sibling crate [otel-genai-bridge-rs](https://crates.io/crates/otel-genai-bridge-rs) does the same mapping for telemetry attributes.

## What gets mapped

| log field | OTLP span field |
|---|---|
| `ts` | `startTimeUnixNano` |
| `latency_ms` (or `extra.latency_ms`) | `endTimeUnixNano - startTimeUnixNano` |
| `session_id` | `traceId` (sha256 of session id, first 16 bytes) and `session.id` attribute |
| `span_id` | `spanId` (sha256 of span id, first 8 bytes) |
| `parent_span_id` | `parentSpanId` |
| `tool` | span `name` prefix and `tool.name` attribute |
| `kind` | span `name` prefix and `agent.event.kind` attribute |
| `usd` / `cost_usd` | `gen_ai.usage.cost_usd` attribute |
| `error` (or `extra.error`) | `status.code = ERROR` + `error.message` attribute |
| `tool_denied`, `budget_denied`, `egress_denied`, `rate_limited`, `policy_denied`, `blocked` | `status.code = ERROR` (even with no error string) |
| `args_hash` | `agent.tool.args_hash` attribute |
| `url` | `http.url` attribute |
| `extra.input_tokens`, `extra.output_tokens`, `extra.total_tokens`, `extra.model`, `extra.system` | `gen_ai.usage.*`, `gen_ai.request.model`, `gen_ai.system` |

## CLI

```
trace-to-otel <jsonl> [out.otlp.json] [--service-name NAME]
                       [--semconv otel-genai|openinference]
                       [--session-key FIELD]
                       [--post URL]
```

Use `-` (the default) as the output to stream to stdout. Pipe into `jq`, `curl`, anything.

```bash
trace-to-otel runs/audit.jsonl | curl -H "Content-Type: application/json" \
  --data @- http://localhost:4318/v1/traces
```

## Why not use the OTel SDK?

The OpenTelemetry SDK is excellent if you are instrumenting a live service. If you already have an audit log on disk and you want to replay it into a collector, you do not need a SDK, a tracer provider, a span processor, or a batch exporter. You need to format the bytes correctly and POST them. That is what this library does.

The OTLP/HTTP JSON encoding is a stable, public protobuf-derived schema. Any collector that speaks OTLP/HTTP (and that is most of them) accepts it as-is.

## Related libraries

- [trace-tree](https://github.com/MukundaKatta/trace-tree): same input shapes, ASCII tree output for a terminal.
- [agenttrace](https://github.com/MukundaKatta/agenttrace): cost+latency tracking for agent runs.
- [agentleash](https://github.com/MukundaKatta/agentleash): safety harness for money-making AI agents.
- [agentsnap](https://github.com/MukundaKatta/agentsnap): snapshot tests for AI agents.
- [otel-genai-bridge-rs](https://crates.io/crates/otel-genai-bridge-rs): Rust crate that translates semconv attributes between OpenInference and OTel GenAI conventions.

## License

MIT. See [LICENSE](LICENSE).
