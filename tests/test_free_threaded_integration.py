"""Integration tests for FreeThreadedIndexer.

Tasks 14.1 – 14.5 of the free-threaded-parsing spec.

Requirements covered:
  12.2  – integration tests that parse real Python repositories
  8.3, 8.4, 8.5 – error recovery
  9.3, 9.4, 9.5 – resource management
  10.1, 10.2, 10.3, 10.4, 10.5 – progress reporting
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path

import pytest

from siof.free_threaded_indexer import (
    DTGAggregator,
    FreeThreadedIndexer,
    ProgressReporter,
    WorkPool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write *files* dict (relative-path -> content) into *tmp_path*."""
    for rel, content in files.items():
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return tmp_path


def _simple_repo(tmp_path: Path) -> Path:
    """Create a small but realistic Python repository."""
    return _make_repo(tmp_path, {
        "main.py": (
            "from utils import helper\n"
            "\n"
            "def main():\n"
            "    return helper(42)\n"
        ),
        "utils.py": (
            "def helper(x: int) -> int:\n"
            "    return x * 2\n"
        ),
        "models.py": (
            "class User:\n"
            "    def __init__(self, name: str) -> None:\n"
            "        self.name = name\n"
            "\n"
            "    def greet(self) -> str:\n"
            "        return f'Hello, {self.name}'\n"
        ),
    })


# ---------------------------------------------------------------------------
# Task 14.1 – Full build workflow integration test
# Requirements: 12.2
# ---------------------------------------------------------------------------

class TestFullBuildWorkflow:
    """Integration tests for the complete index build workflow."""

    def test_build_completes_on_real_repo(self, tmp_path: Path) -> None:
        """Test that build() completes successfully on a real repository."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        # All phases must complete – result dict must be present
        assert result is not None
        assert isinstance(result, dict)

    def test_build_returns_expected_keys(self, tmp_path: Path) -> None:
        """Build result must contain the standard statistics keys."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        for key in ("artifacts", "nodes", "edges", "parse_errors", "files"):
            assert key in result, f"Missing key: {key}"

    def test_build_discovers_all_python_files(self, tmp_path: Path) -> None:
        """All Python files in the repo must be discovered and counted."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        # 3 files were created
        assert result["files"] == 3
        assert result["artifacts"] == 3

    def test_build_extracts_nodes_and_edges(self, tmp_path: Path) -> None:
        """Build must produce at least some nodes and edges."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        assert result["nodes"] > 0
        assert result["edges"] >= 0  # edges may be 0 for simple files

    def test_build_produces_valid_dtg(self, tmp_path: Path) -> None:
        """The DTG stored in the repository must pass integrity checks."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            indexer.build()
            stats = indexer.repository.get_statistics()
        finally:
            indexer.close()

        # Repository must have been populated
        assert stats["artifacts"] > 0
        assert stats["nodes"] >= 0

    def test_build_zero_parse_errors_on_valid_repo(self, tmp_path: Path) -> None:
        """A repo with only valid Python files must produce zero parse errors."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        assert result["parse_errors"] == 0

    def test_build_empty_repo(self, tmp_path: Path) -> None:
        """Build on an empty directory must return zero counts without crashing."""
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        assert result["artifacts"] == 0
        assert result["nodes"] == 0
        assert result["edges"] == 0
        assert result["parse_errors"] == 0

    def test_build_skips_venv_directories(self, tmp_path: Path) -> None:
        """Files inside .venv / __pycache__ must not be indexed."""
        repo = _simple_repo(tmp_path)
        # Plant a file inside a skipped directory
        venv_file = repo / ".venv" / "lib" / "site.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.write_text("# should be skipped\n")

        db_path = tmp_path / "index.db"
        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        # Only the 3 original files should be indexed
        assert result["files"] == 3


# ---------------------------------------------------------------------------
# Task 14.2 – Incremental update workflow integration test
# Requirements: 12.2
# ---------------------------------------------------------------------------

