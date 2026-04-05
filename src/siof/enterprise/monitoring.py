"""Monitoring helpers: Prometheus metrics and health checks."""

from __future__ import annotations

import logging
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _label_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted(labels.items()))


@dataclass(slots=True)
class HistogramSeries:
    values: list[float]


class MetricsCollector:
    """In-memory metrics collector with Prometheus text export."""

    def __init__(self):
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], HistogramSeries] = {}

    def increment_counter(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        key = (name, _label_key(labels))
        self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = (name, _label_key(labels))
        self._gauges[key] = value

    def observe_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        key = (name, _label_key(labels))
        series = self._histograms.setdefault(key, HistogramSeries(values=[]))
        series.values.append(value)

    def record_request(
        self, *, latency_ms: float, status_code: int, auth_failure: bool = False
    ) -> None:
        self.increment_counter("requests_total")
        self.observe_histogram("request_latency_ms", latency_ms)

        if status_code >= 500:
            self.increment_counter("request_errors_total", labels={"class": "5xx"})
        elif status_code >= 400:
            self.increment_counter("request_errors_total", labels={"class": "4xx"})

        if auth_failure:
            self.increment_counter("auth_failures_total")

    def get_snapshot(self) -> dict[str, Any]:
        histograms: dict[str, dict[str, float]] = {}
        for (name, labels), series in self._histograms.items():
            key = self._format_metric_key(name, labels)
            values = series.values
            histograms[key] = {
                "count": float(len(values)),
                "min": min(values) if values else 0.0,
                "max": max(values) if values else 0.0,
                "avg": statistics.mean(values) if values else 0.0,
            }

        return {
            "counters": {
                self._format_metric_key(name, labels): value
                for (name, labels), value in self._counters.items()
            },
            "gauges": {
                self._format_metric_key(name, labels): value
                for (name, labels), value in self._gauges.items()
            },
            "histograms": histograms,
        }

    def _format_metric_key(self, name: str, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return name
        suffix = ",".join(f"{k}={v}" for k, v in labels)
        return f"{name}[{suffix}]"

    def _format_labels(self, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        encoded = ",".join(f'{k}="{v}"' for k, v in labels)
        return "{" + encoded + "}"

    def export_prometheus(self) -> str:
        """Export metrics using Prometheus exposition text format."""
        lines: list[str] = []

        for (name, labels), value in sorted(self._counters.items(), key=lambda x: x[0][0]):
            lines.append(f"{name}{self._format_labels(labels)} {value}")

        for (name, labels), value in sorted(self._gauges.items(), key=lambda x: x[0][0]):
            lines.append(f"{name}{self._format_labels(labels)} {value}")

        for (name, labels), series in sorted(self._histograms.items(), key=lambda x: x[0][0]):
            values = series.values
            label_expr = self._format_labels(labels)
            lines.append(f"{name}_count{label_expr} {len(values)}")
            lines.append(f"{name}_sum{label_expr} {sum(values)}")

        return "\n".join(lines) + ("\n" if lines else "")


class HealthChecker:
    """Composable liveness and readiness checks."""

    def __init__(self):
        self._checks: dict[str, Callable[[], bool | dict[str, Any]]] = {}

    def register_check(self, name: str, check_fn: Callable[[], bool | dict[str, Any]]) -> None:
        self._checks[name] = check_fn

    def _run(self) -> dict[str, Any]:
        component_status: dict[str, dict[str, Any]] = {}
        all_healthy = True

        for name, check_fn in self._checks.items():
            start = time.time()
            try:
                result = check_fn()
                if isinstance(result, bool):
                    healthy = result
                    details: dict[str, Any] = {}
                elif isinstance(result, dict):
                    healthy = bool(result.get("healthy", True))
                    details = {k: v for k, v in result.items() if k != "healthy"}
                else:
                    healthy = False
                    details = {"error": "invalid health response"}
            except Exception as exc:
                healthy = False
                details = {"error": str(exc)}

            elapsed_ms = (time.time() - start) * 1000
            component_status[name] = {
                "healthy": healthy,
                "latency_ms": round(elapsed_ms, 2),
                "details": details,
            }
            all_healthy = all_healthy and healthy

        return {
            "healthy": all_healthy,
            "components": component_status,
        }

    def health(self) -> tuple[int, dict[str, Any]]:
        payload = self._run()
        payload["status"] = "healthy" if payload["healthy"] else "unhealthy"
        return (200 if payload["healthy"] else 503), payload

    def readiness(self) -> tuple[int, dict[str, Any]]:
        payload = self._run()
        payload["status"] = "ready" if payload["healthy"] else "not_ready"
        return (200 if payload["healthy"] else 503), payload

    def liveness(self) -> tuple[int, dict[str, Any]]:
        # Liveness intentionally remains simple so transient dependency outages
        # do not trigger restart loops.
        return 200, {"status": "alive"}
