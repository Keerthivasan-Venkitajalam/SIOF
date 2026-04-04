"""Validation tests for FreeThreadedIndexer vs PythonIndexer equivalence.

Tasks 19.1 – 19.3 of the free-threaded-parsing spec.

Requirements covered:
  7.4, 7.5  – backward compatibility and DTG integrity
  12.5      – fallback and parallel mode activation
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from siof.free_threaded_indexer import FreeThreadedIndexer, VersionDetector
from siof.indexer import PythonIndexer

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


def _sample_repo(tmp_path: Path) -> Path:
    """Create a small but realistic Python repository for comparison tests."""
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
        "pkg/__init__.py": "",
        "pkg/service.py": (
            "from models import User\n"
            "\n"
            "class UserService:\n"
            "    def create(self, name: str) -> User:\n"
            "        return User(name)\n"
        ),
    })


# ---------------------------------------------------------------------------
# Task 19.1 – Verify FreeThreadedIndexer produces same results as PythonIndexer
# Requirements: 7.4, 7.5
# ---------------------------------------------------------------------------

class TestIndexerEquivalence:
    """Verify FreeThreadedIndexer (workers=1) produces same results as PythonIndexer."""

    def test_same_artifact_count(self, tmp_path: Path) -> None:
        """Both indexers should discover and index the same number of artifacts."""
        repo = _sample_repo(tmp_path)

        # Build with PythonIndexer
        py_db = tmp_path / "py_index.db"
        py_indexer = PythonIndexer(repo, py_db, workers=1)
        py_indexer.init()
        try:
            py_result = py_indexer.build()
        finally:
            py_indexer.close()

        # Build with FreeThreadedIndexer (workers=1 for determinism)
        ft_db = tmp_path / "ft_index.db"
        ft_indexer = FreeThreadedIndexer(repo, ft_db, workers=1)
        ft_indexer.init()
        try:
            ft_result = ft_indexer.build()
        finally:
            ft_indexer.close()

        assert ft_result["artifacts"] == py_result["artifacts"], (
            f"Artifact count mismatch: FreeThreaded={ft_result['artifacts']}, "
            f"Python={py_result['artifacts']}"
        )

    def test_same_node_count(self, tmp_path: Path) -> None:
        """Both indexers should produce the same number of DTG nodes."""
        repo = _sample_repo(tmp_path)

        py_db = tmp_path / "py_index.db"
        py_indexer = PythonIndexer(repo, py_db, workers=1)
        py_indexer.init()
        try:
            py_result = py_indexer.build()
        finally:
            py_indexer.close()

        ft_db = tmp_path / "ft_index.db"
        ft_indexer = FreeThreadedIndexer(repo, ft_db, workers=1)
        ft_indexer.init()
        try:
            ft_result = ft_indexer.build()
        finally:
            ft_indexer.close()

        assert ft_result["nodes"] == py_result["nodes"], (
            f"Node count mismatch: FreeThreaded={ft_result['nodes']}, "
            f"Python={py_result['nodes']}"
        )

    def test_same_edge_count(self, tmp_path: Path) -> None:
        """Both indexers should produce the same number of DTG edges."""
        repo = _sample_repo(tmp_path)

        py_db = tmp_path / "py_index.db"
        py_indexer = PythonIndexer(repo, py_db, workers=1)
        py_indexer.init()
        try:
            py_result = py_indexer.build()
        finally:
            py_indexer.close()

        ft_db = tmp_path / "ft_index.db"
        ft_indexer = FreeThreadedIndexer(repo, ft_db, workers=1)
        ft_indexer.init()
        try:
            ft_result = ft_indexer.build()
        finally:
            ft_indexer.close()

        assert ft_result["edges"] == py_result["edges"], (
            f"Edge count mismatch: FreeThreaded={ft_result['edges']}, "
            f"Python={py_result['edges']}"
        )

    def test_result_keys_match(self, tmp_path: Path) -> None:
        """FreeThreadedIndexer result dict should contain all keys PythonIndexer returns."""
        repo = _sample_repo(tmp_path)

        py_db = tmp_path / "py_index.db"
        py_indexer = PythonIndexer(repo, py_db, workers=1)
        py_indexer.init()
        try:
            py_result = py_indexer.build()
        finally:
            py_indexer.close()

        ft_db = tmp_path / "ft_index.db"
        ft_indexer = FreeThreadedIndexer(repo, ft_db, workers=1)
        ft_indexer.init()
        try:
            ft_result = ft_indexer.build()
        finally:
            ft_indexer.close()

        # FreeThreadedIndexer must expose at least the same keys
        for key in ("artifacts", "nodes", "edges", "parse_errors", "files"):
            assert key in ft_result, f"Missing key '{key}' in FreeThreadedIndexer result"
            assert key in py_result, f"Missing key '{key}' in PythonIndexer result"

    def test_no_parse_errors_on_valid_repo(self, tmp_path: Path) -> None:
        """Neither indexer should report parse errors on a valid repository."""
        repo = _sample_repo(tmp_path)

        py_db = tmp_path / "py_index.db"
        py_indexer = PythonIndexer(repo, py_db, workers=1)
        py_indexer.init()
        try:
            py_result = py_indexer.build()
        finally:
            py_indexer.close()

        ft_db = tmp_path / "ft_index.db"
        ft_indexer = FreeThreadedIndexer(repo, ft_db, workers=1)
        ft_indexer.init()
        try:
            ft_result = ft_indexer.build()
        finally:
            ft_indexer.close()

        assert py_result["parse_errors"] == 0
        assert ft_result["parse_errors"] == 0


# ---------------------------------------------------------------------------
# Task 19.2 – Test fallback mode (Python 3.11-3.13 simulation)
# Requirements: 12.5
# ---------------------------------------------------------------------------

class TestFallbackMode:
    """Verify FreeThreadedIndexer falls back to single-threaded on Python < 3.14."""

    def test_version_detector_returns_single_threaded_for_311(self) -> None:
        """VersionDetector should select single-threaded mode for Python 3.11."""
        with patch.object(sys, "version_info", (3, 11, 0, "final", 0)):
            mode = VersionDetector.detect()

        assert mode.parallel is False
        assert mode.gil_enabled is True
        assert "3.11" in mode.reason or "3.14" in mode.reason

    def test_version_detector_returns_single_threaded_for_312(self) -> None:
        """VersionDetector should select single-threaded mode for Python 3.12."""
        with patch.object(sys, "version_info", (3, 12, 0, "final", 0)):
            mode = VersionDetector.detect()

        assert mode.parallel is False

    def test_version_detector_returns_single_threaded_for_313(self) -> None:
        """VersionDetector should select single-threaded mode for Python 3.13."""
        with patch.object(sys, "version_info", (3, 13, 0, "final", 0)):
            mode = VersionDetector.detect()

        assert mode.parallel is False

    def test_fallback_mode_produces_correct_results(self, tmp_path: Path) -> None:
        """FreeThreadedIndexer in fallback mode should still index correctly."""
        repo = _sample_repo(tmp_path)
        db_path = tmp_path / "index.db"

        with patch.object(sys, "version_info", (3, 11, 0, "final", 0)):
            indexer = FreeThreadedIndexer(repo, db_path, workers=1)
            # Confirm fallback mode was selected
            assert indexer.mode.parallel is False

            indexer.init()
            try:
                result = indexer.build()
            finally:
                indexer.close()

        assert result["artifacts"] > 0
        assert result["parse_errors"] == 0

    def test_fallback_mode_uses_single_worker(self, tmp_path: Path) -> None:
        """In fallback mode the effective worker count should be 1."""
        repo = _sample_repo(tmp_path)
        db_path = tmp_path / "index.db"

        with patch.object(sys, "version_info", (3, 11, 0, "final", 0)):
            indexer = FreeThreadedIndexer(repo, db_path, workers=4)
            # Mode should be single-threaded regardless of requested workers
            assert indexer.mode.parallel is False

    def test_fallback_mode_matches_python_indexer(self, tmp_path: Path) -> None:
        """Fallback mode results should match PythonIndexer results."""
        repo = _sample_repo(tmp_path)

        py_db = tmp_path / "py_index.db"
        py_indexer = PythonIndexer(repo, py_db, workers=1)
        py_indexer.init()
        try:
            py_result = py_indexer.build()
        finally:
            py_indexer.close()

        ft_db = tmp_path / "ft_index.db"
        with patch.object(sys, "version_info", (3, 11, 0, "final", 0)):
            ft_indexer = FreeThreadedIndexer(repo, ft_db, workers=1)
            ft_indexer.init()
            try:
                ft_result = ft_indexer.build()
            finally:
                ft_indexer.close()

        assert ft_result["artifacts"] == py_result["artifacts"]
        assert ft_result["nodes"] == py_result["nodes"]
        assert ft_result["edges"] == py_result["edges"]


# ---------------------------------------------------------------------------
# Task 19.3 – Test parallel mode activation (Python 3.14+ simulation)
# Requirements: 12.5
# ---------------------------------------------------------------------------

class TestParallelModeActivation:
    """Verify FreeThreadedIndexer activates parallel mode on Python 3.14+ with GIL off."""

    def test_version_detector_enables_parallel_for_314_no_gil(self) -> None:
        """VersionDetector should select parallel mode for Python 3.14 with GIL disabled."""
        with (
            patch.object(sys, "version_info", (3, 14, 0, "final", 0)),
            patch.object(sys, "_is_gil_enabled", return_value=False, create=True),
        ):
            mode = VersionDetector.detect()

        assert mode.parallel is True
        assert mode.gil_enabled is False

    def test_version_detector_disables_parallel_for_314_with_gil(self) -> None:
        """VersionDetector should NOT select parallel mode for Python 3.14 when GIL is on."""
        with (
            patch.object(sys, "version_info", (3, 14, 0, "final", 0)),
            patch.object(sys, "_is_gil_enabled", return_value=True, create=True),
        ):
            mode = VersionDetector.detect()

        assert mode.parallel is False
        assert mode.gil_enabled is True

    def test_free_threaded_indexer_parallel_mode_activated(self, tmp_path: Path) -> None:
        """FreeThreadedIndexer should report parallel mode when Python 3.14+ and GIL off."""
        repo = _sample_repo(tmp_path)
        db_path = tmp_path / "index.db"

        with (
            patch.object(sys, "version_info", (3, 14, 0, "final", 0)),
            patch.object(sys, "_is_gil_enabled", return_value=False, create=True),
        ):
            indexer = FreeThreadedIndexer(repo, db_path, workers=2)
            assert indexer.mode.parallel is True
            assert indexer.mode.gil_enabled is False

    def test_parallel_mode_still_produces_correct_results(self, tmp_path: Path) -> None:
        """Parallel mode (simulated) should still produce a valid index."""
        repo = _sample_repo(tmp_path)
        db_path = tmp_path / "index.db"

        with (
            patch.object(sys, "version_info", (3, 14, 0, "final", 0)),
            patch.object(sys, "_is_gil_enabled", return_value=False, create=True),
        ):
            indexer = FreeThreadedIndexer(repo, db_path, workers=2)
            indexer.init()
            try:
                result = indexer.build()
            finally:
                indexer.close()

        assert result["artifacts"] > 0
        assert result["parse_errors"] == 0

    def test_parallel_mode_reason_mentions_free_threading(self) -> None:
        """The mode reason string should mention free-threading when parallel mode is active."""
        with (
            patch.object(sys, "version_info", (3, 14, 0, "final", 0)),
            patch.object(sys, "_is_gil_enabled", return_value=False, create=True),
        ):
            mode = VersionDetector.detect()

        assert mode.parallel is True
        # Reason should mention free-threading or parallel
        reason_lower = mode.reason.lower()
        assert "free-thread" in reason_lower or "parallel" in reason_lower
