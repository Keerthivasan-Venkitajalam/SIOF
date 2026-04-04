"""Prometheus-compatible metrics exporter with cardinality controls."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricDefinition:
    """Metric metadata and runtime values."""

    name: str
    metric_type: str
    description: str
    unit: str = ""
    max_cardinality: int = 1000
    values: dict[tuple[tuple[str, str], ...], Any] = field(default_factory=dict)
    label_keys: set[str] = field(default_factory=set)
    cardinality: set[tuple[tuple[str, str], ...]] = field(default_factory=set)


class MetricsExporter:
    """In-process metric registry with Prometheus text rendering."""

    def __init__(self):
        self._lock = threading.RLock()
        self._metrics: dict[str, MetricDefinition] = {}
        self._cardinality_drops = 0
        self._register_defaults()

    @staticmethod
    def _normalize_labels(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = labels or {}
        return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

    def _register_defaults(self) -> None:
        self.register_metric("requests_total", "counter", "Total requests")
        self.register_metric("errors_total", "counter", "Total errors")
        self.register_metric("request_duration_seconds", "histogram", "Request latency seconds")
        self.register_metric("active_connections", "gauge", "Active connections")
        self.register_metric("cache_size_bytes", "gauge", "Cache size")
        self.register_metric("queue_depth", "gauge", "Queue depth")

    def register_metric(
        self,
        name: str,
        metric_type: str,
        description: str,
        *,
        unit: str = "",
        max_cardinality: int = 1000,
    ) -> None:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError("Metric name must be alphanumeric with underscores")
        if metric_type not in {"counter", "gauge", "histogram", "summary"}:
            raise ValueError("Unsupported metric type")
        if max_cardinality < 1:
            raise ValueError("max_cardinality must be >= 1")
        with self._lock:
            self._metrics[name] = MetricDefinition(
                name=name,
                metric_type=metric_type,
                description=description,
                unit=unit,
                max_cardinality=max_cardinality,
            )

    def _ensure_series(self, metric: MetricDefinition, labels: tuple[tuple[str, str], ...]) -> bool:
        if labels in metric.cardinality:
            return True
        if len(metric.cardinality) >= metric.max_cardinality:
            self._cardinality_drops += 1
            return False
        metric.cardinality.add(labels)
        return True

    def increment_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            metric = self._metrics[name]
            series = self._normalize_labels(labels)
            if not self._ensure_series(metric, series):
                return
            metric.values[series] = float(metric.values.get(series, 0.0)) + float(value)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            metric = self._metrics[name]
            series = self._normalize_labels(labels)
            if not self._ensure_series(metric, series):
                return
            metric.values[series] = float(value)

    def record_histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            metric = self._metrics[name]
            series = self._normalize_labels(labels)
            if not self._ensure_series(metric, series):
                return
            buckets = metric.values.setdefault(series, [])
            buckets.append(float(value))

    @staticmethod
    def _labels_to_str(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        inner = ",".join(f'{k}="{v}"' for k, v in labels)
        return "{" + inner + "}"

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for metric in self._metrics.values():
                lines.append(f"# HELP {metric.name} {metric.description}")
                lines.append(f"# TYPE {metric.name} {metric.metric_type}")
                for labels, raw_value in metric.values.items():
                    suffix = self._labels_to_str(labels)
                    if metric.metric_type in {"counter", "gauge"}:
                        lines.append(f"{metric.name}{suffix} {raw_value}")
                    elif metric.metric_type == "histogram":
                        values = list(raw_value)
                        if not values:
                            continue
                        values.sort()
                        count = len(values)
                        total = sum(values)
                        p50 = values[count // 2]
                        p95 = values[min(count - 1, int(count * 0.95))]
                        lines.append(f"{metric.name}_count{suffix} {count}")
                        lines.append(f"{metric.name}_sum{suffix} {total}")
                        lines.append(f"{metric.name}_p50{suffix} {p50}")
                        lines.append(f"{metric.name}_p95{suffix} {p95}")
                    else:
                        values = list(raw_value)
                        if values:
                            lines.append(f"{metric.name}_count{suffix} {len(values)}")
                            lines.append(f"{metric.name}_sum{suffix} {sum(values)}")
            lines.append(f"siof_metric_cardinality_drops_total {self._cardinality_drops}")
            lines.append(f"siof_metrics_export_timestamp_seconds {int(time.time())}")
        return "\n".join(lines) + "\n"

    def get_cardinality(self, metric_name: str) -> int:
        with self._lock:
            metric = self._metrics[metric_name]
            return len(metric.cardinality)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "metric_count": len(self._metrics),
                "cardinality_drops": self._cardinality_drops,
                "metrics": {
                    name: {
                        "type": m.metric_type,
                        "series": len(m.cardinality),
                    }
                    for name, m in self._metrics.items()
                },
            }
