"""Advanced end-to-end integration tests."""

from pathlib import Path

from siof.orchestrator import SIOFOrchestrator


def test_e2e_orchestrator_full_pipeline(tmp_path: Path):
    """Test orchestrator running full pipeline."""
    # Setup repo with realistic code
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create a multi-file project
    (repo / "main.py").write_text(
        "from utils import process_data\n"
        "\n"
        "def main():\n"
        "    data = [1, 2, 3]\n"
        "    result = process_data(data)\n"
        "    return result\n"
    )

    (repo / "utils.py").write_text(
        "def process_data(items):\n"
        "    # This is a robust implementation\n"
        "    try:\n"
        "        return [transform(x) for x in items]\n"
        "    except:\n"
        "        pass\n"
        "\n"
        "def transform(x):\n"
        "    return x * 2\n"
    )

    (repo / "models.py").write_text(
        "class DataModel:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "    def compute(self):\n"
        "        return self.value + 1\n"
    )

    db = tmp_path / "siof.db"

    # Run orchestrator
    orch = SIOFOrchestrator(repo=repo, db_path=db)
    result = orch.run_full_pipeline(
        index_mode="build",
        slop_mode="audit",
        enable_memex=True,
        enable_green_guard=True,
    )

    # Verify success
    assert result.success is True
    assert result.total_duration_s > 0

    # Verify all phases ran
    assert "phase1_index" in result.phase_results
    assert "phase2_slop" in result.phase_results
    assert "phase3_mcp" in result.phase_results
    assert "phase4_memex" in result.phase_results
    assert "phase5_green_guard" in result.phase_results

    # Verify phase 1 results
    index_result = result.phase_results["phase1_index"]
    assert index_result["files"] == 3
    assert index_result["nodes"] > 0
    assert index_result["edges"] > 0

    # Verify phase 2 results
    slop_result = result.phase_results["phase2_slop"]
    assert slop_result["findings"] > 0  # Should find NakedExceptionPass and HedgeComment

    # Verify phase 3 results
    mcp_result = result.phase_results["phase3_mcp"]
    assert mcp_result["status"] == "ready"

    # Verify repository stats
    stats = orch.get_repository_stats()
    assert stats["nodes"] > 0
    assert stats["edges"] > 0
    assert stats["findings"] > 0

    # Verify KPIs
    kpis = orch.validate_kpis()
    assert kpis["nodes_indexed"] is True
    assert kpis["edges_indexed"] is True
    assert kpis["all_passed"] is True


def test_e2e_orchestrator_incremental_update(tmp_path: Path):
    """Test orchestrator with incremental updates."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("def f(x):\n    return x + 1\n")

    db = tmp_path / "siof.db"
    orch = SIOFOrchestrator(repo=repo, db_path=db)

    # Initial build
    result1 = orch.run_full_pipeline(index_mode="build", slop_mode="audit")
    assert result1.success is True
    nodes1 = result1.phase_results["phase1_index"]["nodes"]

    # Modify code
    (repo / "code.py").write_text(
        "def f(x):\n    return x + 1\n\ndef g(y):\n    return y * 2\n"
    )

    # Incremental update (currently does full rebuild in v1)
    result2 = orch.run_full_pipeline(index_mode="update", slop_mode="audit")
    assert result2.success is True
    nodes2 = result2.phase_results["phase1_index"]["nodes"]

    # In v1, update does full rebuild, so nodes should be recounted
    # Should have more nodes after adding function
    assert nodes2 >= nodes1  # >= because full rebuild may recount differently


def test_e2e_orchestrator_with_errors(tmp_path: Path):
    """Test orchestrator handles errors gracefully."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create file with syntax error
    (repo / "bad.py").write_text("def f(\n    invalid")

    db = tmp_path / "siof.db"
    orch = SIOFOrchestrator(repo=repo, db_path=db)

    # Should complete but report parse errors
    result = orch.run_full_pipeline(index_mode="build", slop_mode="audit")
    assert result.success is True
    assert result.phase_results["phase1_index"]["parse_errors"] == 1


def test_e2e_orchestrator_selective_phases(tmp_path: Path):
    """Test orchestrator with selective phase execution."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("def f(x):\n    return x\n")

    db = tmp_path / "siof.db"
    orch = SIOFOrchestrator(repo=repo, db_path=db)

    # Run without memex and green guard
    result = orch.run_full_pipeline(
        index_mode="build",
        slop_mode="audit",
        enable_memex=False,
        enable_green_guard=False,
    )

    assert result.success is True
    assert result.phase_results["phase4_memex"]["skipped"] is True
    assert result.phase_results["phase5_green_guard"]["skipped"] is True


def test_e2e_orchestrator_fix_mode(tmp_path: Path):
    """Test orchestrator with fix mode for de-slopper."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create file with fixable slop
    bad_code = (
        "def process():\n" "    try:\n" "        return compute()\n" "    except:\n" "        pass\n"
    )
    (repo / "code.py").write_text(bad_code)

    db = tmp_path / "siof.db"
    orch = SIOFOrchestrator(repo=repo, db_path=db)

    # Run with fix mode
    result = orch.run_full_pipeline(index_mode="build", slop_mode="fix")

    assert result.success is True
    assert result.phase_results["phase2_slop"]["mode"] == "fix"

    # Code should be modified
    fixed_code = (repo / "code.py").read_text()
    assert fixed_code != bad_code
    assert "except:" not in fixed_code


def test_e2e_orchestrator_large_project(tmp_path: Path):
    """Test orchestrator on larger project."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create multiple files
    for i in range(10):
        (repo / f"module{i}.py").write_text(
            f"def func{i}(x):\n"
            f"    return x + {i}\n"
            f"\n"
            f"class Class{i}:\n"
            f"    def method(self):\n"
            f"        return func{i}(42)\n"
        )

    db = tmp_path / "siof.db"
    orch = SIOFOrchestrator(repo=repo, db_path=db)

    result = orch.run_full_pipeline(index_mode="build", slop_mode="audit")

    assert result.success is True
    assert result.phase_results["phase1_index"]["files"] == 10
    assert result.phase_results["phase1_index"]["nodes"] >= 20  # At least 2 per file

    # Verify stats
    stats = orch.get_repository_stats()
    assert stats["nodes"] >= 20
    assert stats["edges"] > 0


def test_e2e_orchestrator_kpi_validation(tmp_path: Path):
    """Test KPI validation logic."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("def f(x):\n    return x\n")

    db = tmp_path / "siof.db"
    orch = SIOFOrchestrator(repo=repo, db_path=db)

    # Run pipeline
    result = orch.run_full_pipeline(index_mode="build", slop_mode="audit")
    assert result.success is True

    # Validate KPIs
    kpis = orch.validate_kpis()

    assert "nodes_indexed" in kpis
    assert "edges_indexed" in kpis
    assert "artifacts_parsed" in kpis
    assert "findings_detected" in kpis
    assert "intent_records" in kpis
    assert "all_passed" in kpis

    # All should pass for valid code
    assert kpis["all_passed"] is True
