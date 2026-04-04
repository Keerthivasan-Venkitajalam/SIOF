"""Trace export utilities with Jaeger-compatible JSON payloads."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .telemetry_collector import SpanRecord


class JaegerTraceExporter:
    """Batch and export traces to a local JSON file for ingestion."""

    def __init__(self, output_path: str | Path = "./deploy/observability/jaeger-spans.json"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._exported_batches = 0
        self._exported_spans = 0

    def export(self, spans: list[SpanRecord]) -> dict[str, Any]:
        payload = {
            "exported_at": int(time.time()),
            "spans": [asdict(s) for s in spans],
        }
        if self.output_path.exists():
            existing = self.output_path.read_text(encoding="utf-8").strip()
            if existing:
                try:
                    current = json.loads(existing)
                except json.JSONDecodeError:
                    current = {"batches": []}
            else:
                current = {"batches": []}
        else:
            current = {"batches": []}

        current.setdefault("batches", []).append(payload)
        self.output_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

        self._exported_batches += 1
        self._exported_spans += len(spans)
        return {
            "status": "ok",
            "exported_spans": len(spans),
            "batch": self._exported_batches,
            "path": str(self.output_path),
        }

    def stats(self) -> dict[str, int]:
        return {
            "exported_batches": self._exported_batches,
            "exported_spans": self._exported_spans,
        }
