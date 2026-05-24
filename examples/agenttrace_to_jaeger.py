"""Send a sample audit log to a local Jaeger / OTel Collector.

Usage:

    # 1. Run the OpenTelemetry Collector (or Jaeger all-in-one) somewhere
    #    that exposes OTLP/HTTP on port 4318. For example with Docker:
    #
    #        docker run -p 4318:4318 -p 16686:16686 \\
    #            jaegertracing/all-in-one:1.55 \\
    #            --collector.otlp.enabled=true
    #
    # 2. Run this script.
    # 3. Open http://localhost:16686 and look for the service "my-agent".

    python examples/agenttrace_to_jaeger.py

If you do not have a collector running, the script still prints the OTLP/JSON
payload to stdout so you can see what it would have sent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make the example runnable from a source checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trace_to_otel import JsonlSource, OtlpExporter


def main() -> int:
    sample = Path(__file__).with_name("sample_audit.jsonl")
    src = JsonlSource(sample)
    exporter = OtlpExporter(service_name="my-agent", semconv="otel-genai")
    payload = exporter.spans_from(src)

    print(json.dumps(payload, indent=2))

    endpoint = os.environ.get("OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
    try:
        status = exporter.post_to(endpoint, payload, timeout=2.0)
        print(f"\nposted to {endpoint}: HTTP {status}", file=sys.stderr)
    except Exception as e:  # collector might not be running, that's fine
        print(f"\nskipped POST to {endpoint}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
