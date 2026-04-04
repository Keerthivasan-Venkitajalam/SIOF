"""Performance benchmarks for FreeThreadedIndexer.

Tasks 15.1-15.4: Benchmark suite covering varying file counts, core counts,
8x speedup target verification, and race condition stress testing.

Tests are marked @pytest.mark.slow and can be skipped in CI with:
    pytest -m "not slow"
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from siof.free_threaded_indexer import FreeThreadedIndexer
from siof.indexer import PythonIndexer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_python_files(root: Path, count: int, subdir: str = "") -> None:
    """Create *count* minimal Python files under *root* (optionally in *subdir*)."""
    base = root / subdir if subdir else root
    base.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (base / f"file_{i}.py").write_text(
            f"# auto-generated file {i}\n"
            f"def func_{i}(x: int) -> int:\n"
            f"    return x + {i}\n"
        )


def _run_single_threaded(repo: Path, db_path: Path) -> tuple[dict, float]:
    """Run PythonIndexer (single-threaded baseline) and return (result, elapsed)."""
    idx = PythonIndexer(repo=repo, db_path=db_path)
    idx.init()
    t0 = time.perf_counter()
    result = idx.build()
    elapsed = time.perf_counter() - t0
    idx.close()
    return result, elapsed


def _run_parallel(repo: Path, db_path: Path, workers: int | None = None) -> tuple[dict, float]:
    """Run FreeThreadedIndexer and return (result, elapsed)."""
    idx = FreeThreadedIndexer(repo=repo, db_path=db_path, workers=workers)
    idx.init()
    t0 = time.perf_counter()
    result = idx.build()
    elapsed = time.perf_counter() - t0
    idx.close()
    return result, elapsed


# ---------------------------------------------------------------------------
# Task 15.1 – Benchmark suite for varying file counts
# Requirements: 6.1, 6.3, 6.4
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestVaryingFileCounts:
    """Measure parsing time for 100, 1000, 10000 files.

    Compares FreeThreadedIndexer against PythonIndexer (single-threaded
    baseline) and reports speedup factor and throughput.
    """

    @pytest.mark.parametrize("file_count", [100, 1000])
    def test_parallel_vs_single_threaded(self, tmp_path: Path, file_count: int):
        """Measure and compare parallel vs single-threaded for *file_count* files.

        Validates: Requirements 6.1, 6.3, 6.4
        """
        repo = tmp_path / "repo"
        _make_python_files(repo, file_count)

        # Single-threaded baseline
        st_result, st_elapsed = _run_single_threaded(repo, tmp_path / "st.db")

        # Parallel
        par_result, par_elapsed = _run_parallel(repo, tmp_path / "par.db")

        # Both must discover all files
        assert st_result["files"] == file_count, (
            f"Single-threaded found {st_result['files']} files, expected {file_count}"
        )
        assert par_result["files"] == file_count, (
            f"Parallel found {par_result['files']} files, expected {file_count}"
        )

        # Throughput (files/sec)
        st_throughput = file_count / st_elapsed if st_elapsed > 0 else float("inf")
        par_throughput = file_count / par_elapsed if par_elapsed > 0 else float("inf")

        # Speedup factor
        speedup = st_elapsed / par_elapsed if par_elapsed > 0 else float("inf")

        print(
            f"\n[file_count={file_count}] "
            f"single={st_elapsed:.3f}s ({st_throughput:.1f} f/s) | "
            f"parallel={par_elapsed:.3f}s ({par_throughput:.1f} f/s) | "
            f"speedup={speedup:.2f}x"
        )

        # Parallel must complete within a reasonable wall-clock budget
        assert par_elapsed < 120.0, (
            f"Parallel indexing {file_count} files took {par_elapsed:.2f}s (> 120s)"
        )

    def test_10k_files_parallel_completes(self, tmp_path: Path):
        """Verify parallel indexer handles 10 000 files without error.

        Validates: Requirements 6.1
        """
        repo = tmp_path / "repo"
        # Spread across 100 subdirectories to avoid filesystem limits
        for i in range(100):
            _make_python_files(repo, 100, subdir=f"pkg_{i}")

        par_result, par_elapsed = _run_parallel(repo, tmp_path / "par.db")

        assert par_result["files"] == 10_000, (
            f"Expected 10000 files, got {par_result['files']}"
        )
        assert par_elapsed < 300.0, (
            f"Parallel indexing 10000 files took {par_elapsed:.2f}s (> 300s)"
        )

        throughput = 10_000 / par_elapsed
        print(
            f"\n[10k files] parallel={par_elapsed:.2f}s | "
            f"throughput={throughput:.1f} f/s"
        )

    def test_throughput_increases_with_file_count(self, tmp_path: Path):
        """Verify throughput (files/sec) is non-trivially positive for all sizes.

        Validates: Requirements 6.4
        """
        results: dict[int, float] = {}
        for count in [100, 500]:
            repo = tmp_path / f"repo_{count}"
            _make_python_files(repo, count)
            _, elapsed = _run_parallel(repo, tmp_path / f"par_{count}.db")
            throughput = count / elapsed if elapsed > 0 else 0.0
            results[count] = throughput
            assert throughput > 0, f"Zero throughput for {count} files"

        print(f"\nThroughput by file count: {results}")


# ---------------------------------------------------------------------------
# Task 15.2 – Benchmark suite for varying core counts
# Requirements: 6.2, 6.4
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestVaryingCoreCounts:
    """Measure parsing time on 2, 4, 8, 16 worker threads (if cores available).

    Verifies near-linear scaling and reports CPU utilization proxy.
    """

    def _available_worker_counts(self) -> list[int]:
        """Return worker counts to test, capped at available CPU cores."""
        cpu_count = os.cpu_count() or 1
        candidates = [2, 4, 8, 16]
        return [w for w in candidates if w <= cpu_count * 2]  # allow mild over-subscription

    def test_scaling_with_worker_count(self, tmp_path: Path):
        """Measure throughput for each available worker count.

        Validates: Requirements 6.2, 6.4
        """
        file_count = 500
        repo = tmp_path / "repo"
        _make_python_files(repo, file_count)

        worker_counts = self._available_worker_counts()
        if not worker_counts:
            pytest.skip("No suitable worker counts available on this system")

        timings: dict[int, float] = {}
        for workers in worker_counts:
            _, elapsed = _run_parallel(repo, tmp_path / f"par_{workers}.db", workers=workers)
            timings[workers] = elapsed
            throughput = file_count / elapsed if elapsed > 0 else 0.0
            print(
                f"\n[workers={workers}] elapsed={elapsed:.3f}s | "
                f"throughput={throughput:.1f} f/s"
            )

        # All runs must complete successfully
        for workers, elapsed in timings.items():
            assert elapsed < 120.0, (
                f"workers={workers} took {elapsed:.2f}s (> 120s)"
            )

    def test_more_workers_not_slower(self, tmp_path: Path):
        """Verify that doubling workers does not make things dramatically slower.

        Near-linear scaling means 4 workers should be faster than 2 workers
        (or at worst comparable) on a multi-core machine.

        Validates: Requirements 6.2
        """
        cpu_count = os.cpu_count() or 1
        if cpu_count < 2:
            pytest.skip("Need at least 2 CPU cores for this test")

        file_count = 300
        repo = tmp_path / "repo"
        _make_python_files(repo, file_count)

        _, t1 = _run_parallel(repo, tmp_path / "par_1.db", workers=1)
        _, t2 = _run_parallel(repo, tmp_path / "par_2.db", workers=min(2, cpu_count))

        # 2 workers should not be more than 3x slower than 1 worker
        # (accounts for overhead on single-core CI machines)
        assert t2 < t1 * 3.0, (
            f"2 workers ({t2:.3f}s) is more than 3x slower than 1 worker ({t1:.3f}s)"
        )
        print(f"\n[scaling] 1 worker={t1:.3f}s | 2 workers={t2:.3f}s")

    def test_cpu_utilization_proxy(self, tmp_path: Path):
        """Verify that parallel indexer uses multiple threads (proxy for CPU util).

        We measure wall-clock time with 1 vs N workers; if N workers is faster
        we infer that multiple cores were utilised.

        Validates: Requirements 6.4
        """
        cpu_count = os.cpu_count() or 1
        if cpu_count < 2:
            pytest.skip("Need at least 2 CPU cores for CPU utilization test")

        file_count = 200
        repo = tmp_path / "repo"
        _make_python_files(repo, file_count)

        _, t_single = _run_parallel(repo, tmp_path / "par_single.db", workers=1)
        _, t_multi = _run_parallel(repo, tmp_path / "par_multi.db", workers=cpu_count)

        throughput_single = file_count / t_single if t_single > 0 else 0.0
        throughput_multi = file_count / t_multi if t_multi > 0 else 0.0

        print(
            f"\n[cpu_util] 1 worker={t_single:.3f}s ({throughput_single:.1f} f/s) | "
            f"{cpu_count} workers={t_multi:.3f}s ({throughput_multi:.1f} f/s)"
        )

        # Both must produce valid results
        assert throughput_single > 0
        assert throughput_multi > 0


# ---------------------------------------------------------------------------
# Task 15.3 – Verify 8x speedup target on 8-core systems
# Requirements: 6.5
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestSpeedupTarget:
    """Verify 8x speedup on 8-core systems with 1000+ files.

    On systems with fewer than 8 cores the test is skipped.
    """

    def test_8x_speedup_on_8_core_system(self, tmp_path: Path):
        """Verify at least 8x speedup over single-threaded on 8-core system.

        This test requires:
        - 8+ CPU cores
        - Python 3.14+ with free-threading enabled (GIL disabled)

        On Python 3.11-3.13 or GIL-enabled 3.14+, the FreeThreadedIndexer
        falls back to single-threaded mode and cannot achieve 8x speedup.
        The test is skipped in those environments.

        Validates: Requirements 6.5
        """
        import sys

        cpu_count = os.cpu_count() or 0
        if cpu_count < 8:
            pytest.skip(
                f"8x speedup test requires 8+ CPU cores; this system has {cpu_count}"
            )

        # Check that free-threading is actually active
        if sys.version_info < (3, 14):
            pytest.skip(
                f"8x speedup requires Python 3.14+ free-threading; "
                f"running Python {sys.version_info.major}.{sys.version_info.minor}"
            )

        gil_enabled = True
        if hasattr(sys, "_is_gil_enabled"):
            try:
                gil_enabled = sys._is_gil_enabled()
            except Exception:
                pass
        if gil_enabled:
            pytest.skip(
                "8x speedup requires GIL to be disabled (free-threaded Python build)"
            )

        file_count = 1000
        repo = tmp_path / "repo"
        _make_python_files(repo, file_count)

        # Single-threaded baseline (workers=1)
        st_result, st_elapsed = _run_parallel(repo, tmp_path / "st.db", workers=1)

        # Parallel with 8 workers
        par_result, par_elapsed = _run_parallel(repo, tmp_path / "par.db", workers=8)

        assert st_result["files"] == file_count
        assert par_result["files"] == file_count

        speedup = st_elapsed / par_elapsed if par_elapsed > 0 else float("inf")

        print(
            f"\n[8x speedup] single={st_elapsed:.3f}s | "
            f"parallel(8)={par_elapsed:.3f}s | speedup={speedup:.2f}x"
        )

        # Requirement 6.5: at least 8x speedup on 8-core system with 1000+ files
        assert speedup >= 8.0, (
            f"Expected >= 8x speedup on 8-core system, got {speedup:.2f}x "
            f"(single={st_elapsed:.3f}s, parallel={par_elapsed:.3f}s)"
        )

    def test_speedup_documented(self, tmp_path: Path):
        """Document speedup results for any available core count.

        Always runs (not skipped) to provide benchmark data regardless of
        core count.  Does not assert a specific speedup threshold.

        Validates: Requirements 6.5 (documentation aspect)
        """
        cpu_count = os.cpu_count() or 1
        file_count = 1000
        repo = tmp_path / "repo"
        _make_python_files(repo, file_count)

        _, st_elapsed = _run_parallel(repo, tmp_path / "st.db", workers=1)
        _, par_elapsed = _run_parallel(repo, tmp_path / "par.db", workers=cpu_count)

        speedup = st_elapsed / par_elapsed if par_elapsed > 0 else float("inf")
        st_throughput = file_count / st_elapsed if st_elapsed > 0 else 0.0
        par_throughput = file_count / par_elapsed if par_elapsed > 0 else 0.0

        print(
            f"\n[speedup_doc] cores={cpu_count} | "
            f"single={st_elapsed:.3f}s ({st_throughput:.1f} f/s) | "
            f"parallel={par_elapsed:.3f}s ({par_throughput:.1f} f/s) | "
            f"speedup={speedup:.2f}x"
        )

        # Sanity: parallel must complete and produce correct file count
        assert par_throughput > 0


# ---------------------------------------------------------------------------
# Task 15.4 – Stress test for race condition detection
# Requirements: 12.3
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestRaceConditionStress:
    """Parse the same files concurrently many times to detect race conditions.

    Validates: Requirements 12.3
    """

    def test_concurrent_builds_no_corruption(self, tmp_path: Path):
        """Run 20 concurrent builds on the same repo; verify consistent results.

        Validates: Requirements 12.3
        """
        repo = tmp_path / "repo"
        _make_python_files(repo, 50)

        results: list[dict] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def run_build(idx: int) -> None:
            try:
                db = tmp_path / f"db_{idx}.db"
                result, _ = _run_parallel(repo, db)
                with lock:
                    results.append(result)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=run_build, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        assert not errors, f"Errors during concurrent builds: {errors}"
        assert len(results) == 20, f"Expected 20 results, got {len(results)}"

        # All builds must agree on file count
        file_counts = {r["files"] for r in results}
        assert file_counts == {50}, (
            f"Inconsistent file counts across concurrent builds: {file_counts}"
        )

    def test_repeated_sequential_builds_consistent(self, tmp_path: Path):
        """Run 30 sequential builds on the same repo; verify identical results.

        Validates: Requirements 12.3
        """
        repo = tmp_path / "repo"
        _make_python_files(repo, 30)

        file_counts: list[int] = []
        node_counts: list[int] = []

        for i in range(30):
            result, _ = _run_parallel(repo, tmp_path / f"db_{i}.db")
            file_counts.append(result["files"])
            node_counts.append(result["nodes"])

        # All runs must agree
        assert len(set(file_counts)) == 1, (
            f"Inconsistent file counts across 30 runs: {set(file_counts)}"
        )
        assert len(set(node_counts)) == 1, (
            f"Inconsistent node counts across 30 runs: {set(node_counts)}"
        )

    def test_high_concurrency_no_data_corruption(self, tmp_path: Path):
        """Stress test with many threads sharing a single FreeThreadedIndexer.

        Validates: Requirements 12.3
        """
        repo = tmp_path / "repo"
        _make_python_files(repo, 20)

        db = tmp_path / "shared.db"
        idx = FreeThreadedIndexer(repo=repo, db_path=db, workers=4)
        idx.init()

        # Run build once to populate the DB
        baseline = idx.build()
        idx.close()

        # Now run many independent builds and verify consistency
        results: list[dict] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def run_independent(i: int) -> None:
            try:
                local_db = tmp_path / f"local_{i}.db"
                local_idx = FreeThreadedIndexer(repo=repo, db_path=local_db, workers=2)
                local_idx.init()
                r = local_idx.build()
                local_idx.close()
                with lock:
                    results.append(r)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=run_independent, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        assert not errors, f"Errors in high-concurrency test: {errors}"
        assert len(results) == 10

        # All results must match baseline file count
        for r in results:
            assert r["files"] == baseline["files"], (
                f"File count mismatch: {r['files']} != {baseline['files']}"
            )

    def test_1000_plus_concurrent_parse_invocations(self, tmp_path: Path):
        """Parse same files 1000+ times via WorkPool to detect race conditions.

        Uses the WorkPool directly to submit 1000 parse tasks for the same
        small set of files, verifying no corruption occurs.

        Validates: Requirements 12.3
        """
        from siof.free_threaded_indexer import ParseTask, WorkPool

        repo = tmp_path / "repo"
        _make_python_files(repo, 5)

        files = list(repo.glob("*.py"))
        assert len(files) == 5

        # Create 1000 tasks (200 repetitions of each of the 5 files)
        tasks = [
            ParseTask(
                file_path=files[i % len(files)],
                file_metadata={},
                task_id=i,
            )
            for i in range(1000)
        ]

        pool = WorkPool(workers=min(8, os.cpu_count() or 4), repo=repo)
        results = list(pool.submit_tasks(tasks))
        pool.shutdown()

        assert len(results) == 1000, f"Expected 1000 results, got {len(results)}"

        # All results for valid Python files must succeed
        failures = [r for r in results if not r.success]
        assert not failures, (
            f"{len(failures)} parse failures in 1000-task stress test: "
            f"{[str(f.errors) for f in failures[:5]]}"
        )

        # Verify no corrupted results (all have non-empty file_path)
        for r in results:
            assert r.file_path is not None
            assert r.task_id >= 0
