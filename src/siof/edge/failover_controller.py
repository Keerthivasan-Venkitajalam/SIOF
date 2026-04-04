"""Primary region failover and recovery orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class FailoverEvent:
    timestamp: int
    old_primary: str
    new_primary: str
    reason: str


class FailoverController:
    """Tracks region health and promotes replicas on failures."""

    def __init__(self, *, primary_region: str):
        self.primary_region = primary_region
        self._failures: dict[str, int] = {}
        self._events: list[FailoverEvent] = []
        self._region_health: dict[str, str] = {primary_region: "healthy"}

    def report_health(self, region: str, healthy: bool) -> None:
        self._region_health[region] = "healthy" if healthy else "unhealthy"
        if healthy:
            self._failures[region] = 0
        else:
            self._failures[region] = self._failures.get(region, 0) + 1

    def check_primary_health(self) -> dict[str, Any]:
        state = self._region_health.get(self.primary_region, "unknown")
        failures = self._failures.get(self.primary_region, 0)
        return {
            "region": self.primary_region,
            "status": state,
            "consecutive_failures": failures,
            "ready_for_failover": failures >= 3,
        }

    def trigger_failover(self, target_replica: str, reason: str = "automatic") -> FailoverEvent:
        old = self.primary_region
        self.primary_region = target_replica
        event = FailoverEvent(
            timestamp=int(time.time()),
            old_primary=old,
            new_primary=target_replica,
            reason=reason,
        )
        self._events.append(event)
        self._region_health[target_replica] = "healthy"
        return event

    def get_failover_history(self) -> list[FailoverEvent]:
        return self._events[:]
