"""Tests for the OTLP/JSON exporter."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from trace_to_otel.jsonl_source import Event
from trace_to_otel.otlp import (
    OtlpExporter,
    _hex_pad,
    event_to_span,
    jsonl_to_otlp,
    span_id_for,
    trace_id_for,
)


_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def _attrs_to_dict(attrs):
    """Helper: collapse the OTLP attributes list into a plain dict."""
    out = {}
    for a in attrs:
        v = a["value"]
        out[a["key"]] = next(iter(v.values()))
    return out


def test_hex_pad_strips_only_real_prefix_and_preserves_zeros():
    # A "0x" prefix is dropped, but interior/trailing zeros must be preserved.
    assert _hex_pad("0xabc123def4567890", 16) == "abc123def4567890"
    # Leading zeros inside the value must NOT be eaten (the old lstrip bug).
    assert _hex_pad("00abc123def4567890", 16) == "abc123def4567890"
    assert _hex_pad("0x00abc123def45678", 16) == "0x00abc123def45678"[2:]
    # Short values are left-padded with zeros to the requested width.
    assert _hex_pad("ff", 16) == "0000000000000000"[:-2] + "ff"
    assert len(_hex_pad("ff", 16)) == 16


def test_trace_id_is_32_hex_and_stable():
    a = trace_id_for("session-1")
    b = trace_id_for("session-1")
    assert a == b
    assert _HEX32.match(a)


def test_trace_id_differs_per_session():
    assert trace_id_for("a") != trace_id_for("b")


def test_trace_id_handles_none():
    tid = trace_id_for(None)
    assert _HEX32.match(tid)


def test_span_id_is_16_hex_and_stable():
    ev = Event(raw={}, kind="tool_ok", tool="x", session_id="s", ts=1.0)
    a = span_id_for(ev, 0)
    b = span_id_for(ev, 0)
    assert a == b
    assert _HEX16.match(a)
    assert span_id_for(ev, 1) != a


def test_event_to_span_basic_shape():
    ev = Event(
        raw={},
        kind="tool_ok",
        tool="locus.payments.charge",
        session_id="s1",
        ts=1779638601.0,
        usd=4.99,
        latency_ms=12.0,
        args_hash="aeff9a9e",
    )
    span = event_to_span(ev, 0)
    assert span["name"] == "tool_ok.locus.payments.charge"
    assert span["kind"] == 1
    assert span["status"]["code"] == 1
    assert int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"]) == 12_000_000
    attrs = _attrs_to_dict(span["attributes"])
    assert attrs["tool.name"] == "locus.payments.charge"
    assert attrs["gen_ai.usage.cost_usd"] == 4.99
    assert attrs["session.id"] == "s1"
    assert attrs["agent.tool.args_hash"] == "aeff9a9e"


def test_event_to_span_marks_error_with_message():
    ev = Event(raw={}, kind="tool_denied", tool="x", session_id="s", error="nope")
    span = event_to_span(ev, 0)
    assert span["status"]["code"] == 2
    assert span["status"]["message"] == "nope"
    attrs = _attrs_to_dict(span["attributes"])
    assert attrs["error.message"] == "nope"


def test_event_to_span_openinference_uses_alt_keys():
    ev = Event(raw={}, kind="tool_ok", tool="x", session_id="s", usd=1.0)
    span = event_to_span(ev, 0, semconv="openinference")
    keys = {a["key"] for a in span["attributes"]}
    assert "openinference.tool.name" in keys
    assert "openinference.llm.token.cost" in keys
    assert "tool.name" not in keys


def test_event_to_span_emits_parent_span_id():
    ev = Event(raw={}, kind="tool_ok", tool="x", session_id="s", parent_id="parent-A")
    span = event_to_span(ev, 0)
    assert "parentSpanId" in span
    assert _HEX16.match(span["parentSpanId"])


def test_event_to_span_token_attrs_from_extra():
    ev = Event(
        raw={},
        kind="llm_call",
        tool="anthropic",
        session_id="s",
        extra={"input_tokens": 1024, "output_tokens": 512, "model": "sonnet-4.6"},
    )
    span = event_to_span(ev, 0)
    attrs = _attrs_to_dict(span["attributes"])
    # ints become string-encoded intValue. We unwrap them in the helper.
    assert attrs["gen_ai.usage.input_tokens"] == "1024"
    assert attrs["gen_ai.usage.output_tokens"] == "512"
    assert attrs["gen_ai.request.model"] == "sonnet-4.6"


def test_exporter_payload_resource_attrs_and_scope():
    ev = Event(raw={}, kind="tool_ok", tool="x", session_id="s", ts=1.0)
    payload = OtlpExporter(service_name="my-agent").spans_from([ev])
    assert "resourceSpans" in payload
    rs = payload["resourceSpans"][0]
    resource_attrs = _attrs_to_dict(rs["resource"]["attributes"])
    assert resource_attrs["service.name"] == "my-agent"
    assert resource_attrs["telemetry.sdk.name"] == "trace-to-otel"
    scope = rs["scopeSpans"][0]["scope"]
    assert scope["name"] == "trace-to-otel"
    assert len(rs["scopeSpans"][0]["spans"]) == 1


def test_exporter_rejects_unknown_semconv():
    with pytest.raises(ValueError):
        OtlpExporter(semconv="not-real")


def test_jsonl_to_otlp_writes_valid_json(tmp_path: Path):
    src = tmp_path / "audit.jsonl"
    src.write_text(
        "\n".join(
            [
                '{"session_id": "s1", "kind": "session_open", "ts": 1.0}',
                '{"session_id": "s1", "kind": "tool_ok", "tool": "x", "ts": 2.0, "usd": 0.1, "extra": {"latency_ms": 5}}',
            ]
        )
        + "\n"
    )
    dst = tmp_path / "out.otlp.json"
    payload = jsonl_to_otlp(str(src), str(dst), service_name="demo")
    assert dst.exists()
    loaded = json.loads(dst.read_text())
    assert loaded == payload
    spans = loaded["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 2
    assert spans[1]["name"] == "tool_ok.x"


def test_post_to_uses_urlopen(monkeypatch, tmp_path):
    calls = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls["url"] = req.full_url
        calls["body"] = req.data
        calls["headers"] = dict(req.header_items())
        return FakeResp()

    monkeypatch.setattr("trace_to_otel.otlp._urlrequest.urlopen", fake_urlopen)

    exporter = OtlpExporter(service_name="demo")
    payload = exporter.spans_from(
        [Event(raw={}, kind="tool_ok", tool="x", session_id="s", ts=1.0)]
    )
    status = exporter.post_to("http://localhost:4318/v1/traces", payload)
    assert status == 200
    assert calls["url"] == "http://localhost:4318/v1/traces"
    # Header keys come back capitalized by urllib.
    assert any(k.lower() == "content-type" for k in calls["headers"])
    decoded = json.loads(calls["body"])
    assert decoded == payload
