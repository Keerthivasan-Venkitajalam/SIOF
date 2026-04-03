"""Performance benchmarks for file discovery and dependency seed extraction."""

import time
from pathlib import Path

from siof.indexer import DependencySeedExtractor, FileDiscovery, PythonIndexer


class TestFileDiscoveryBenchmark:
    """Benchmarks for FileDiscovery performance."""

    def test_discover_1k_files_timing(self, tmp_path: Path):
        """Test that discovering 1,000 files completes in reasonable time."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create 1,000 Python files
        for i in range(1000):
            (repo / f"file_{i}.py").write_text(f"x = {i}\n")

        discovery = FileDiscovery(repo)

        start = time.time()
        result = discovery.discover()
        elapsed = time.time() - start

        assert len(result) == 1000
        # Should complete in < 5 seconds
        assert elapsed < 5.0, f"Discovery took {elapsed:.2f}s, expected < 5s"

    def test_discover_10k_files_timing(self, tmp_path: Path):
        """Test that discovering 10,000 files completes in reasonable time."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create 10,000 Python files in nested structure
        for i in range(100):
            subdir = repo / f"dir_{i}"
            subdir.mkdir()
            for j in range(100):
                (subdir / f"file_{j}.py").write_text(f"x = {i * 100 + j}\n")

        discovery = FileDiscovery(repo)

        start = time.time()
        result = discovery.discover()
        elapsed = time.time() - start

        assert len(result) == 10000
        # Should complete in < 30 seconds
        assert elapsed < 30.0, f"Discovery took {elapsed:.2f}s, expected < 30s"


class TestDependencySeedExtractorBenchmark:
    """Benchmarks for DependencySeedExtractor performance."""

    def test_extract_1k_files_timing(self, tmp_path: Path):
        """Test that extracting seeds from 1,000 files completes in reasonable time."""
        repo = tmp_path / "repo"
        repo.mkdir()

        files = []
        for i in range(1000):
            file_path = repo / f"file_{i}.py"
            file_path.write_text(f"import os\nimport sys\n\ndef func_{i}(): pass\n")
            files.append(file_path)

        extractor = DependencySeedExtractor(repo)

        start = time.time()
        result = extractor.extract_batch(files)
        elapsed = time.time() - start

        assert len(result) == 1000
        # Should complete in < 10 seconds
        assert elapsed < 10.0, f"Extraction took {elapsed:.2f}s, expected < 10s"


class TestPythonIndexerBenchmark:
    """Benchmarks for PythonIndexer performance."""

    def test_index_1k_files_timing(self, tmp_path: Path):
        """Test that indexing 1,000 files completes in reasonable time."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create 1,000 Python files
        for i in range(1000):
            (repo / f"file_{i}.py").write_text(
                f"import os\n\ndef func_{i}(x):\n    return x + {i}\n"
            )

        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()

        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        idx.close()

        assert result["files"] == 1000
        # Should complete in < 30 seconds
        assert elapsed < 30.0, f"Index build took {elapsed:.2f}s, expected < 30s"

    def test_index_build_with_nested_structure(self, tmp_path: Path):
        """Test indexing with nested directory structure."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Create nested structure with 500 files
        for i in range(10):
            subdir = repo / f"package_{i}"
            subdir.mkdir()
            (subdir / "__init__.py").write_text("")
            for j in range(50):
                (subdir / f"module_{j}.py").write_text(f"def func_{i}_{j}(): pass\n")

        db = tmp_path / "siof.db"
        idx = PythonIndexer(repo=repo, db_path=db)
        idx.init()

        start = time.time()
        result = idx.build()
        elapsed = time.time() - start
        idx.close()

        assert result["files"] == 510  # 10 __init__.py + 500 modules
        # Should complete in < 30 seconds
        assert elapsed < 30.0, f"Index build took {elapsed:.2f}s, expected < 30s"

    def test_file_discovery_scales_linearly(self, tmp_path: Path):
        """Test that file discovery scales approximately linearly."""
        repo = tmp_path / "repo"
        repo.mkdir()

        # Test with 100, 500, 1000 files
        timings = {}
        for count in [100, 500, 1000]:
            # Clear and recreate repo
            import shutil

            if repo.exists():
                shutil.rmtree(repo)
            repo.mkdir()

            # Create files
            for i in range(count):
                (repo / f"file_{i}.py").write_text(f"x = {i}\n")

            discovery = FileDiscovery(repo)
            start = time.time()
            result = discovery.discover()
            elapsed = time.time() - start

            assert len(result) == count
            timings[count] = elapsed

        # Check that timing scales roughly linearly
        # 500 files should take ~5x time of 100 files (with some tolerance)
        ratio_500_100 = timings[500] / timings[100]
        assert 3.0 < ratio_500_100 < 7.0, f"Scaling ratio {ratio_500_100} not linear"

        # 1000 files should take ~10x time of 100 files (with some tolerance)
        ratio_1000_100 = timings[1000] / timings[100]
        assert 7.0 < ratio_1000_100 < 15.0, f"Scaling ratio {ratio_1000_100} not linear"
