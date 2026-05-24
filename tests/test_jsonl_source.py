"""Tests for the JSONL parser and Event normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trace_to_otel.jsonl_source import (
    Event,
    JsonlSource,
    normalize,
    parse_lines,
)


def test_normalize_agentleash_shape():
    rec = {
        "ts": 1779638601.265,
        "session_id": "abc12",
        "kind": "tool_ok",
        "tool": "locus.payments.charge",
        "args_hash": "aeff9a9e",
        "url": None,
        "usd": 4.99,
        "error": None,
        "extra": {"latency_ms": 12},
    }
    ev = normalize(rec)
    assert ev.kind == "tool_ok"
    assert ev.tool == "locus.payments.charge"
    assert ev.session_id == "abc12"
    assert ev.usd == 4.99
    assert ev.latency_ms == 12
    assert ev.args_hash == "aeff9a9e"
    assert ev.is_error is False


def test_normalize_pulls_error_from_extra():
    rec = {"kind": "tool_ok", "tool": "x", "extra": {"error": "boom"}}
    ev = normalize(rec)
    assert ev.error == "boom"
    assert ev.is_error is True


def test_denied_kind_marks_error_even_without_error_string():
    ev = normalize({"kind": "tool_denied", "tool": "x"})
    assert ev.is_error is True


def test_normalize_agenttrace_aliases():
    rec = {
        "event": "llm_call",
        "tool_name": "anthropic.messages.create",
        "parent_span_id": "parent-1",
        "span_id": "span-2",
        "cost_usd": 0.03,
        "latency_ms": 412.5,
        "session_id": "run-9",
    }
    ev = normalize(rec)
    assert ev.kind == "llm_call"
    assert ev.tool == "anthropic.messages.create"
    assert ev.parent_id == "parent-1"
    assert ev.span_id == "span-2"
    assert ev.usd == 0.03
    assert ev.latency_ms == 412.5


def test_normalize_unknown_shape_still_works():
    ev = normalize({"some_weird_field": 1})
    assert ev.kind == "event"
    assert ev.tool is None
    assert ev.usd == 0.0
    assert ev.is_error is False


def test_parse_lines_skips_blank_and_flags_bad_json():
    lines = [
        "",
        '{"kind": "session_open", "session_id": "a"}',
        "   ",
        "{not valid json",
        '{"kind": "tool_ok", "tool": "x"}',
    ]
    events = parse_lines(lines)
    assert [e.kind for e in events] == ["session_open", "parse_error", "tool_ok"]
    assert events[1].error == "invalid json"


def test_parse_agentsnap_explodes_steps():
    lines = [
        json.dumps(
            {
                "session_id": "snap-1",
                "ts": 100.0,
                "steps": [
                    {"kind": "tool_ok", "tool": "search"},
                    {"kind": "tool_ok", "tool": "summarize"},
                ],
            }
        )
    ]
    events = parse_lines(lines)
    # session_open + two tool_ok
    assert [e.kind for e in events] == ["session_open", "tool_ok", "tool_ok"]
    assert all(e.session_id == "snap-1" for e in events)


def test_parse_agent_step_log_uses_step_as_kind():
    rec = {"ts": 1.0, "step": "think", "role": "assistant", "content": "..."}
    ev = normalize(rec)
    assert ev.kind == "think"


def test_jsonl_source_reads_real_file(tmp_path: Path):
    f = tmp_path / "log.jsonl"
    f.write_text(
        '\n'.join(
            [
                '{"session_id": "s1", "kind": "session_open", "ts": 1.0}',
                '{"session_id": "s1", "kind": "tool_ok", "tool": "x", "ts": 2.0, "usd": 0.1}',
            ]
        )
        + "\n"
    )
    src = JsonlSource(f)
    events = src.events()
    assert len(events) == 2
    assert events[1].tool == "x"


def test_jsonl_source_session_key_override(tmp_path: Path):
    f = tmp_path / "log.jsonl"
    f.write_text(
        json.dumps({"my_run": "run-7", "kind": "tool_ok", "tool": "x"}) + "\n"
    )
    src = JsonlSource(f, session_key="my_run")
    events = src.events()
    assert events[0].session_id == "run-7"


def test_event_dataclass_defaults():
    ev = Event(raw={})
    assert ev.kind == "event"
    assert ev.usd == 0.0
    assert ev.extra == {}
    assert ev.is_error is False
