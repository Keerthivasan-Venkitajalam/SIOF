"""Regional endpoint registration and nearest-endpoint selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EndpointRecord:
    region: str
    endpoint: str
    metadata: dict[str, Any]
    healthy: bool = True


class RegionalEndpointRegistry:
    """Stores and resolves edge endpoints by region and health."""

    def __init__(self):
        self._records: dict[str, EndpointRecord] = {}

    def register_endpoint(
        self, region: str, endpoint: str, metadata: dict[str, Any] | None = None
    ) -> None:
        self._records[region] = EndpointRecord(
            region=region, endpoint=endpoint, metadata=metadata or {}
        )

    def get_nearest_endpoint(self, preferred_regions: list[str] | None = None) -> str | None:
        preferred_regions = preferred_regions or []
        for region in preferred_regions:
            rec = self._records.get(region)
            if rec and rec.healthy:
                return rec.endpoint
        for rec in self._records.values():
            if rec.healthy:
                return rec.endpoint
        return None

    def mark_unhealthy(self, endpoint: str) -> None:
        for region, record in self._records.items():
            if record.endpoint == endpoint:
                self._records[region] = EndpointRecord(
                    region=record.region,
                    endpoint=record.endpoint,
                    metadata=record.metadata,
                    healthy=False,
                )

    def get_status(self) -> dict[str, dict[str, Any]]:
        return {
            region: {
                "endpoint": record.endpoint,
                "healthy": record.healthy,
                "metadata": record.metadata,
            }
            for region, record in self._records.items()
        }
