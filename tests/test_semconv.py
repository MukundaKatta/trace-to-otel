"""Tests for the semconv attribute key mapping."""

from __future__ import annotations

import pytest

from trace_to_otel import semconv as sc


def test_otel_genai_cost_key():
    assert sc.attr_key(sc.COST_USD, "otel-genai") == "gen_ai.usage.cost_usd"


def test_openinference_cost_key():
    assert sc.attr_key(sc.COST_USD, "openinference") == "openinference.llm.token.cost"


def test_otel_genai_tool_name():
    assert sc.attr_key(sc.TOOL_NAME, "otel-genai") == "tool.name"


def test_openinference_tool_name():
    assert sc.attr_key(sc.TOOL_NAME, "openinference") == "openinference.tool.name"


def test_session_id_is_session_id_under_both_presets():
    assert sc.attr_key(sc.SESSION_ID, "otel-genai") == "session.id"
    assert sc.attr_key(sc.SESSION_ID, "openinference") == "session.id"


def test_unknown_semconv_raises():
    with pytest.raises(ValueError, match="unknown semconv"):
        sc.attr_key(sc.TOOL_NAME, "garbage")


def test_unknown_logical_falls_back_to_literal():
    # If a caller asks for a logical we don't know, just emit it verbatim.
    assert sc.attr_key("foo.bar", "otel-genai") == "foo.bar"


def test_supported_semconvs_returns_both():
    assert sc.supported_semconvs() == ["openinference", "otel-genai"]


def test_status_code_constants_match_otel():
    # OTLP wire format: 0 unset, 1 ok, 2 error.
    assert (sc.STATUS_UNSET, sc.STATUS_OK, sc.STATUS_ERROR) == (0, 1, 2)
