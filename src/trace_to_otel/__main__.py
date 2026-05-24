"""CLI entrypoint: ``python -m trace_to_otel <jsonl> <out.otlp.json>``."""

from __future__ import annotations

import argparse
import sys

from .otlp import jsonl_to_otlp
from .semconv import supported_semconvs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trace-to-otel",
        description=(
            "Convert an agent JSONL audit log (agenttrace, agentleash, "
            "agentsnap, agent-step-log, or generic) into an OTLP/JSON file "
            "you can POST to any OpenTelemetry collector."
        ),
    )
    parser.add_argument("src", help="Path to the JSONL audit log.")
    parser.add_argument(
        "dst",
        nargs="?",
        default="-",
        help="Output path for the OTLP JSON file. Use '-' for stdout (default).",
    )
    parser.add_argument(
        "--service-name",
        default="agent",
        help="Value for the resource service.name attribute. Default: agent.",
    )
    parser.add_argument(
        "--semconv",
        default="otel-genai",
        choices=supported_semconvs(),
        help="Semantic-convention preset for attribute keys. Default: otel-genai.",
    )
    parser.add_argument(
        "--session-key",
        default=None,
        help="Top-level JSONL field to use as the session id. Default: auto-detect.",
    )
    parser.add_argument(
        "--post",
        default=None,
        help="If set, also POST the payload to this OTLP/HTTP traces endpoint.",
    )
    args = parser.parse_args(argv)

    if args.dst == "-":
        # Build and dump to stdout without touching disk.
        from .jsonl_source import JsonlSource
        from .otlp import OtlpExporter
        import json

        source = JsonlSource(args.src, session_key=args.session_key)
        exporter = OtlpExporter(service_name=args.service_name, semconv=args.semconv)
        payload = exporter.spans_from(source)
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        payload = jsonl_to_otlp(
            src=args.src,
            dst=args.dst,
            service_name=args.service_name,
            semconv=args.semconv,
            session_key=args.session_key,
        )

    if args.post:
        from .otlp import OtlpExporter

        exporter = OtlpExporter(service_name=args.service_name, semconv=args.semconv)
        status = exporter.post_to(args.post, payload)
        print(f"posted to {args.post}: HTTP {status}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
