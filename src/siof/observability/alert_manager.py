"""Alerting rule evaluation and notification orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AlertRule:
    """Threshold-based alert definition."""

    name: str
    metric: str
    threshold: float
    comparator: str = ">"
    duration_seconds: int = 300
    severity: str = "warning"
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Alert:
    """Active or resolved alert event."""

    name: str
    severity: str
    metric: str
    value: float
    threshold: float
    status: str
    fired_at: int
    labels: dict[str, str] = field(default_factory=dict)


class AlertManager:
    """Evaluates rules and emits alerts to configured channels."""

    def __init__(self):
        self._rules: dict[str, AlertRule] = {}
        self._active_since: dict[str, int] = {}
        self._active_alerts: dict[str, Alert] = {}
        self._history: list[Alert] = []
        self._channels: list[Any] = []

    def register_channel(self, channel: Any) -> None:
        """Register notification channel with send(alert) signature."""
        self._channels.append(channel)

    def register_rule(self, rule: AlertRule) -> None:
        self._rules[rule.name] = rule

    def register_default_rules(self) -> None:
        self.register_rule(AlertRule("high_error_rate", "error_rate", 0.05, ">", 300, "critical"))
        self.register_rule(AlertRule("high_latency_p95", "latency_p95_seconds", 1.0, ">", 300, "critical"))
        self.register_rule(AlertRule("low_cache_hit_rate", "cache_hit_rate", 0.70, "<", 600, "warning"))
        self.register_rule(AlertRule("high_memory_usage", "memory_usage_ratio", 0.80, ">", 300, "warning"))
        self.register_rule(AlertRule("high_cpu_usage", "cpu_usage_ratio", 0.80, ">", 300, "warning"))

    @staticmethod
    def _matches(value: float, comparator: str, threshold: float) -> bool:
        if comparator == ">":
            return value > threshold
        if comparator == ">=":
            return value >= threshold
        if comparator == "<":
            return value < threshold
        if comparator == "<=":
            return value <= threshold
        raise ValueError("Unsupported comparator")

    def evaluate(self, metrics: dict[str, float], now: int | None = None) -> list[Alert]:
        now = int(time.time()) if now is None else now
        emitted: list[Alert] = []

        for name, rule in self._rules.items():
            value = float(metrics.get(rule.metric, 0.0))
            matched = self._matches(value, rule.comparator, rule.threshold)
            if matched:
                self._active_since.setdefault(name, now)
                active_duration = now - self._active_since[name]
                if active_duration >= rule.duration_seconds and name not in self._active_alerts:
                    alert = Alert(
                        name=name,
                        severity=rule.severity,
                        metric=rule.metric,
                        value=value,
                        threshold=rule.threshold,
                        status="firing",
                        fired_at=now,
                        labels=rule.labels,
                    )
                    self._active_alerts[name] = alert
                    self._history.append(alert)
                    emitted.append(alert)
                    for channel in self._channels:
                        channel.send(alert)
            else:
                self._active_since.pop(name, None)
                active = self._active_alerts.pop(name, None)
                if active is not None:
                    resolved = Alert(
                        name=active.name,
                        severity=active.severity,
                        metric=active.metric,
                        value=value,
                        threshold=active.threshold,
                        status="resolved",
                        fired_at=now,
                        labels=active.labels,
                    )
                    self._history.append(resolved)
                    emitted.append(resolved)
                    for channel in self._channels:
                        channel.send(resolved)
        return emitted

    def active_alerts(self) -> list[Alert]:
        return list(self._active_alerts.values())

    def history(self) -> list[Alert]:
        return self._history[:]
