"""Structured JSON logging and Loki-style aggregation."""

from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogEntry:
    """Normalized structured log event."""

    timestamp: str
    level: str
    logger: str
    message: str
    correlation_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    component: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class LogAggregator:
    """Collect logs, enrich context, and expose query/filter helpers."""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: list[LogEntry] = []
        self._forwarded_batches = 0

    @staticmethod
    def _iso_now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def build_entry(
        self,
        *,
        level: str,
        logger: str,
        message: str,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        component: str | None = None,
        extra: dict[str, Any] | None = None,
        exc: Exception | None = None,
    ) -> LogEntry:
        payload = dict(extra or {})
        if exc is not None:
            payload["error_type"] = exc.__class__.__name__
            payload["error_message"] = str(exc)
            payload["stack_trace"] = traceback.format_exc()
        return LogEntry(
            timestamp=self._iso_now(),
            level=level.upper(),
            logger=logger,
            message=message,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            component=component,
            extra=payload,
        )

    def emit(self, entry: LogEntry) -> str:
        with self._lock:
            self._entries.append(entry)
        return self.to_json(entry)

    @staticmethod
    def to_json(entry: LogEntry) -> str:
        data = {
            "timestamp": entry.timestamp,
            "level": entry.level,
            "logger": entry.logger,
            "message": entry.message,
            "correlation_id": entry.correlation_id,
            "tenant_id": entry.tenant_id,
            "user_id": entry.user_id,
            "component": entry.component,
            "extra": entry.extra,
        }
        return json.dumps(data, separators=(",", ":"), sort_keys=True)

    def collect(self, lines: list[str]) -> None:
        for line in lines:
            raw = json.loads(line)
            self.emit(
                LogEntry(
                    timestamp=raw.get("timestamp", self._iso_now()),
                    level=raw.get("level", "INFO"),
                    logger=raw.get("logger", "siof"),
                    message=raw.get("message", ""),
                    correlation_id=raw.get("correlation_id"),
                    tenant_id=raw.get("tenant_id"),
                    user_id=raw.get("user_id"),
                    component=raw.get("component"),
                    extra=raw.get("extra", {}),
                )
            )

    def query(
        self,
        *,
        level: str | None = None,
        tenant_id: str | None = None,
        component: str | None = None,
        correlation_id: str | None = None,
    ) -> list[LogEntry]:
        with self._lock:
            out = []
            for entry in self._entries:
                if level and entry.level != level.upper():
                    continue
                if tenant_id and entry.tenant_id != tenant_id:
                    continue
                if component and entry.component != component:
                    continue
                if correlation_id and entry.correlation_id != correlation_id:
                    continue
                out.append(entry)
            return out

    def forward_to_loki(self) -> dict[str, Any]:
        with self._lock:
            count = len(self._entries)
            self._forwarded_batches += 1
            return {
                "forwarded_entries": count,
                "batch_id": self._forwarded_batches,
                "status": "ok",
            }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "forwarded_batches": self._forwarded_batches,
            }
