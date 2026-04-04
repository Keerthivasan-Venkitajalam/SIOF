"""Health checks for observability subsystem components."""

from __future__ import annotations

from typing import Any


class ObservabilityHealthChecker:
    """Aggregate health checks for telemetry pipeline components."""

    def __init__(self, *, metrics_exporter=None, trace_exporter=None, log_aggregator=None):
        self.metrics_exporter = metrics_exporter
        self.trace_exporter = trace_exporter
        self.log_aggregator = log_aggregator

    def _component_status(self, component: Any) -> dict[str, Any]:
        if component is None:
            return {"status": "unknown"}
        if hasattr(component, "stats"):
            return {"status": "ok", "stats": component.stats()}
        return {"status": "ok"}

    def check(self) -> tuple[int, dict[str, Any]]:
        payload = {
            "metrics_exporter": self._component_status(self.metrics_exporter),
            "trace_exporter": self._component_status(self.trace_exporter),
            "log_aggregator": self._component_status(self.log_aggregator),
        }
        statuses = [v["status"] for v in payload.values()]
        overall = "ok" if all(s in {"ok", "unknown"} for s in statuses) else "degraded"
        payload["status"] = overall
        return (200 if overall == "ok" else 503, payload)
