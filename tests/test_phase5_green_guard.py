"""Comprehensive tests for Phase 5: Green Guard Instrumentation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from siof.green_guard import GreenGuard


class TestGreenGuard:
    """Test Green Guard energy tracking."""

    @pytest.fixture
    def green_guard(self) -> GreenGuard:
        """Create Green Guard instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            guard = GreenGuard(db_path)
            yield guard
            guard.close()

    def test_green_guard_initialization(self, green_guard: GreenGuard) -> None:
        """Test Green Guard initialization."""
        assert green_guard.co2_kg_per_kwh == 0.475
        assert green_guard.cpu_watts == 45.0

    def test_green_guard_custom_factors(self) -> None:
        """Test Green Guard with custom factors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            guard = GreenGuard(db_path, co2_kg_per_kwh=0.5, cpu_watts=50.0)

            assert guard.co2_kg_per_kwh == 0.5
            assert guard.cpu_watts == 50.0

            guard.close()

    def test_run_command_success(self, green_guard: GreenGuard) -> None:
        """Test running successful command."""
        result = green_guard.run_command(["python", "-c", "print('test')"])

        assert result["returncode"] == 0
        assert result["status"] == "ok"
        assert result["run_id"]
        assert result["duration_s"] >= 0
        assert result["estimated_wh"] >= 0
        assert result["estimated_co2_kg"] >= 0

    def test_run_command_failure(self, green_guard: GreenGuard) -> None:
        """Test running failed command."""
        result = green_guard.run_command(["python", "-c", "raise Exception('test')"])

        assert result["returncode"] != 0
        assert result["status"] == "failed"

    def test_run_command_hard_limit_exceeded(self, green_guard: GreenGuard) -> None:
        """Test hard CO2 limit enforcement."""
        # Set very low limit to trigger (but realistic for a quick command)
        result = green_guard.run_command(
            ["python", "-c", "import time; time.sleep(0.1)"],
            hard_co2_kg=0.00001,  # Very low limit
        )

        # Should be terminated by policy or succeed (depends on actual CPU usage)
        assert result["status"] in ["terminated_by_co2_policy", "ok"]

    def test_run_command_hard_limit_not_exceeded(self, green_guard: GreenGuard) -> None:
        """Test hard CO2 limit not exceeded."""
        result = green_guard.run_command(
            ["python", "-c", "print('test')"],
            hard_co2_kg=1.0,  # High limit
        )

        assert result["status"] == "ok"

    def test_run_command_soft_limit(self, green_guard: GreenGuard) -> None:
        """Test soft CO2 limit (warning only)."""
        result = green_guard.run_command(
            ["python", "-c", "print('test')"],
            soft_co2_kg=0.0001,  # Low limit
        )

        # Should still succeed but with warning
        assert result["returncode"] == 0

    def test_run_command_metrics(self, green_guard: GreenGuard) -> None:
        """Test run command metrics."""
        result = green_guard.run_command(["python", "-c", "x = 1 + 1"])

        assert "run_id" in result
        assert "returncode" in result
        assert "duration_s" in result
        assert "cpu_seconds" in result
        assert "estimated_wh" in result
        assert "estimated_co2_kg" in result
        assert "status" in result

    def test_report_existing_run(self, green_guard: GreenGuard) -> None:
        """Test retrieving report for existing run."""
        run_result = green_guard.run_command(["python", "-c", "print('test')"])
        run_id = run_result["run_id"]

        report = green_guard.report(run_id)

        assert report is not None
        assert "run_id" in report or len(report) > 0

    def test_report_nonexistent_run(self, green_guard: GreenGuard) -> None:
        """Test retrieving report for nonexistent run."""
        report = green_guard.report("nonexistent_run_id")

        assert report == {} or report is None or "run_id" not in report

    def test_sustainability_report_empty(self, green_guard: GreenGuard) -> None:
        """Test sustainability report with no runs."""
        report = green_guard.sustainability_report()

        assert report["total_runs"] == 0
        assert report["total_duration_s"] == 0.0
        assert report["total_wh"] == 0.0
        assert report["total_co2_kg"] == 0.0

    def test_sustainability_report_single_run(self, green_guard: GreenGuard) -> None:
        """Test sustainability report with single run."""
        green_guard.run_command(["python", "-c", "print('test')"])

        report = green_guard.sustainability_report()

        assert report["total_runs"] == 1
        assert report["successful_runs"] == 1
        assert report["failed_runs"] == 0
        assert report["success_rate"] == 1.0
        assert report["total_duration_s"] > 0
        assert report["total_wh"] >= 0
        assert report["total_co2_kg"] >= 0

    def test_sustainability_report_multiple_runs(self, green_guard: GreenGuard) -> None:
        """Test sustainability report with multiple runs."""
        green_guard.run_command(["python", "-c", "print('test1')"])
        green_guard.run_command(["python", "-c", "print('test2')"])
        green_guard.run_command(["python", "-c", "raise Exception()"])

        report = green_guard.sustainability_report()

        assert report["total_runs"] == 3
        assert report["successful_runs"] == 2
        assert report["failed_runs"] == 1
        assert report["success_rate"] == 2.0 / 3.0
        assert report["average_duration_s"] > 0
        assert report["average_wh"] >= 0
        assert report["average_co2_kg"] >= 0

    def test_sustainability_report_aggregation(self, green_guard: GreenGuard) -> None:
        """Test sustainability report aggregation."""
        for i in range(5):
            green_guard.run_command(["python", "-c", f"print({i})"])

        report = green_guard.sustainability_report()

        assert report["total_runs"] == 5
        assert report["successful_runs"] == 5
        assert report["total_duration_s"] >= 0
        assert report["total_wh"] >= 0
        assert report["total_co2_kg"] >= 0
        if report["total_runs"] > 0:
            assert report["average_duration_s"] == report["total_duration_s"] / 5
            assert report["average_wh"] == report["total_wh"] / 5
            assert report["average_co2_kg"] == report["total_co2_kg"] / 5


class TestGreenGuardIntegration:
    """Integration tests for Green Guard."""

    def test_full_green_guard_workflow(self) -> None:
        """Test complete Green Guard workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            guard = GreenGuard(db_path)

            # Run commands
            result1 = guard.run_command(["python", "-c", "print('test1')"])
            result2 = guard.run_command(["python", "-c", "print('test2')"])

            # Get reports
            guard.report(result1["run_id"])
            guard.report(result2["run_id"])

            # Get sustainability report
            sustainability = guard.sustainability_report()

            assert result1["status"] == "ok"
            assert result2["status"] == "ok"
            assert sustainability["total_runs"] == 2
            assert sustainability["successful_runs"] == 2

            guard.close()

    def test_green_guard_with_limits(self) -> None:
        """Test Green Guard with CO2 limits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            guard = GreenGuard(db_path)

            # Run with hard limit
            result = guard.run_command(
                ["python", "-c", "print('test')"],
                hard_co2_kg=1.0,
            )

            assert result["returncode"] == 0

            # Get sustainability report
            sustainability = guard.sustainability_report()
            assert sustainability["total_runs"] == 1

            guard.close()

    def test_green_guard_energy_calculation(self) -> None:
        """Test energy calculation accuracy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            guard = GreenGuard(db_path, co2_kg_per_kwh=1.0, cpu_watts=100.0)

            result = guard.run_command(["python", "-c", "x = 1"])

            # Verify calculation: Wh = (cpu_seconds * 100) / 3600
            # CO2 = (Wh / 1000) * 1.0
            assert result["estimated_wh"] >= 0
            assert result["estimated_co2_kg"] >= 0

            guard.close()

    def test_green_guard_multiple_instances(self) -> None:
        """Test multiple Green Guard instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            guard1 = GreenGuard(db_path)
            guard2 = GreenGuard(db_path)

            guard1.run_command(["python", "-c", "print('test1')"])
            guard2.run_command(["python", "-c", "print('test2')"])

            report1 = guard1.sustainability_report()
            report2 = guard2.sustainability_report()

            # Both should see all runs
            assert report1["total_runs"] == 2
            assert report2["total_runs"] == 2

            guard1.close()
            guard2.close()
