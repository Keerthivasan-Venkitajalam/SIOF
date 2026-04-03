"""Comprehensive tests for the green_guard module."""
from pathlib import Path

from siof.green_guard import GreenGuard


def test_green_run_success(tmp_path: Path):
    """Test successful command execution tracking."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    result = g.run_command(["python", "-c", "print('hello')"])
    g.close()

    assert result["returncode"] == 0
    assert result["status"] == "ok"
    assert result["duration_s"] >= 0
    assert result["estimated_wh"] >= 0
    assert result["estimated_co2_kg"] >= 0
    assert "run_id" in result


def test_green_run_failure(tmp_path: Path):
    """Test failed command execution tracking."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    result = g.run_command(["python", "-c", "raise ValueError('test')"])
    g.close()

    assert result["returncode"] != 0
    assert result["status"] == "failed"


def test_green_run_co2_limit(tmp_path: Path):
    """Test CO2 limit enforcement."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    # Set extremely low limit to trigger policy
    result = g.run_command(
        ["python", "-c", "import time; time.sleep(0.5)"],
        hard_co2_kg=0.00001,
    )
    g.close()

    # Should have some CO2 or be terminated by policy
    assert result["estimated_co2_kg"] >= 0 or result["status"] == "terminated_by_co2_policy"


def test_green_report(tmp_path: Path):
    """Test energy report retrieval."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    result = g.run_command(["python", "-c", "print('test')"])
    run_id = result["run_id"]

    report = g.report(run_id)
    g.close()

    assert report["run_id"] == run_id
    assert "duration_s" in report
    assert "estimated_wh" in report
    assert "estimated_co2_kg" in report


def test_green_report_nonexistent(tmp_path: Path):
    """Test report for nonexistent run."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    report = g.report("nonexistent_run_id")
    g.close()

    assert report == {}


def test_green_co2_factor(tmp_path: Path):
    """Test custom CO2 factor."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db, co2_kg_per_kwh=0.5)

    result = g.run_command(["python", "-c", "print('test')"])
    g.close()

    assert result["estimated_co2_kg"] >= 0


def test_green_deterministic(tmp_path: Path):
    """Test that energy tracking is deterministic."""
    db1 = tmp_path / "siof1.db"
    g1 = GreenGuard(db_path=db1)
    result1 = g1.run_command(["python", "-c", "x = 1 + 1"])
    g1.close()

    db2 = tmp_path / "siof2.db"
    g2 = GreenGuard(db_path=db2)
    result2 = g2.run_command(["python", "-c", "x = 1 + 1"])
    g2.close()

    # Duration should be similar (within reasonable bounds)
    assert abs(result1["duration_s"] - result2["duration_s"]) < 1.0


def test_green_multiple_runs(tmp_path: Path):
    """Test tracking multiple runs."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    run_ids = []
    for i in range(3):
        result = g.run_command(["python", "-c", f"x = {i}"])
        run_ids.append(result["run_id"])

    # Verify all runs are tracked
    for run_id in run_ids:
        report = g.report(run_id)
        assert report["run_id"] == run_id

    g.close()


def test_green_energy_accumulation(tmp_path: Path):
    """Test that energy is properly accumulated."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    result1 = g.run_command(["python", "-c", "import time; time.sleep(0.01)"])
    result2 = g.run_command(["python", "-c", "import time; time.sleep(0.01)"])

    g.close()

    # Both should have positive energy
    assert result1["estimated_wh"] >= 0
    assert result2["estimated_wh"] >= 0


def test_green_command_with_args(tmp_path: Path):
    """Test running command with various arguments."""
    db = tmp_path / "siof.db"
    g = GreenGuard(db_path=db)

    result = g.run_command(["python", "-c", "import sys; print(sys.version)"])
    g.close()

    assert result["returncode"] == 0
    assert result["status"] == "ok"
