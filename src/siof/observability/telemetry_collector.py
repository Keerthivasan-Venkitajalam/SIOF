"""OpenTelemetry-inspired collector with correlation and sampling support.

This module intentionally provides a lightweight implementation that can run
without external telemetry dependencies while keeping the same programming
model used by OpenTelemetry-style instrumentation.
"""

from __future__ import annotations

import contextvars
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TelemetryConfig:
    """Telemetry collector configuration."""

    service_name: str = "siof"
    service_version: str = "2.0.0"
    environment: str = "dev"
    sampling_rate: float = 1.0
    max_attributes: int = 1000
    exporters: dict[str, dict[str, Any]] = field(default_factory=dict)

    def validate(self) -> None:
        if not (0.0 <= self.sampling_rate <= 1.0):
            raise ValueError("sampling_rate must be in [0.0, 1.0]")
        if self.max_attributes < 1:
            raise ValueError("max_attributes must be >= 1")


@dataclass
class SpanRecord:
    """Captured span with contextual metadata."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    operation_name: str
    start_time: float
    end_time: float | None = None
    duration_ms: float | None = None
    status: str = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    correlation_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class SpanContext:
    """Context manager for safe span lifecycle handling."""

    def __init__(self, collector: "TelemetryCollector", span: SpanRecord):
        self.collector = collector
        self.span = span

    def __enter__(self) -> SpanRecord:
        return self.span

    def __exit__(self, exc_type, exc_val, _exc_tb) -> None:
        if exc_type is not None:
            self.collector.record_error(self.span, exc_type.__name__, str(exc_val))
        self.collector.end_span(self.span)


class TelemetryCollector:
    """Collects spans, correlation IDs, and telemetry context."""

    _correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "siof_correlation_id",
        default=None,
    )
    _trace_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "siof_trace_id",
        default=None,
    )
    _span_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
        "siof_span_id",
        default=None,
    )

    def __init__(self, config: TelemetryConfig | None = None):
        self.config = config or TelemetryConfig()
        self.config.validate()
        self._initialized = True
        self._spans: list[SpanRecord] = []
        self._dropped_spans = 0

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    def initialize(self, config: TelemetryConfig) -> None:
        config.validate()
        self.config = config
        self._initialized = True

    def get_tracer(self, _name: str) -> "TelemetryCollector":
        """Return tracer-compatible object.

        This lightweight collector acts as its own tracer instance.
        """
        if not self._initialized:
            raise RuntimeError("TelemetryCollector is not initialized")
        return self

    def create_correlation_id(self) -> str:
        cid = str(uuid.uuid4())
        self.set_correlation_id(cid)
        return cid

    def set_correlation_id(self, correlation_id: str) -> None:
        self._correlation_id_ctx.set(correlation_id)

    def get_correlation_id(self) -> str | None:
        return self._correlation_id_ctx.get()

    def extract_correlation_id(self, headers: dict[str, str]) -> str:
        traceparent = headers.get("traceparent")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 4:
                trace_id = parts[1]
                self._trace_id_ctx.set(trace_id)
                cid = headers.get("x-correlation-id", trace_id)
                self.set_correlation_id(cid)
                return cid

        incoming = headers.get("x-correlation-id")
        if incoming:
            self.set_correlation_id(incoming)
            return incoming
        return self.create_correlation_id()

    def should_sample(self, operation_name: str | None = None) -> bool:
        """Head-based sampling with optional per-operation override."""
        if operation_name:
            override = self.config.exporters.get("sampling", {}).get(operation_name)
            if override is not None:
                return random.random() < float(override)
        return random.random() < self.config.sampling_rate

    def create_span(
        self,
        operation_name: str,
        attributes: dict[str, Any] | None = None,
        parent_span_id: str | None = None,
    ) -> SpanContext:
        """Create a sampled span context manager."""
        if not self.should_sample(operation_name):
            self._dropped_spans += 1
            # Return a no-op context with minimal placeholder span.
            span = SpanRecord(
                trace_id=self._trace_id_ctx.get() or self._new_id(),
                span_id=self._new_id(),
                parent_span_id=parent_span_id,
                operation_name=operation_name,
                start_time=time.time(),
                status="dropped",
            )
            return SpanContext(self, span)

        trace_id = self._trace_id_ctx.get() or self._new_id()
        span_id = self._new_id()
        self._trace_id_ctx.set(trace_id)
        self._span_id_ctx.set(span_id)
        attrs = dict(attributes or {})
        if len(attrs) > self.config.max_attributes:
            attrs = dict(list(attrs.items())[: self.config.max_attributes])

        attrs.setdefault("service.name", self.config.service_name)
        attrs.setdefault("service.version", self.config.service_version)
        attrs.setdefault("deployment.environment", self.config.environment)

        span = SpanRecord(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id or self._span_id_ctx.get(),
            operation_name=operation_name,
            start_time=time.time(),
            attributes=attrs,
            correlation_id=self.get_correlation_id(),
        )
        return SpanContext(self, span)

    def add_event(self, span: SpanRecord, name: str, attrs: dict[str, Any] | None = None) -> None:
        span.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "attributes": attrs or {},
            }
        )

    def record_error(self, span: SpanRecord, error_type: str, message: str) -> None:
        span.status = "error"
        span.error_type = error_type
        span.error_message = message

    def end_span(self, span: SpanRecord) -> None:
        if span.status == "dropped":
            return
        span.end_time = time.time()
        span.duration_ms = (span.end_time - span.start_time) * 1000.0
        self._spans.append(span)

    def flush(self) -> list[SpanRecord]:
        spans = self._spans[:]
        self._spans.clear()
        return spans

    def shutdown(self) -> None:
        self._initialized = False

    def get_metrics(self) -> dict[str, Any]:
        return {
            "captured_spans": len(self._spans),
            "dropped_spans": self._dropped_spans,
            "sampling_rate": self.config.sampling_rate,
        }
