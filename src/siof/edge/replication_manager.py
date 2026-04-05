"""Event-based replication coordination for multi-region edge systems."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class ReplicationEvent:
    event_id: str
    operation: str
    resource_type: str
    resource_id: str
    payload: dict[str, Any]
    checksum: str
    created_at: int


class ReplicationManager:
    """Coordinates asynchronous replication across regions."""

    def __init__(self, lag_threshold_seconds: int = 5):
        self.lag_threshold_seconds = lag_threshold_seconds
        self._events: list[ReplicationEvent] = []
        self._region_status: dict[str, dict[str, Any]] = {}

    def create_event(
        self,
        *,
        operation: str,
        resource_type: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> ReplicationEvent:
        checksum = str(
            hash((operation, resource_type, resource_id, tuple(sorted(payload.items()))))
        )
        event = ReplicationEvent(
            event_id=str(uuid.uuid4()),
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            checksum=checksum,
            created_at=int(time.time()),
        )
        self._events.append(event)
        return event

    def replicate_event(self, event: ReplicationEvent, regions: list[str]) -> dict[str, str]:
        now = int(time.time())
        status: dict[str, str] = {}
        for region in regions:
            self._region_status[region] = {
                "state": "in_sync",
                "last_event_id": event.event_id,
                "last_replicated_at": now,
                "lag_seconds": 0,
            }
            status[region] = "in_sync"
        return status

    def mark_region_lagging(self, region: str, lag_seconds: int) -> None:
        state = "failed" if lag_seconds > (self.lag_threshold_seconds * 3) else "lagging"
        self._region_status[region] = {
            "state": state,
            "lag_seconds": lag_seconds,
            "last_replicated_at": int(time.time()) - lag_seconds,
        }

    def sync_region(self, region: str) -> dict[str, Any]:
        self._region_status[region] = {
            "state": "in_sync",
            "lag_seconds": 0,
            "last_replicated_at": int(time.time()),
        }
        return {"region": region, "status": "synced", "events_replayed": len(self._events)}

    def get_replication_status(self) -> dict[str, dict[str, Any]]:
        return dict(self._region_status)

    def replay_events(
        self, region: str, since_event_id: str | None = None
    ) -> list[ReplicationEvent]:
        if since_event_id is None:
            return self._events[:]
        seen = False
        out: list[ReplicationEvent] = []
        for event in self._events:
            if seen:
                out.append(event)
            if event.event_id == since_event_id:
                seen = True
        return out
