"""Edge deployment manager for K3s regional rollouts."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DeploymentStatus:
    region_id: str
    status: str
    message: str
    updated_at: int


class EdgeDeploymentManager:
    """Coordinates regional edge deployment status and simple orchestration."""

    def __init__(self, manifests_dir: str | Path = "deploy/k3s"):
        self.manifests_dir = Path(manifests_dir)
        self._regions: dict[str, DeploymentStatus] = {}

    def deploy_region(self, region_id: str, k3s_config: dict[str, Any]) -> DeploymentStatus:
        now = int(time.time())
        if not self.manifests_dir.exists():
            status = DeploymentStatus(region_id, "failed", "manifests directory not found", now)
            self._regions[region_id] = status
            return status
        mode = k3s_config.get("mode", "single-node")
        msg = f"deployed in {mode} mode"
        status = DeploymentStatus(region_id, "ready", msg, now)
        self._regions[region_id] = status
        return status

    def rebalance_workloads(self, region_id: str, node_count: int) -> dict[str, Any]:
        if node_count < 1:
            raise ValueError("node_count must be >= 1")
        return {
            "region_id": region_id,
            "status": "rebalanced",
            "nodes": node_count,
            "strategy": "spread",
            "timestamp": int(time.time()),
        }

    def get_region_health(self, region_id: str) -> dict[str, Any]:
        status = self._regions.get(region_id)
        if status is None:
            return {"region_id": region_id, "status": "unknown"}
        return {
            "region_id": status.region_id,
            "status": status.status,
            "message": status.message,
            "updated_at": status.updated_at,
        }

    def list_regions(self) -> dict[str, dict[str, Any]]:
        return {region: self.get_region_health(region) for region in self._regions}
