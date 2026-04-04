"""Generic function instrumentation wrapper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def instrument_call(collector, operation_name: str, fn: Callable[..., Any], **attrs: Any) -> Any:
    """Run a callable inside a telemetry span and return the result."""
    with collector.create_span(operation_name, attributes=attrs):
        return fn()
