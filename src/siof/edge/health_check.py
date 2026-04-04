"""Edge health checks for liveness, readiness, and replication state."""

from __future__ import annotations

import shutil
from typing import Any


class EdgeHealthChecker:
    """Simple health checker for edge runtime components."""

    def __init__(self, *, min_disk_free_bytes: int = 100 * 1024 * 1024):
        self.min_disk_free_bytes = min_disk_free_bytes

    def check_live(self) -> tuple[int, dict[str, Any]]:
        return 200, {"status": "alive"}

    def check_ready(
        self,
        *,
        db_connected: bool,
        cache_connected: bool,
        replication_lag_seconds: int,
        lag_threshold_seconds: int = 5,
        path_for_disk_check: str = ".",
    ) -> tuple[int, dict[str, Any]]:
        disk = shutil.disk_usage(path_for_disk_check)
        checks = {
            "db_connected": db_connected,
            "cache_connected": cache_connected,
            "replication_lag_ok": replication_lag_seconds <= lag_threshold_seconds,
            "disk_ok": disk.free >= self.min_disk_free_bytes,
        }
        ok = all(checks.values())
        payload = {
            "status": "ready" if ok else "not_ready",
            "checks": checks,
            "disk_free_bytes": disk.free,
        }
        return (200 if ok else 503), payload
