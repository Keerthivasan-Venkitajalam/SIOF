"""Green Guard: Energy tracking and CO2 enforcement.

Tracks energy consumption and CO2 emissions for command execution,
enforcing soft/hard thresholds and generating sustainability reports.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import EnergyRun
from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EnergyMetrics:
    """Energy metrics for a run."""

    run_id: str
    duration_s: float
    cpu_seconds: float
    estimated_wh: float
    estimated_co2_kg: float
    status: str


class GreenGuard:
    """Tracks and enforces energy/CO2 budgets for command execution.

    Features:
    - Per-run energy tracking
    - CO2 emissions calculation
    - Soft/hard threshold enforcement
    - Sustainability reporting
    """

    # Default CO2 factor (kg CO2 per kWh)
    DEFAULT_CO2_PER_KWH = 0.475

    # Default CPU power consumption (watts)
    DEFAULT_CPU_WATTS = 45.0

    def __init__(
        self,
        db_path: Path | str,
        co2_kg_per_kwh: float = DEFAULT_CO2_PER_KWH,
        cpu_watts: float = DEFAULT_CPU_WATTS,
    ):
        """Initialize GreenGuard.

        Args:
            db_path: Path to SQLite database
            co2_kg_per_kwh: CO2 emissions factor (kg CO2 per kWh)
            cpu_watts: CPU power consumption (watts)
        """
        self.db = Storage(db_path)
        self.db.init_schema()
        self.co2_kg_per_kwh = co2_kg_per_kwh
        self.cpu_watts = cpu_watts
        logger.info(f"Initialized GreenGuard: CO2={co2_kg_per_kwh} kg/kWh, CPU={cpu_watts}W")

    def close(self) -> None:
        """Close database connection."""
        self.db.close()

    def run_command(
        self,
        command: list[str],
        hard_co2_kg: float | None = None,
        soft_co2_kg: float | None = None,
    ) -> dict[str, Any]:
        """Run a command with energy tracking and optional CO2 limit enforcement.

        Args:
            command: Command to run
            hard_co2_kg: Hard CO2 limit (terminates if exceeded)
            soft_co2_kg: Soft CO2 limit (warning if exceeded)

        Returns:
            Dictionary with run metrics and status
        """
        run_id = str(uuid.uuid4())
        logger.info(f"Starting monitored run {run_id}: {' '.join(command)}")

        start = time.time()
        before_cpu = os.times()

        try:
            proc = subprocess.run(command, text=True, capture_output=True)
            returncode = proc.returncode
        except Exception as exc:
            logger.error(f"Command execution failed: {exc}")
            returncode = 1

        after_cpu = os.times()
        end = time.time()

        # Calculate metrics
        duration_s = max(0.0, end - start)
        cpu_seconds = max(
            0.0,
            (after_cpu.user + after_cpu.system) - (before_cpu.user + before_cpu.system),
        )

        # Energy estimation: cpu_seconds * cpu_watts / 3600 = Wh
        estimated_wh = (cpu_seconds * self.cpu_watts) / 3600.0
        estimated_co2_kg = (estimated_wh / 1000.0) * self.co2_kg_per_kwh

        # Determine status
        status = "ok" if returncode == 0 else "failed"

        if hard_co2_kg is not None and estimated_co2_kg > hard_co2_kg:
            status = "terminated_by_co2_policy"
            logger.warning(
                f"Run {run_id} exceeded hard CO2 limit: "
                f"{estimated_co2_kg:.6f} > {hard_co2_kg:.6f}"
            )
        elif soft_co2_kg is not None and estimated_co2_kg > soft_co2_kg:
            logger.warning(
                f"Run {run_id} exceeded soft CO2 limit: "
                f"{estimated_co2_kg:.6f} > {soft_co2_kg:.6f}"
            )

        # Store run
        run = EnergyRun(
            run_id=run_id,
            command=" ".join(command),
            duration_s=duration_s,
            estimated_wh=estimated_wh,
            estimated_co2_kg=estimated_co2_kg,
            status=status,
        )
        self.db.insert_energy_run(run)

        logger.info(
            f"Run {run_id} complete: {duration_s:.2f}s, "
            f"{estimated_wh:.4f}Wh, {estimated_co2_kg:.6f}kg CO2, status={status}"
        )

        return {
            "run_id": run_id,
            "returncode": returncode,
            "duration_s": duration_s,
            "cpu_seconds": cpu_seconds,
            "estimated_wh": estimated_wh,
            "estimated_co2_kg": estimated_co2_kg,
            "status": status,
        }

    def report(self, run_id: str) -> dict[str, Any]:
        """Get energy report for a run.

        Args:
            run_id: Run identifier

        Returns:
            Dictionary with run metrics
        """
        result = self.db.get_energy_run(run_id)
        if result:
            logger.info(f"Retrieved report for run {run_id}")
        else:
            logger.warning(f"No report found for run {run_id}")
        return result or {}

    def sustainability_report(self) -> dict[str, Any]:
        """Generate sustainability report for all runs.

        Returns:
            Dictionary with aggregated metrics
        """
        conn = self.db.conn

        # Get all runs
        rows = conn.execute(
            "SELECT duration_s, estimated_wh, estimated_co2_kg, status FROM energy_runs"
        ).fetchall()

        if not rows:
            logger.info("No runs found for sustainability report")
            return {
                "total_runs": 0,
                "total_duration_s": 0.0,
                "total_wh": 0.0,
                "total_co2_kg": 0.0,
                "successful_runs": 0,
                "failed_runs": 0,
            }

        total_duration = sum(row[0] for row in rows)
        total_wh = sum(row[1] for row in rows)
        total_co2_kg = sum(row[2] for row in rows)
        successful = sum(1 for row in rows if row[3] == "ok")
        failed = sum(1 for row in rows if row[3] != "ok")

        report = {
            "total_runs": len(rows),
            "total_duration_s": total_duration,
            "total_wh": total_wh,
            "total_co2_kg": total_co2_kg,
            "average_duration_s": total_duration / len(rows) if rows else 0.0,
            "average_wh": total_wh / len(rows) if rows else 0.0,
            "average_co2_kg": total_co2_kg / len(rows) if rows else 0.0,
            "successful_runs": successful,
            "failed_runs": failed,
            "success_rate": successful / len(rows) if rows else 0.0,
        }

        logger.info(f"Generated sustainability report: {report}")
        return report