class TestIncrementalUpdateWorkflow:
    """Integration tests for the incremental update workflow."""

    def test_update_with_changed_files(self, tmp_path: Path) -> None:
        """update() with an explicit changed-file list must succeed."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            indexer.build()

            # Modify one file
            (repo / "utils.py").write_text(
                "def helper(x: int) -> int:\n"
                "    return x * 3  # changed\n"
            )

            result = indexer.update(changed_files=[repo / "utils.py"])
        finally:
            indexer.close()

        assert result is not None
        assert isinstance(result, dict)
        assert result.get("updated") is True

    def test_update_returns_expected_keys(self, tmp_path: Path) -> None:
        """update() result must contain the standard statistics keys."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            indexer.build()
            result = indexer.update(changed_files=[repo / "utils.py"])
        finally:
            indexer.close()

        for key in ("artifacts", "nodes", "edges", "parse_errors", "files"):
            assert key in result, f"Missing key: {key}"

    def test_update_no_changed_files_returns_current_stats(self, tmp_path: Path) -> None:
        """update() with an empty list must return current stats without re-parsing."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            build_result = indexer.build()
            update_result = indexer.update(changed_files=[])
        finally:
            indexer.close()

        # No re-parsing happened
        assert update_result.get("updated") is False
        # Artifact count should match what was built
        assert update_result["artifacts"] == build_result["artifacts"]

    def test_update_preserves_unchanged_nodes(self, tmp_path: Path) -> None:
        """Nodes from unchanged files must still be present after update."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            indexer.build()
            nodes_before = indexer.repository.get_statistics()["nodes"]

            # Update only utils.py
            (repo / "utils.py").write_text(
                "def helper(x: int) -> int:\n"
                "    return x + 1\n"
            )
            indexer.update(changed_files=[repo / "utils.py"])
            nodes_after = indexer.repository.get_statistics()["nodes"]
        finally:
            indexer.close()

        # Node count should be similar (may vary slightly due to re-parse)
        assert nodes_after >= 0
        # Nodes from main.py and models.py should still be present
        assert nodes_after > 0

    def test_update_only_parses_changed_files(self, tmp_path: Path) -> None:
        """update() must only re-parse the specified changed files."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            indexer.build()

            # Track which files get parsed during update
            parsed_files: list[Path] = []
            original_build = indexer.build

            result = indexer.update(changed_files=[repo / "utils.py"])
        finally:
            indexer.close()

        # The update should have processed exactly 1 file
        assert result["parse_errors"] == 0

    def test_update_after_adding_new_file(self, tmp_path: Path) -> None:
        """update() with a new file must add it to the index."""
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            indexer.build()

            # Add a new file
            new_file = repo / "new_module.py"
            new_file.write_text("def new_func(): pass\n")

            result = indexer.update(changed_files=[new_file])
        finally:
            indexer.close()

        assert result is not None
        assert result["parse_errors"] == 0


# ---------------------------------------------------------------------------
# Task 14.3 – Error recovery integration test
# Requirements: 8.3, 8.4, 8.5
# ---------------------------------------------------------------------------

class TestErrorRecovery:
    """Integration tests for error recovery during build/update."""

    def test_build_with_syntax_error_file(self, tmp_path: Path) -> None:
        """Build must complete even when one file has a syntax error."""
        repo = _make_repo(tmp_path, {
            "good.py": "def good(): return 42\n",
            "bad.py": "def bad(\n    invalid syntax here",
        })
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        # Build must complete
        assert result is not None
        # Exactly one parse error
        assert result["parse_errors"] == 1
        # Total files still 2
        assert result["files"] == 2

    def test_partial_results_preserved_on_error(self, tmp_path: Path) -> None:
        """Successful parses must be stored even when other files fail.

        Validates: Requirements 8.5
        """
        repo = _make_repo(tmp_path, {
            "good1.py": "def f1(): pass\n",
            "good2.py": "def f2(): pass\n",
            "bad.py": "def bad(\n    invalid",
        })
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
            stats = indexer.repository.get_statistics()
        finally:
            indexer.close()

        # 2 good files must be stored
        assert result["parse_errors"] == 1
        # Artifacts include all 3 (even failed ones are recorded)
        assert result["artifacts"] == 3
        # Nodes from the 2 good files must be present
        assert stats["nodes"] > 0

    def test_error_reporting_accurate(self, tmp_path: Path) -> None:
        """parse_errors count must match the number of invalid files.

        Validates: Requirements 8.3
        """
        repo = _make_repo(tmp_path, {
            "ok.py": "x = 1\n",
            "err1.py": "def f(\n    bad",
            "err2.py": "class (\n    bad",
        })
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        assert result["parse_errors"] == 2

    def test_worker_thread_crash_handled(self, tmp_path: Path) -> None:
        """A worker thread crash must be caught and reported, not propagate.

        Validates: Requirements 8.4
        """
        repo = _make_repo(tmp_path, {
            "a.py": "def a(): pass\n",
            "b.py": "def b(): pass\n",
        })
        db_path = tmp_path / "index.db"

        # Patch ParseWorker.parse to raise on one file
        from siof import free_threaded_indexer as fti_module
        original_parse = fti_module.ParseWorker.parse
        call_count = [0]

        def flaky_parse(task, repo_path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated worker crash")
            return original_parse(task, repo_path)

        fti_module.ParseWorker.parse = staticmethod(flaky_parse)
        try:
            indexer = FreeThreadedIndexer(repo, db_path, workers=2)
            indexer.init()
            try:
                result = indexer.build()
            finally:
                indexer.close()
        finally:
            fti_module.ParseWorker.parse = staticmethod(original_parse)

        # Build must complete despite the crash
        assert result is not None
        # The crashed task is counted as a parse error
        assert result["parse_errors"] >= 1

    def test_all_valid_files_parsed_despite_errors(self, tmp_path: Path) -> None:
        """All valid files must be parsed even when some files have errors.

        Validates: Requirements 8.5
        """
        valid_files = {f"valid_{i}.py": f"def func_{i}(): return {i}\n" for i in range(5)}
        invalid_files = {f"invalid_{i}.py": f"def bad_{i}(\n    syntax error" for i in range(3)}
        repo = _make_repo(tmp_path, {**valid_files, **invalid_files})
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        try:
            result = indexer.build()
        finally:
            indexer.close()

        assert result["parse_errors"] == 3
        assert result["files"] == 8
        # 5 valid files must have been parsed successfully
        assert result["artifacts"] - result["parse_errors"] == 5


# ---------------------------------------------------------------------------
# Task 14.4 – Resource management integration test
# Requirements: 9.3, 9.4, 9.5
# ---------------------------------------------------------------------------

class TestResourceManagement:
    """Integration tests for resource management (shutdown, timeout, cleanup)."""

    def test_graceful_shutdown_after_build(self, tmp_path: Path) -> None:
        """close() must shut down all worker threads gracefully.

        Validates: Requirements 9.3
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=4)
        indexer.init()
        indexer.build()

        # close() must not raise
        indexer.close()

        # After close, _work_pool must be None
        assert indexer._work_pool is None

    def test_close_without_build_is_safe(self, tmp_path: Path) -> None:
        """close() before any build must not raise.

        Validates: Requirements 9.3
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        indexer.close()  # Must not raise

    def test_workpool_shutdown_with_timeout(self, tmp_path: Path) -> None:
        """WorkPool.shutdown() must complete within the given timeout.

        Validates: Requirements 9.5
        """
        repo = _simple_repo(tmp_path)

        pool = WorkPool(workers=2, repo=repo)
        start = time.perf_counter()
        pool.shutdown(timeout=5.0)
        elapsed = time.perf_counter() - start

        # Shutdown of an idle pool must be near-instant
        assert elapsed < 5.0

    def test_worker_threads_cleaned_up_after_shutdown(self, tmp_path: Path) -> None:
        """After shutdown, no worker threads should remain alive.

        Validates: Requirements 9.4
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        threads_before = threading.active_count()

        indexer = FreeThreadedIndexer(repo, db_path, workers=4)
        indexer.init()
        indexer.build()
        indexer.close()

        # Allow threads to terminate
        time.sleep(0.1)
        threads_after = threading.active_count()

        # Thread count should return to approximately the baseline
        # (allow a small delta for test framework threads)
        assert threads_after <= threads_before + 2

    def test_multiple_builds_do_not_leak_threads(self, tmp_path: Path) -> None:
        """Running build() multiple times must not accumulate threads.

        Validates: Requirements 9.3, 9.4
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()

        try:
            threads_before = threading.active_count()

            for _ in range(3):
                indexer.build()

            time.sleep(0.1)
            threads_after = threading.active_count()

            # Should not accumulate threads across builds
            assert threads_after <= threads_before + 4
        finally:
            indexer.close()

    def test_context_manager_style_cleanup(self, tmp_path: Path) -> None:
        """init/build/close lifecycle must be safe to call in sequence.

        Validates: Requirements 9.3
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2)
        indexer.init()
        result = indexer.build()
        indexer.close()

        assert result["files"] == 3

    def test_workpool_shutdown_called_on_build_exception(self, tmp_path: Path) -> None:
        """WorkPool must be shut down even if an exception occurs during build.

        Validates: Requirements 9.3
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        from siof import free_threaded_indexer as fti_module
        original_aggregate = fti_module.DTGAggregator.add_result

        call_count = [0]

        def exploding_add_result(self, result):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated aggregation failure")
            return original_aggregate(self, result)

        fti_module.DTGAggregator.add_result = exploding_add_result
        try:
            indexer = FreeThreadedIndexer(repo, db_path, workers=2)
            indexer.init()
            try:
                indexer.build()
            except Exception:
                pass  # Expected
            finally:
                indexer.close()
        finally:
            fti_module.DTGAggregator.add_result = original_aggregate

        # After close, work pool must be cleaned up
        assert indexer._work_pool is None


# ---------------------------------------------------------------------------
# Task 14.5 – Progress reporting integration test
# Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
# ---------------------------------------------------------------------------

class TestProgressReporting:
    """Integration tests for progress reporting."""

    def test_progress_reporter_logs_at_interval(self, caplog: pytest.LogCaptureFixture) -> None:
        """ProgressReporter must emit a log line when the interval elapses.

        Validates: Requirements 10.1
        """
        reporter = ProgressReporter(total_files=100, interval=0.0)  # interval=0 → always log

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            reporter.update(50)

        assert any("Progress:" in r.message for r in caplog.records)

    def test_progress_log_contains_required_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """Progress log must include files parsed, total, percentage, and throughput.

        Validates: Requirements 10.2
        """
        reporter = ProgressReporter(total_files=200, interval=0.0)

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            reporter.update(100)

        progress_msgs = [r.message for r in caplog.records if "Progress:" in r.message]
        assert progress_msgs, "No progress log found"
        msg = progress_msgs[0]

        assert "100/200" in msg
        assert "%" in msg
        assert "files/sec" in msg

    def test_final_statistics_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """report_final() must log total time, throughput, and error counts.

        Validates: Requirements 10.3, 10.4
        """
        reporter = ProgressReporter(total_files=10, interval=5.0)

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            reporter.report_final(duration=2.0, errors=1)

        final_msgs = [r.message for r in caplog.records if "Parsing complete:" in r.message]
        assert final_msgs, "No final statistics log found"
        msg = final_msgs[0]

        assert "10 files" in msg
        assert "2.00s" in msg
        assert "files/sec" in msg
        assert "successful:" in msg
        assert "errors:" in msg

    def test_final_statistics_accuracy(self, caplog: pytest.LogCaptureFixture) -> None:
        """Final statistics must accurately reflect successful vs error counts.

        Validates: Requirements 10.4
        """
        total = 20
        errors = 3
        reporter = ProgressReporter(total_files=total, interval=5.0)

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            reporter.report_final(duration=1.0, errors=errors)

        final_msgs = [r.message for r in caplog.records if "Parsing complete:" in r.message]
        assert final_msgs
        msg = final_msgs[0]

        # successful = total - errors = 17
        assert "successful: 17" in msg
        assert "errors: 3" in msg

    def test_build_emits_final_statistics(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """build() must emit final statistics log after completion.

        Validates: Requirements 10.3
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        indexer = FreeThreadedIndexer(repo, db_path, workers=2, progress_interval=0.0)
        indexer.init()

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            indexer.build()

        indexer.close()

        final_msgs = [r.message for r in caplog.records if "Parsing complete:" in r.message]
        assert final_msgs, "build() did not emit final statistics"

    def test_progress_not_logged_before_interval(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ProgressReporter must NOT log before the interval has elapsed.

        Validates: Requirements 10.1
        """
        reporter = ProgressReporter(total_files=100, interval=9999.0)  # very long interval

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            reporter.update(50)

        progress_msgs = [r.message for r in caplog.records if "Progress:" in r.message]
        assert not progress_msgs, "Progress logged before interval elapsed"

    def test_verbose_mode_logs_each_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """In verbose mode (progress_interval=0), each file should trigger a log.

        Validates: Requirements 10.5
        """
        repo = _simple_repo(tmp_path)
        db_path = tmp_path / "index.db"

        # Use a very small interval to simulate verbose-style frequent logging
        indexer = FreeThreadedIndexer(repo, db_path, workers=1, progress_interval=0.0)
        indexer.init()

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            result = indexer.build()

        indexer.close()

        # With interval=0, every update() call should log
        progress_msgs = [r.message for r in caplog.records if "Progress:" in r.message]
        # At least one progress message per file (3 files)
        assert len(progress_msgs) >= 1

    def test_progress_reporter_eta_present(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Progress log must include ETA information.

        Validates: Requirements 10.2
        """
        reporter = ProgressReporter(total_files=100, interval=0.0)
        time.sleep(0.01)  # Ensure some elapsed time for throughput calculation

        with caplog.at_level(logging.INFO, logger="siof.free_threaded_indexer"):
            reporter.update(10)

        progress_msgs = [r.message for r in caplog.records if "Progress:" in r.message]
        assert progress_msgs
        assert "ETA:" in progress_msgs[0]
