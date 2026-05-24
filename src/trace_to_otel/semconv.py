"""Semantic-convention mappings for span attribute keys.

Two presets:

* ``otel-genai``: OpenTelemetry GenAI semantic conventions
  (https://opentelemetry.io/docs/specs/semconv/gen-ai/).
* ``openinference``: Arize OpenInference conventions
  (https://arize-ai.github.io/openinference/).

The lib intentionally ships hand-rolled tables instead of importing any vendor
SDK. The set of fields we emit is small (cost, tokens, tool name, error,
session id) and both conventions are public, so a static mapping is enough.
"""

from __future__ import annotations

from typing import Final


# OpenTelemetry SpanKind enum values per the OTLP proto.
SPAN_KIND_INTERNAL: Final[int] = 1
SPAN_KIND_SERVER: Final[int] = 2
SPAN_KIND_CLIENT: Final[int] = 3

# OpenTelemetry StatusCode per the OTLP proto.
STATUS_UNSET: Final[int] = 0
STATUS_OK: Final[int] = 1
STATUS_ERROR: Final[int] = 2


# Logical attribute names we know how to emit. Concrete attribute keys depend
# on the semconv preset (otel-genai vs openinference).
TOOL_NAME = "tool_name"
COST_USD = "cost_usd"
INPUT_TOKENS = "input_tokens"
OUTPUT_TOKENS = "output_tokens"
TOTAL_TOKENS = "total_tokens"
MODEL = "model"
SYSTEM = "system"
SESSION_ID = "session_id"
ERROR_MESSAGE = "error_message"
EVENT_KIND = "event_kind"
ARGS_HASH = "args_hash"
URL = "url"


_OTEL_GENAI: Final[dict[str, str]] = {
    TOOL_NAME: "tool.name",
    COST_USD: "gen_ai.usage.cost_usd",
    INPUT_TOKENS: "gen_ai.usage.input_tokens",
    OUTPUT_TOKENS: "gen_ai.usage.output_tokens",
    TOTAL_TOKENS: "gen_ai.usage.total_tokens",
    MODEL: "gen_ai.request.model",
    SYSTEM: "gen_ai.system",
    SESSION_ID: "session.id",
    ERROR_MESSAGE: "error.message",
    EVENT_KIND: "agent.event.kind",
    ARGS_HASH: "agent.tool.args_hash",
    URL: "http.url",
}


_OPENINFERENCE: Final[dict[str, str]] = {
    TOOL_NAME: "openinference.tool.name",
    COST_USD: "openinference.llm.token.cost",
    INPUT_TOKENS: "llm.token_count.prompt",
    OUTPUT_TOKENS: "llm.token_count.completion",
    TOTAL_TOKENS: "llm.token_count.total",
    MODEL: "llm.model_name",
    SYSTEM: "llm.provider",
    SESSION_ID: "session.id",
    ERROR_MESSAGE: "exception.message",
    EVENT_KIND: "openinference.event.kind",
    ARGS_HASH: "openinference.tool.input_hash",
    URL: "http.url",
}


_PRESETS: Final[dict[str, dict[str, str]]] = {
    "otel-genai": _OTEL_GENAI,
    "openinference": _OPENINFERENCE,
}


def attr_key(logical: str, semconv: str = "otel-genai") -> str:
    """Map a logical attribute name (TOOL_NAME, COST_USD, ...) to a concrete key."""
    try:
        table = _PRESETS[semconv]
    except KeyError as e:
        raise ValueError(
            f"unknown semconv {semconv!r}; expected one of {sorted(_PRESETS)}"
        ) from e
    return table.get(logical, logical)


def supported_semconvs() -> list[str]:
    return sorted(_PRESETS)
