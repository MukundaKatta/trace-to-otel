"""Read JSONL agent audit logs and normalize them into Event records.

Recognizes the same shapes trace-tree does, so any log that renders as a tree
also flows into OTLP spans:

* agenttrace: kind, tool, latency_ms, cost_usd, parent_span_id, session_id
* agentleash: ts, session_id, kind, tool, args_hash, usd, error, extra.latency_ms
* agentsnap: a single top-level object with a steps list
* agent-step-log: ts, step, role, content
* generic JSONL with parent_id or parent_span_id

Unknown shapes still flow through with a best-effort normalize.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


# Field aliases. First hit wins.
_KIND_KEYS = ("kind", "event", "type", "step", "name")
_TS_KEYS = ("ts", "timestamp", "time", "t")
_TOOL_KEYS = ("tool", "tool_name", "function", "name")
_PARENT_KEYS = ("parent_span_id", "parent_id", "parent")
_ID_KEYS = ("span_id", "id", "step_id")
_SESSION_KEYS = ("session_id", "run_id", "trace_id", "session")
_USD_KEYS = ("usd", "cost_usd", "cost", "price_usd")
_LATENCY_KEYS = ("latency_ms", "duration_ms", "elapsed_ms", "ms")
_ERROR_KEYS = ("error", "err", "message")
_URL_KEYS = ("url", "endpoint", "host")

# Kinds that mean "something the agent tried got blocked" so the OTLP status
# code should be ERROR even if no error string was provided.
_DENIED_KINDS = frozenset(
    {
        "tool_denied",
        "budget_denied",
        "egress_denied",
        "policy_denied",
        "rate_limited",
        "blocked",
    }
)


@dataclass
class Event:
    """One normalized record from an agent JSONL audit log."""

    raw: dict[str, Any]
    ts: float | None = None
    kind: str = "event"
    tool: str | None = None
    session_id: str | None = None
    span_id: str | None = None
    parent_id: str | None = None
    usd: float = 0.0
    latency_ms: float | None = None
    error: str | None = None
    url: str | None = None
    args_hash: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return bool(self.error) or self.kind in _DENIED_KINDS


def _first(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def normalize(record: dict[str, Any]) -> Event:
    """Coerce one JSON record into an Event. Unknown shapes still flow through."""
    extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}

    latency = _to_float(_first(record, _LATENCY_KEYS))
    if latency is None and extra:
        latency = _to_float(_first(extra, _LATENCY_KEYS))

    error = _to_str(_first(record, _ERROR_KEYS))
    if error is None and extra:
        error = _to_str(_first(extra, _ERROR_KEYS))

    return Event(
        raw=record,
        ts=_to_float(_first(record, _TS_KEYS)),
        kind=_to_str(_first(record, _KIND_KEYS)) or "event",
        tool=_to_str(_first(record, _TOOL_KEYS)),
        session_id=_to_str(_first(record, _SESSION_KEYS)),
        span_id=_to_str(_first(record, _ID_KEYS)),
        parent_id=_to_str(_first(record, _PARENT_KEYS)),
        usd=_to_float(_first(record, _USD_KEYS)) or 0.0,
        latency_ms=latency,
        error=error,
        url=_to_str(_first(record, _URL_KEYS)),
        args_hash=_to_str(record.get("args_hash")),
        extra=extra,
    )


def _explode_agentsnap(record: dict[str, Any]) -> list[Event]:
    """A top-level object with a steps list expands into one Event per step."""
    out: list[Event] = []
    session = _to_str(_first(record, _SESSION_KEYS)) or _to_str(record.get("name"))
    if session:
        out.append(
            normalize(
                {"kind": "session_open", "session_id": session, "ts": record.get("ts")}
            )
        )
    for step in record.get("steps") or []:
        if not isinstance(step, dict):
            continue
        ev = normalize(step)
        if ev.session_id is None:
            ev.session_id = session
        out.append(ev)
    return out


def parse_lines(lines: Iterable[str]) -> list[Event]:
    """Parse JSONL text into a list of Events. Blank lines skipped, bad lines flagged."""
    events: list[Event] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            events.append(
                Event(raw={"_raw": line}, kind="parse_error", error="invalid json")
            )
            continue
        if isinstance(obj, dict) and isinstance(obj.get("steps"), list):
            events.extend(_explode_agentsnap(obj))
        elif isinstance(obj, dict):
            events.append(normalize(obj))
        else:
            events.append(Event(raw={"_raw": obj}, kind="event"))
    return events


class JsonlSource:
    """Lazily reads a JSONL file and yields normalized Events.

    Pass ``session_key`` to override which top-level field is used to group
    events into spans (default tries the usual aliases).
    """

    def __init__(self, path: str | Path, session_key: str | None = None) -> None:
        self.path = Path(path)
        self.session_key = session_key

    def __iter__(self) -> Iterator[Event]:
        with self.path.open("r", encoding="utf-8") as fh:
            events = parse_lines(fh)
        if self.session_key:
            # Re-key sessions if the caller specified a custom field.
            for ev in events:
                v = ev.raw.get(self.session_key) if isinstance(ev.raw, dict) else None
                if v is not None:
                    ev.session_id = _to_str(v)
        for ev in events:
            yield ev

    def events(self) -> list[Event]:
        return list(iter(self))
