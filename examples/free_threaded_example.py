"""Example: using FreeThreadedIndexer for parallel Python repository indexing.

This script demonstrates the main configuration options and usage patterns
for FreeThreadedIndexer. It works on Python 3.11+ — parallel mode activates
automatically when running on Python 3.14+ with free-threading enabled.

Usage:
    python examples/free_threaded_example.py [--repo PATH] [--db PATH] [--verbose]

Requirements: 10.5, 11.1, 11.2, 11.3
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import textwrap
from pathlib import Path


def _create_demo_repo(base: Path) -> Path:
    """Create a small demo repository so the example runs without a real repo."""
    repo = base / "demo_repo"
    repo.mkdir()

    # A simple package with a few modules
    pkg = repo / "mypackage"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .core import process\n")
    (pkg / "core.py").write_text(
        textwrap.dedent("""\
        def process(data: list) -> list:
            return [transform(item) for item in data]

        def transform(item):
            return item * 2
        """)
    )
    (pkg / "utils.py").write_text(
        textwrap.dedent("""\
        import os

        def read_file(path: str) -> str:
            with open(path) as f:
                return f.read()

        def write_file(path: str, content: str) -> None:
            with open(path, "w") as f:
                f.write(content)
        """)
    )

    # A top-level script
    (repo / "main.py").write_text(
        textwrap.dedent("""\
        from mypackage import process

        def main():
            result = process([1, 2, 3])
            print(result)

        if __name__ == "__main__":
            main()
        """)
    )

    return repo


# ---------------------------------------------------------------------------
# Example 1: Minimal usage — drop-in replacement for PythonIndexer
# ---------------------------------------------------------------------------

def example_minimal(repo: Path, db_path: Path) -> None:
    """Minimal usage: identical API to PythonIndexer."""
    print("\n--- Example 1: Minimal usage ---")

    from siof.free_threaded_indexer import FreeThreadedIndexer

    indexer = FreeThreadedIndexer(repo=repo, db_path=db_path)
    indexer.init()
    result = indexer.build()
    indexer.close()

    print(f"  Artifacts : {result['artifacts']}")
    print(f"  Nodes     : {result['nodes']}")
    print(f"  Edges     : {result['edges']}")
    print(f"  Errors    : {result['parse_errors']}")
    print(f"  Duration  : {result['duration_seconds']:.3f}s")


# ---------------------------------------------------------------------------
# Example 2: Explicit worker count (Requirement 11.1)
# ---------------------------------------------------------------------------

def example_explicit_workers(repo: Path, db_path: Path) -> None:
    """Configure the number of parallel worker threads."""
    print("\n--- Example 2: Explicit worker count ---")

    from siof.free_threaded_indexer import FreeThreadedIndexer

    cpu_count = os.cpu_count() or 4

    for workers in [1, min(2, cpu_count), cpu_count]:
        indexer = FreeThreadedIndexer(repo=repo, db_path=db_path, workers=workers)
        indexer.init()
        result = indexer.build()
        indexer.close()
        print(
            f"  workers={workers:2d}  "
            f"duration={result['duration_seconds']:.3f}s  "
            f"nodes={result['nodes']}"
        )

    print(
        "\n  Tip: workers=1 produces results identical to single-threaded mode."
        "\n  Tip: workers=None (default) uses os.cpu_count()."
    )


# ---------------------------------------------------------------------------
# Example 3: Batch size tuning (Requirement 11.2)
# ---------------------------------------------------------------------------

def example_batch_size(repo: Path, db_path: Path) -> None:
    """Tune batch_size for different repository characteristics."""
    print("\n--- Example 3: Batch size tuning ---")

    from siof.free_threaded_indexer import FreeThreadedIndexer

    for batch_size in [1, 5, 10]:
        indexer = FreeThreadedIndexer(
            repo=repo,
            db_path=db_path,
            batch_size=batch_size,
        )
        indexer.init()
        result = indexer.build()
        indexer.close()
        print(
            f"  batch_size={batch_size:2d}  "
            f"duration={result['duration_seconds']:.3f}s"
        )

    print(
        "\n  Tip: smaller batch_size improves load balancing for varied file sizes."
        "\n  Tip: larger batch_size reduces scheduling overhead for many small files."
    )


# ---------------------------------------------------------------------------
# Example 4: Progress interval (Requirement 11.3)
# ---------------------------------------------------------------------------

def example_progress_interval(repo: Path, db_path: Path) -> None:
    """Control how often progress is logged."""
    print("\n--- Example 4: Progress reporting interval ---")

    from siof.free_threaded_indexer import FreeThreadedIndexer

    # Short interval so progress lines appear even for small repos
    indexer = FreeThreadedIndexer(
        repo=repo,
        db_path=db_path,
        progress_interval=1.0,  # log every 1 second (default: 5.0)
    )
    indexer.init()
    result = indexer.build()
    indexer.close()

    print(f"  Build complete. Nodes: {result['nodes']}, Edges: {result['edges']}")
    print(
        "\n  Tip: set progress_interval=0.5 for very fast feedback on large repos."
        "\n  Tip: set progress_interval=60.0 to reduce log noise in CI pipelines."
    )


# ---------------------------------------------------------------------------
# Example 5: Verbose mode — per-file logging (Requirement 10.5)
# ---------------------------------------------------------------------------

def example_verbose(repo: Path, db_path: Path) -> None:
    """Enable DEBUG logging to see per-file parse events."""
    print("\n--- Example 5: Verbose mode (DEBUG logging) ---")

    # Enable DEBUG for the free_threaded_indexer logger only
    fti_logger = logging.getLogger("siof.free_threaded_indexer")
    original_level = fti_logger.level
    fti_logger.setLevel(logging.DEBUG)

    # Add a simple handler if none present
    if not fti_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
        fti_logger.addHandler(handler)

    from siof.free_threaded_indexer import FreeThreadedIndexer

    indexer = FreeThreadedIndexer(repo=repo, db_path=db_path)
    indexer.init()
    indexer.build()
    indexer.close()

    # Restore original log level
    fti_logger.setLevel(original_level)

    print("\n  Tip: in production use logging.basicConfig(level=logging.DEBUG)")
    print("  Tip: filter to 'siof.free_threaded_indexer' to reduce noise.")


# ---------------------------------------------------------------------------
# Example 6: Incremental update
# ---------------------------------------------------------------------------

def example_incremental_update(repo: Path, db_path: Path) -> None:
    """Demonstrate incremental update after initial build."""
    print("\n--- Example 6: Incremental update ---")

    from siof.free_threaded_indexer import FreeThreadedIndexer

    # Initial build
    indexer = FreeThreadedIndexer(repo=repo, db_path=db_path)
    indexer.init()
    indexer.build()

    # Simulate a file change
    changed_file = repo / "main.py"
    changed_file.write_text(
        "from mypackage import process\n\ndef main():\n    print(process([10, 20]))\n"
    )

    # Incremental update — only re-parses the changed file
    result = indexer.update(changed_files=[changed_file])
    indexer.close()

    print(f"  Updated artifacts: {result['artifacts']}")
    print(f"  Duration         : {result['duration_seconds']:.3f}s")
    print("\n  Tip: pass changed_files=None to let the indexer detect changes.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FreeThreadedIndexer usage examples")
    parser.add_argument("--repo", type=Path, default=None, help="Repository path (default: auto-generated demo)")
    parser.add_argument("--db", type=Path, default=None, help="Database path (default: temp file)")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging globally")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        repo = args.repo or _create_demo_repo(tmp)
        db_path = args.db or (tmp / "siof.db")

        print(f"Repository : {repo}")
        print(f"Database   : {db_path}")

        # Detect and report parsing mode
        from siof.free_threaded_indexer import VersionDetector
        mode = VersionDetector.detect()
        print(f"Mode       : {'parallel' if mode.parallel else 'single-threaded'}")
        print(f"Reason     : {mode.reason}")

        example_minimal(repo, db_path)
        example_explicit_workers(repo, db_path)
        example_batch_size(repo, db_path)
        example_progress_interval(repo, db_path)
        if args.verbose:
            example_verbose(repo, db_path)
        example_incremental_update(repo, db_path)

    print("\nAll examples completed successfully.")


if __name__ == "__main__":
    main()
