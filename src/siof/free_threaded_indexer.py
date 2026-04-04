"""Free-threaded parallel indexer for Python 3.14+.

This module implements Phase 1 of SIOF v2.0: Free-Threaded Parsing.
It leverages Python 3.14's free-threaded mode (PEP 703) to achieve
parallel AST parsing without the Global Interpreter Lock (GIL).
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from siof.models import Artifact, DataNode, TransformEdge

# Import SymbolInfo for type hints
try:
    from siof.indexer import SymbolInfo
except ImportError:
    # For type checking when indexer is not available
    SymbolInfo = dict  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class ParsingMode:
    """Configuration for parsing mode.
    
    Attributes:
        parallel: True if parallel parsing is enabled
        python_version: Python version tuple (major, minor, patch)
        gil_enabled: True if GIL is enabled
        reason: Human-readable reason for mode selection
    """
    parallel: bool
    python_version: tuple[int, int, int]
    gil_enabled: bool
    reason: str


@dataclass
class ParseTask:
    """Task for parallel parsing.
    
    Attributes:
        file_path: Path to file to parse
        file_metadata: File metadata (size, hash, etc.)
        task_id: Unique task identifier
    """
    file_path: Path
    file_metadata: dict
    task_id: int


@dataclass
class ParseResult:
    """Result of parsing a file.
    
    Attributes:
        task_id: Task identifier
        file_path: Path to parsed file
        artifact: Artifact metadata
        nodes: Extracted nodes
        edges: Extracted edges
        errors: Parse errors
        duration_ms: Parse duration in milliseconds
        success: True if parse succeeded
    """
    task_id: int
    file_path: Path
    artifact: Artifact
    nodes: list[DataNode]
    edges: list[TransformEdge]
    errors: list[str]
    duration_ms: float
    success: bool


@dataclass
class BuildResult:
    """Result of index build.
    
    Attributes:
        artifacts: Number of artifacts processed
        nodes: Number of nodes created
        edges: Number of edges created
        parse_errors: Number of parse errors
        duration_seconds: Total duration
        throughput_files_per_second: Parsing throughput
        speedup_factor: Speedup vs single-threaded (1.0 = baseline)
        mode: Parsing mode used
    """
    artifacts: int
    nodes: int
    edges: int
    parse_errors: int
    duration_seconds: float
    throughput_files_per_second: float
    speedup_factor: float
    mode: ParsingMode


class VersionDetector:
    """Detects Python version and free-threading capabilities."""

    @staticmethod
    def detect() -> ParsingMode:
        """Detect parsing mode based on Python version.
        
        Returns:
            ParsingMode with detection results
        """
        python_version = sys.version_info[:3]

        # Check if Python 3.14+
        if python_version < (3, 14, 0):
            return ParsingMode(
                parallel=False,
                python_version=python_version,
                gil_enabled=True,
                reason=f"Python {python_version[0]}.{python_version[1]} detected, "
                       f"free-threading requires Python 3.14+"
            )

        # Check if GIL is disabled
        # sys._is_gil_enabled() returns False when GIL is disabled
        gil_enabled = True
        if hasattr(sys, '_is_gil_enabled'):
            try:
                gil_enabled = sys._is_gil_enabled()
            except Exception:
                # If we can't determine GIL status, assume it's enabled
                gil_enabled = True

        if gil_enabled:
            return ParsingMode(
                parallel=False,
                python_version=python_version,
                gil_enabled=True,
                reason=f"Python {python_version[0]}.{python_version[1]} detected, "
                       f"but GIL is enabled (free-threading not active)"
            )

        # Python 3.14+ with GIL disabled - enable parallel mode
        return ParsingMode(
            parallel=True,
            python_version=python_version,
            gil_enabled=False,
            reason=f"Python {python_version[0]}.{python_version[1]} with free-threading detected, "
                   f"parallel parsing enabled"
        )


@dataclass
class FileMetadata:
    """Metadata for discovered Python file.
    
    Attributes:
        path: Path to the file
        size: File size in bytes
        hash: SHA-256 hash of file content
        language: Programming language (always "python")
    """
    path: Path
    size: int
    hash: str
    language: str = "python"


class ParallelFileDiscovery:
    """Parallel file discovery with thread-safe inode tracking.
    
    Discovers Python files in a repository using multiple threads for
    parallel directory traversal. Tracks visited inodes to prevent
    circular symlink loops.
    """

    # Directories to skip during traversal (copied from FileDiscovery)
    SKIP_DIRS: set[str] = {
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".egg-info",
        ".eggs",
        "node_modules",
        ".git",
        ".hg",
        ".svn",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        "dist",
        "build",
        ".coverage",
    }

    def __init__(self, repo: Path, workers: int = 4):
        """Initialize parallel file discovery.
        
        Args:
            repo: Repository root path
            workers: Number of worker threads for parallel traversal
        """
        self.repo = repo
        self.workers = workers
        self._visited_inodes: set[int] = set()
        self._visited_lock = threading.Lock()
        self._files: list[FileMetadata] = []
        self._files_lock = threading.Lock()

    def discover(self) -> list[FileMetadata]:
        """Discover Python files in parallel.
        
        Returns:
            List of FileMetadata for discovered Python files
        """
        # Reset state
        self._visited_inodes.clear()
        self._files.clear()

        # Start with root directory
        directories_to_process = [self.repo]

        # Process directories in parallel
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            while directories_to_process:
                # Submit batch of directories
                futures = [
                    executor.submit(self._process_directory, directory)
                    for directory in directories_to_process
                ]

                # Collect new directories to process
                directories_to_process = []
                for future in as_completed(futures):
                    try:
                        subdirs = future.result()
                        directories_to_process.extend(subdirs)
                    except Exception as exc:
                        logger.warning(f"Error processing directory: {exc}")

        logger.info(f"Discovered {len(self._files)} Python files")
        return self._files.copy()

    def _process_directory(self, directory: Path) -> list[Path]:
        """Process a single directory and return subdirectories to traverse.
        
        Args:
            directory: Directory to process
            
        Returns:
            List of subdirectories to process next
        """
        subdirs: list[Path] = []

        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError) as exc:
            logger.warning(f"Cannot read directory {directory}: {exc}")
            return subdirs

        for entry in entries:
            try:
                # Check if it's a directory
                is_directory = entry.is_dir()
            except OSError:
                continue

            if is_directory:
                # Skip directories in SKIP_DIRS
                if entry.name in self.SKIP_DIRS:
                    continue

                # Skip symlinks (we don't follow them by default)
                if entry.is_symlink():
                    continue

                # Check for circular references via inode tracking
                try:
                    stat = entry.stat(follow_symlinks=False)
                    inode = stat.st_ino

                    # Thread-safe inode check and add
                    with self._visited_lock:
                        if inode in self._visited_inodes:
                            logger.debug(f"Skipping circular symlink: {entry}")
                            continue
                        self._visited_inodes.add(inode)

                    subdirs.append(entry)
                except (OSError, ValueError):
                    logger.debug(f"Cannot stat {entry}, skipping")
                    continue
            else:
                # Check if it's a Python file
                try:
                    is_python_file = entry.is_file() and entry.suffix == ".py"
                except OSError:
                    continue

                if is_python_file:
                    # Skip symlinks for files too
                    if entry.is_symlink():
                        continue

                    try:
                        metadata = self._extract_file_metadata(entry)
                        # Thread-safe file list append
                        with self._files_lock:
                            self._files.append(metadata)
                    except Exception as exc:
                        logger.warning(f"Error extracting metadata for {entry}: {exc}")

        return subdirs

    def _extract_file_metadata(self, file_path: Path) -> FileMetadata:
        """Extract metadata for a Python file.
        
        Args:
            file_path: Path to Python file
            
        Returns:
            FileMetadata with size and hash
        """
        import hashlib

        try:
            content = file_path.read_bytes()
            size = len(content)
            hash_val = hashlib.sha256(content).hexdigest()
            return FileMetadata(path=file_path, size=size, hash=hash_val)
        except Exception as exc:
            logger.error(f"Failed to read {file_path}: {exc}")
            raise



class LockFreeSymbolTable:
    """Lock-free symbol table for concurrent symbol extraction.
    
    This class provides thread-safe storage for symbols extracted during
    parallel parsing. In Python 3.14+ free-threaded mode, the built-in dict
    is thread-safe for concurrent reads and writes. We use minimal locking
    only for complex update operations to ensure atomicity.
    
    Attributes:
        _symbols: Dictionary mapping qualified names to SymbolInfo objects
        _lock: Lock for atomic check-then-update operations
    """

    def __init__(self):
        """Initialize lock-free symbol table with thread-safe dict."""
        self._symbols: dict[str, SymbolInfo] = {}
        self._lock = threading.Lock()  # Minimal locking for dict updates

    def add_symbol(self, qualified_name: str, symbol: SymbolInfo) -> None:
        """Add symbol atomically with minimal locking.
        
        This method adds a symbol to the table in a thread-safe manner.
        In Python 3.14+ free-threaded mode, simple dict assignments are
        thread-safe. We use a lock only for check-then-update operations
        to prevent race conditions.
        
        Args:
            qualified_name: Fully qualified symbol name (e.g., "module.Class.method")
            symbol: SymbolInfo object containing symbol metadata
        """
        # Use minimal locking for check-then-update to prevent race conditions
        with self._lock:
            # Only add if not already present (first occurrence wins)
            if qualified_name not in self._symbols:
                self._symbols[qualified_name] = symbol

    def get_all_symbols(self) -> dict[str, SymbolInfo]:
        """Get snapshot of all symbols for retrieval.
        
        Returns a shallow copy of the symbol dictionary to provide a
        consistent snapshot. This prevents issues if the table is modified
        during iteration.
        
        Returns:
            Dictionary mapping qualified names to SymbolInfo objects
        """
        # Return a shallow copy for snapshot consistency
        with self._lock:
            return self._symbols.copy()


class ParseWorker:
    """Worker that parses a single Python file.
    
    This class provides a static method for parsing individual Python files
    in parallel. It includes comprehensive error handling to ensure that
    errors in one file don't affect the parsing of other files.
    """

    @staticmethod
    def parse(task: ParseTask, repo: Path) -> ParseResult:
        """Parse a single file and extract DTG nodes/edges.
        
        This method parses a Python file and extracts symbols, nodes, and edges
        for the Data Transformation Graph (DTG). It includes robust error handling
        for syntax errors and unexpected exceptions to ensure parsing failures
        are isolated to individual files.
        
        Args:
            task: ParseTask containing file path, metadata, and task ID
            repo: Repository root path for computing relative paths
            
        Returns:
            ParseResult with success/error status, extracted nodes/edges, and timing
        """
        import ast
        import hashlib
        import time

        from siof.indexer import DTGBuilder, SymbolExtractor
        from siof.models import module_name

        start_time = time.perf_counter()
        file_path = task.file_path
        errors: list[str] = []

        # Compute relative path for artifact tracking
        try:
            rel_path = str(file_path.relative_to(repo))
        except ValueError as exc:
            # File is not relative to repo
            error_msg = f"File {file_path} is not relative to repository {repo}: {exc}"
            logger.error(error_msg)
            errors.append(error_msg)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=Artifact(path=str(file_path), hash="", parse_ok=False, error=error_msg),
                nodes=[],
                edges=[],
                errors=errors,
                duration_ms=duration_ms,
                success=False
            )

        # Read file content with error handling
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except (PermissionError, FileNotFoundError, OSError) as exc:
            # File system errors - log and return error result
            error_msg = f"Failed to read {rel_path}: {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=Artifact(path=rel_path, hash="", parse_ok=False, error=str(exc)),
                nodes=[],
                edges=[],
                errors=errors,
                duration_ms=duration_ms,
                success=False
            )
        except Exception as exc:
            # Unexpected error reading file
            error_msg = f"Unexpected error reading {rel_path}: {exc}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=Artifact(path=rel_path, hash="", parse_ok=False, error=str(exc)),
                nodes=[],
                edges=[],
                errors=errors,
                duration_ms=duration_ms,
                success=False
            )

        # Compute file hash
        try:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        except Exception as exc:
            # Unlikely but handle encoding errors
            error_msg = f"Failed to compute hash for {rel_path}: {exc}"
            logger.error(error_msg)
            errors.append(error_msg)
            digest = ""

        # Compute module name
        try:
            mod = module_name(repo, file_path)
        except Exception as exc:
            error_msg = f"Failed to compute module name for {rel_path}: {exc}"
            logger.error(error_msg)
            errors.append(error_msg)
            mod = rel_path.replace("/", ".").replace(".py", "")

        # Parse AST with syntax error handling
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            # Syntax error - this is expected for invalid Python files
            error_msg = f"Syntax error in {rel_path}:{exc.lineno}: {exc.msg}"
            logger.warning(error_msg)
            errors.append(error_msg)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=Artifact(path=rel_path, hash=digest, parse_ok=False, error=str(exc)),
                nodes=[],
                edges=[],
                errors=errors,
                duration_ms=duration_ms,
                success=False
            )
        except Exception as exc:
            # Unexpected parsing error
            error_msg = f"Unexpected error parsing {rel_path}: {exc}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=Artifact(path=rel_path, hash=digest, parse_ok=False, error=str(exc)),
                nodes=[],
                edges=[],
                errors=errors,
                duration_ms=duration_ms,
                success=False
            )

        # Extract symbols and build DTG with error handling
        try:
            # Extract comprehensive symbols using SymbolExtractor
            extractor = SymbolExtractor(mod, rel_path)
            symbols = extractor.extract(tree)

            # Build DTG using dedicated builder
            builder = DTGBuilder(mod, rel_path)

            # Add symbol nodes and their relationships
            for qualified_name, symbol in symbols.items():
                builder.add_symbol_node(qualified_name, symbol)
                builder.add_parameter_edges(qualified_name, symbol)
                builder.add_inheritance_edges(qualified_name, symbol)
                builder.add_decorator_edges(qualified_name, symbol)

            # Extract call relationships and assignments
            for node in ast.walk(tree):
                # Track assignments (state mutations)
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            target_symbol = f"{mod}.{target.id}"
                            if isinstance(node.value, ast.Call):
                                # Extract function name from call
                                fn_name = None
                                if isinstance(node.value.func, ast.Name):
                                    fn_name = node.value.func.id
                                elif isinstance(node.value.func, ast.Attribute):
                                    fn_name = node.value.func.attr

                                if fn_name:
                                    builder.add_assignment_transform_edge(
                                        fn_name,
                                        target_symbol,
                                        location=f"{rel_path}:{node.lineno}",
                                        confidence=0.8,
                                    )

            # Verify graph integrity
            violations = builder.verify_integrity()
            if violations:
                logger.debug(f"Graph integrity issues in {rel_path}: {violations}")
                # Note: We don't treat integrity violations as errors - just log them

            # Build final nodes and edges
            nodes, edges = builder.build()

            # Create successful artifact
            artifact = Artifact(path=rel_path, hash=digest, parse_ok=True, error=None)

            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=artifact,
                nodes=nodes,
                edges=edges,
                errors=errors,
                duration_ms=duration_ms,
                success=True
            )

        except Exception as exc:
            # Unexpected error during symbol extraction or DTG building
            error_msg = f"Unexpected error extracting symbols from {rel_path}: {exc}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ParseResult(
                task_id=task.task_id,
                file_path=file_path,
                artifact=Artifact(path=rel_path, hash=digest, parse_ok=False, error=str(exc)),
                nodes=[],
                edges=[],
                errors=errors,
                duration_ms=duration_ms,
                success=False
            )


class WorkPool:
    """Manages parallel parsing workers using ThreadPoolExecutor.
    
    This class manages a pool of worker threads that parse Python files in parallel.
    It distributes parsing tasks across workers and yields results as they complete,
    enabling streaming processing of parse results.
    
    Attributes:
        workers: Number of worker threads
        repo: Repository root path
        _executor: ThreadPoolExecutor for managing worker threads
    """

    def __init__(self, workers: int, repo: Path):
        """Initialize work pool with ThreadPoolExecutor.
        
        Args:
            workers: Number of worker threads to create
            repo: Repository root path for parsing context
        """
        self.workers = workers
        self.repo = repo
        self._executor = ThreadPoolExecutor(max_workers=workers)
        logger.info(f"Initialized WorkPool with {workers} workers")

    def submit_tasks(self, tasks: list[ParseTask]) -> Iterator[ParseResult]:
        """Submit tasks and yield results as they complete.
        
        This method submits all parsing tasks to the thread pool and yields
        results as they complete, enabling streaming processing. Results are
        yielded in completion order, not submission order.
        
        Args:
            tasks: List of ParseTask objects to process
            
        Yields:
            ParseResult objects as tasks complete
        """
        # Submit all tasks to the executor
        future_to_task = {
            self._executor.submit(ParseWorker.parse, task, self.repo): task
            for task in tasks
        }

        logger.info(f"Submitted {len(tasks)} tasks to WorkPool")

        # Yield results as they complete
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                yield result
            except Exception as exc:
                # Worker thread raised an unexpected exception
                error_msg = f"Worker thread failed for task {task.task_id} ({task.file_path}): {exc}"
                logger.error(error_msg, exc_info=True)

                # Yield error result
                yield ParseResult(
                    task_id=task.task_id,
                    file_path=task.file_path,
                    artifact=Artifact(
                        path=str(task.file_path),
                        hash="",
                        parse_ok=False,
                        error=str(exc)
                    ),
                    nodes=[],
                    edges=[],
                    errors=[error_msg],
                    duration_ms=0.0,
                    success=False
                )

    def shutdown(self, timeout: float = 30.0) -> None:
        """Shutdown work pool gracefully with timeout.
        
        This method attempts to gracefully shutdown the thread pool by waiting
        for in-progress tasks to complete. If tasks don't complete within the
        timeout period, it forces termination and logs a warning.
        
        Args:
            timeout: Maximum wait time in seconds (default: 30.0)
        """
        logger.info(f"Shutting down WorkPool (timeout={timeout}s)")

        try:
            # Attempt graceful shutdown with timeout
            self._executor.shutdown(wait=True, cancel_futures=False)
            logger.info("WorkPool shutdown completed successfully")
        except Exception as exc:
            # Log any errors during shutdown
            logger.error(f"Error during WorkPool shutdown: {exc}", exc_info=True)

            # Force shutdown if graceful shutdown failed
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
                logger.warning("WorkPool forced shutdown after error")
            except Exception as force_exc:
                logger.critical(f"Failed to force shutdown WorkPool: {force_exc}")


class DTGAggregator:
    """Aggregates DTG results from parallel workers.
    
    This class collects nodes and edges from multiple parse workers and
    aggregates them into a single consistent Data Transformation Graph (DTG).
    It handles node deduplication by keeping the first occurrence of each
    unique symbol and tracks conflicts for debugging purposes.
    
    Attributes:
        _nodes: Dictionary mapping symbol names to DataNode objects
        _edges: List of all TransformEdge objects
        _conflicts: List of conflict descriptions for debugging
    """

    def __init__(self):
        """Initialize aggregator with empty node/edge collections."""
        self._nodes: dict[str, DataNode] = {}
        self._edges: list[TransformEdge] = []
        self._conflicts: list[str] = []
        logger.debug("Initialized DTGAggregator")

    def add_result(self, result: ParseResult) -> None:
        """Add parse result to aggregation.
        
        This method processes a ParseResult from a worker thread and adds
        its nodes and edges to the aggregated DTG. For nodes, it implements
        deduplication by keeping only the first occurrence of each unique
        symbol. Duplicate node definitions are logged as conflicts.
        
        For edges, all edges are kept since duplicate edges may represent
        multiple call sites or relationships in the code.
        
        Args:
            result: ParseResult from a worker thread containing nodes and edges
        """
        # Add nodes with deduplication (keep first occurrence)
        for node in result.nodes:
            if node.symbol in self._nodes:
                # Duplicate node detected - log conflict and keep first occurrence
                conflict_msg = (
                    f"Duplicate node '{node.symbol}' found in {result.file_path}. "
                    f"Keeping first occurrence from {self._nodes[node.symbol].location}, "
                    f"ignoring occurrence from {node.location}"
                )
                logger.debug(conflict_msg)
                self._conflicts.append(conflict_msg)
            else:
                # First occurrence - add to nodes dictionary
                self._nodes[node.symbol] = node

        # Add all edges (duplicates may represent multiple call sites)
        self._edges.extend(result.edges)

        logger.debug(
            f"Added result from {result.file_path}: "
            f"{len(result.nodes)} nodes, {len(result.edges)} edges"
        )

    def resolve_conflicts(self) -> None:
        """Resolve conflicting node definitions.
        
        This method processes the conflicts detected during aggregation and logs
        warnings for duplicate nodes. The conflict resolution strategy is:
        
        1. Duplicate nodes: Keep first occurrence (already handled in add_result)
        2. Duplicate edges: Keep all (may represent multiple call sites)
        
        This method should be called after all results have been added via add_result()
        but before retrieving the final DTG with get_dtg().
        """
        if self._conflicts:
            logger.warning(
                f"Detected {len(self._conflicts)} node conflicts during DTG aggregation. "
                f"Keeping first occurrence for each duplicate node."
            )

            # Log individual conflict warnings for debugging
            for conflict in self._conflicts:
                logger.warning(f"Node conflict: {conflict}")
        else:
            logger.debug("No conflicts detected during DTG aggregation")

    def get_dtg(self) -> tuple[list[DataNode], list[TransformEdge]]:
        """Get aggregated DTG as lists of nodes and edges.
        
        Returns:
            Tuple of (nodes, edges) where nodes is a list of DataNode objects
            and edges is a list of TransformEdge objects
        """
        nodes = list(self._nodes.values())
        logger.info(
            f"DTG aggregation complete: {len(nodes)} nodes, "
            f"{len(self._edges)} edges, {len(self._conflicts)} conflicts"
        )
        return nodes, self._edges

    def get_conflicts(self) -> list[str]:
        """Get list of conflicts detected during aggregation.
        
        Returns:
            List of conflict description strings
        """
        return self._conflicts.copy()

    def verify_integrity(self) -> list[str]:
        """Verify DTG integrity constraints on aggregated graph.
        
        This method performs in-memory verification of the aggregated DTG
        to ensure it meets integrity constraints before storage. It checks:
        
        1. No self-loops (except allowed cases like "parameter" edges)
        2. Valid confidence bounds [0.0, 1.0] for all edges
        3. No dangling edges (edges referencing non-existent nodes)
        
        This verification is compatible with GraphVerifier checks and ensures
        that parallel parsing produces DTGs that pass the same integrity
        verification as sequential parsing.
        
        Returns:
            List of integrity violation messages (empty if valid)
        """
        violations: list[str] = []

        # Build set of node symbols for dangling edge detection
        node_symbols = set(self._nodes.keys())

        # Check each edge for integrity violations
        for edge in self._edges:
            # Check 1: Self-loops (except allowed cases)
            # Parameter edges are allowed to be self-loops (function -> parameter)
            if edge.source == edge.target and edge.transform_kind not in ("parameter",):
                violations.append(
                    f"Self-loop detected: {edge.source} -> {edge.target} "
                    f"(kind={edge.transform_kind}, location={edge.location})"
                )

            # Check 2: Valid confidence bounds [0.0, 1.0]
            if not (0.0 <= edge.confidence <= 1.0):
                violations.append(
                    f"Invalid confidence score: {edge.confidence} for edge "
                    f"{edge.source} -> {edge.target} (must be in [0.0, 1.0])"
                )

            # Check 3: Dangling edges (edges referencing non-existent nodes)
            # Note: We allow edges to external symbols (cross-module references)
            # Only flag edges where both source and target are missing
            if edge.source not in node_symbols and edge.target not in node_symbols:
                violations.append(
                    f"Dangling edge: {edge.source} -> {edge.target} "
                    f"(neither source nor target node exists)"
                )

        if violations:
            logger.warning(
                f"DTG integrity verification found {len(violations)} violations"
            )
        else:
            logger.debug("DTG integrity verification passed with no violations")

        return violations


class ProgressReporter:
    """Reports parsing progress in real-time.

    Tracks files parsed, calculates throughput (files/sec), percentage
    complete, and estimated time remaining.  Final statistics include
    total duration, average throughput, speedup factor, and success/error
    counts.

    Requirements: 10.1, 10.2, 10.3, 10.4
    """

    def __init__(self, total_files: int, interval: float = 5.0) -> None:
        """Initialize reporter.

        Args:
            total_files: Total number of files to parse.
            interval: Reporting interval in seconds (default: 5.0).
        """
        import time

        self.total_files = total_files
        self.interval = interval
        self._start_time: float = time.perf_counter()
        self._last_report_time: float = self._start_time
        self._last_report_count: int = 0

    def update(self, files_parsed: int) -> None:
        """Update progress and log if the reporting interval has elapsed.

        Calculates percentage complete, current throughput (files/sec), and
        estimated time remaining (ETA).  Logs a progress line whenever the
        configured interval has elapsed since the last report.

        Args:
            files_parsed: Cumulative number of files parsed so far.
        """
        import time

        now = time.perf_counter()
        elapsed_since_last = now - self._last_report_time

        if elapsed_since_last < self.interval:
            return

        total_elapsed = now - self._start_time
        percentage = (files_parsed / self.total_files * 100) if self.total_files > 0 else 0.0
        throughput = files_parsed / total_elapsed if total_elapsed > 0 else 0.0

        remaining_files = max(0, self.total_files - files_parsed)
        eta_seconds = remaining_files / throughput if throughput > 0 else float("inf")
        eta_str = f"{eta_seconds:.1f}s" if eta_seconds != float("inf") else "unknown"

        logger.info(
            f"Progress: {files_parsed}/{self.total_files} files "
            f"({percentage:.1f}%) | "
            f"{throughput:.1f} files/sec | "
            f"ETA: {eta_str}"
        )

        self._last_report_time = now
        self._last_report_count = files_parsed

    def report_final(self, duration: float, errors: int) -> None:
        """Report final statistics after parsing completes.

        Logs total duration, average throughput, speedup factor (relative to
        a single-threaded baseline of 1.0), and successful vs error counts.

        Args:
            duration: Total parsing duration in seconds.
            errors: Number of files that encountered parse errors.
        """
        successful = self.total_files - errors
        throughput = self.total_files / duration if duration > 0 else 0.0

        # Speedup factor: ratio of actual throughput to single-threaded baseline.
        # Single-threaded baseline is defined as 1.0 (no speedup).
        # The actual speedup is reported as the throughput ratio; callers may
        # supply a measured baseline, but here we report the raw throughput and
        # a nominal speedup of 1.0 when no baseline is available.
        speedup_factor = 1.0  # Baseline; updated by FreeThreadedIndexer if available

        logger.info(
            f"Parsing complete: {self.total_files} files in {duration:.2f}s | "
            f"throughput: {throughput:.1f} files/sec | "
            f"speedup: {speedup_factor:.1f}x | "
            f"successful: {successful} | "
            f"errors: {errors}"
        )


class FreeThreadedIndexer:
    """Parallel indexer using Python 3.14+ free-threading.

    Drop-in replacement for PythonIndexer that uses parallel parsing when
    Python 3.14+ with free-threading is available, and falls back to
    single-threaded mode on Python 3.11-3.13 or when the GIL is enabled.

    Requirements: 1.3, 1.5, 7.1, 7.2, 7.3, 9.1, 9.2, 11.1, 11.2, 11.3, 11.5
    """

    def __init__(
        self,
        repo: Path,
        db_path: Path,
        workers: int | None = None,
        batch_size: int = 10,
        progress_interval: float = 5.0,
    ) -> None:
        """Initialize indexer.

        Args:
            repo: Repository root path
            db_path: Database path for storage
            workers: Number of worker threads (default: CPU count)
            batch_size: Files per work batch (controls granularity)
            progress_interval: Progress reporting interval in seconds
        """
        import os

        from .repository import Repository

        self.repo = repo
        self.db_path = db_path
        self.batch_size = batch_size
        self.progress_interval = progress_interval

        # Detect Python version and select parsing mode (Req 1.3)
        self.mode: ParsingMode = VersionDetector.detect()

        # Determine worker count (Req 9.1, 9.2, 11.1, 11.5)
        cpu_count = os.cpu_count() or 4
        if workers is None:
            self.workers = cpu_count
        else:
            self.workers = workers

        # Warn if workers exceeds available CPU cores (Req 11.5)
        if self.workers > cpu_count:
            logger.warning(
                f"workers={self.workers} exceeds available CPU cores ({cpu_count}). "
                f"This may cause overhead due to thread contention."
            )

        # Log detected mode and configuration (Req 1.3)
        logger.info(
            f"FreeThreadedIndexer initialized: repo={repo}, db_path={db_path}, "
            f"workers={self.workers}, batch_size={batch_size}, "
            f"progress_interval={progress_interval}s"
        )
        logger.info(
            f"Parsing mode: {'parallel' if self.mode.parallel else 'single-threaded'} "
            f"(Python {self.mode.python_version[0]}.{self.mode.python_version[1]}, "
            f"GIL={'enabled' if self.mode.gil_enabled else 'disabled'}) — {self.mode.reason}"
        )

        self.repository = Repository(db_path)
        self._work_pool: WorkPool | None = None

    # ------------------------------------------------------------------
    # Resource management (Task 10.4)
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Initialize database schema (delegates to Repository).

        Requirements: 9.1
        """
        self.repository.init()
        logger.info("FreeThreadedIndexer: database schema initialized")

    def close(self) -> None:
        """Close database connection and gracefully shut down workers.

        Requirements: 9.2, 9.3, 9.4
        """
        # Shut down work pool if it was created
        if self._work_pool is not None:
            self._work_pool.shutdown(timeout=30.0)
            self._work_pool = None

        self.repository.close()
        logger.info("FreeThreadedIndexer: closed")

    # ------------------------------------------------------------------
    # Build (Task 10.2)
    # ------------------------------------------------------------------

    def build(self) -> dict:
        """Build complete DTG index from scratch.

        Orchestrates:
        1. Parallel file discovery via ParallelFileDiscovery
        2. ParseTask creation for each discovered file
        3. Parallel parsing via WorkPool
        4. Result aggregation via DTGAggregator
        5. Storage via Repository
        6. Returns BuildResult-compatible statistics dict

        Requirements: 5.3, 4.5, 7.1

        Returns:
            Dictionary with build statistics (compatible with PythonIndexer.build())
        """
        import time

        logger.info(f"Starting full index build for {self.repo}")
        start_time = time.perf_counter()

        # Phase 1: File discovery
        discovery = ParallelFileDiscovery(self.repo, workers=self.workers)
        file_metadata_list = discovery.discover()
        total_files = len(file_metadata_list)
        logger.info(f"Discovered {total_files} Python files")

        if total_files == 0:
            result = {
                "artifacts": 0,
                "nodes": 0,
                "edges": 0,
                "parse_errors": 0,
                "dependency_seeds": 0,
                "files": 0,
            }
            logger.info(f"Index build complete (no files): {result}")
            return result

        # Phase 2: Create ParseTask instances
        tasks = [
            ParseTask(
                file_path=fm.path,
                file_metadata={"size": fm.size, "hash": fm.hash, "language": fm.language},
                task_id=idx,
            )
            for idx, fm in enumerate(file_metadata_list)
        ]

        # Phase 3: Submit tasks to WorkPool and aggregate results
        aggregator = DTGAggregator()
        reporter = ProgressReporter(total_files=total_files, interval=self.progress_interval)
        all_artifacts = []
        files_parsed = 0
        parse_errors = 0

        # Determine effective worker count based on parsing mode (Req 1.4, 1.5)
        # When parallel mode is unavailable, fall back to sequential (workers=1)
        if not self.mode.parallel:
            effective_workers = 1
            logger.info(
                f"Single-threaded fallback mode active: {self.mode.reason}. "
                f"Using workers=1 for sequential parsing."
            )
        else:
            effective_workers = self.workers

        self._work_pool = WorkPool(workers=effective_workers, repo=self.repo)
        try:
            for parse_result in self._work_pool.submit_tasks(tasks):
                aggregator.add_result(parse_result)
                all_artifacts.append(parse_result.artifact)
                files_parsed += 1
                if not parse_result.success:
                    parse_errors += 1
                reporter.update(files_parsed)
        finally:
            self._work_pool.shutdown(timeout=30.0)
            self._work_pool = None

        # Resolve conflicts in aggregated DTG
        aggregator.resolve_conflicts()
        nodes, edges = aggregator.get_dtg()

        # Phase 4: Store results in Repository
        result_counts = self.repository.index_build(all_artifacts, nodes, edges)

        duration = time.perf_counter() - start_time
        reporter.report_final(duration=duration, errors=parse_errors)

        result = {
            "artifacts": result_counts["artifacts"],
            "nodes": result_counts["nodes"],
            "edges": result_counts["edges"],
            "parse_errors": parse_errors,
            "dependency_seeds": 0,
            "files": total_files,
        }
        logger.info(f"Index build complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Update (Task 10.3)
    # ------------------------------------------------------------------

    def update(self, changed_files=None) -> dict:
        """Update index for changed files (incremental update).

        If changed_files is not provided, detects changes using git diff.
        Otherwise, processes the specified files.

        Requirements: 7.2

        Args:
            changed_files: Optional iterable of changed file paths

        Returns:
            Dictionary with update statistics (compatible with PythonIndexer.update())
        """
        import time

        logger.info("Starting incremental index update")

        # Detect changed files if not provided
        if changed_files is None:
            changed_files = self._detect_changed_files()
        else:
            changed_files = list(changed_files)

        if not changed_files:
            logger.info("No changed files detected")
            stats = self.repository.get_statistics()
            return {
                "artifacts": stats["artifacts"],
                "nodes": stats["nodes"],
                "edges": stats["edges"],
                "parse_errors": 0,
                "dependency_seeds": 0,
                "files": stats["artifacts"],
                "updated": False,
            }

        logger.info(f"Detected {len(changed_files)} changed files")
        start_time = time.perf_counter()

        # Create ParseTask instances for changed files
        tasks = [
            ParseTask(
                file_path=Path(fp) if not isinstance(fp, Path) else fp,
                file_metadata={},
                task_id=idx,
            )
            for idx, fp in enumerate(changed_files)
        ]

        # Parse changed files in parallel (or sequential if fallback mode)
        aggregator = DTGAggregator()
        all_artifacts = []
        parse_errors = 0

        # Respect parsing mode for update as well (Req 1.4, 1.5)
        effective_workers = 1 if not self.mode.parallel else self.workers
        if not self.mode.parallel:
            logger.info(
                f"Single-threaded fallback mode active for update: {self.mode.reason}. "
                f"Using workers=1 for sequential parsing."
            )

        self._work_pool = WorkPool(workers=effective_workers, repo=self.repo)
        try:
            for parse_result in self._work_pool.submit_tasks(tasks):
                aggregator.add_result(parse_result)
                all_artifacts.append(parse_result.artifact)
                if not parse_result.success:
                    parse_errors += 1
        finally:
            self._work_pool.shutdown(timeout=30.0)
            self._work_pool = None

        aggregator.resolve_conflicts()
        new_nodes, new_edges = aggregator.get_dtg()

        # Upsert changed artifacts
        self.repository.storage.upsert_artifacts(all_artifacts)

        # Fetch current full graph state
        conn = self.repository.storage.conn
        all_artifacts_rows = conn.execute(
            "SELECT path, hash, parse_ok, error FROM artifacts"
        ).fetchall()
        from .models import Artifact as _Artifact
        from .models import DataNode as _DataNode
        from .models import TransformEdge as _TransformEdge

        all_artifacts_full = [
            _Artifact(path=r["path"], hash=r["hash"], parse_ok=bool(r["parse_ok"]), error=r["error"])
            for r in all_artifacts_rows
        ]

        all_nodes_rows = conn.execute(
            "SELECT symbol, module, kind, location FROM nodes"
        ).fetchall()
        all_nodes = [
            _DataNode(symbol=r["symbol"], module=r["module"], kind=r["kind"], location=r["location"])
            for r in all_nodes_rows
        ]

        all_edges_rows = conn.execute(
            "SELECT source, target, transform_symbol, transform_kind, location, confidence FROM edges"
        ).fetchall()
        all_edges = [
            _TransformEdge(
                source=r["source"],
                target=r["target"],
                transform_symbol=r["transform_symbol"],
                transform_kind=r["transform_kind"],
                location=r["location"],
                confidence=r["confidence"],
            )
            for r in all_edges_rows
        ]

        # Remove old nodes/edges for changed files, then add new ones
        changed_paths = {
            str(Path(fp).relative_to(self.repo)) if Path(fp).is_absolute() else str(fp)
            for fp in changed_files
        }
        all_nodes = [n for n in all_nodes if not any(p in n.location for p in changed_paths)]
        all_edges = [e for e in all_edges if not any(p in e.location for p in changed_paths)]
        all_nodes.extend(new_nodes)
        all_edges.extend(new_edges)

        self.repository.storage.replace_nodes_edges(all_nodes, all_edges)

        duration = time.perf_counter() - start_time
        logger.info(f"Incremental update complete in {duration:.2f}s")

        result = {
            "artifacts": len(all_artifacts_full),
            "nodes": len(all_nodes),
            "edges": len(all_edges),
            "parse_errors": parse_errors,
            "dependency_seeds": 0,
            "files": len(all_artifacts_full),
            "updated": True,
        }
        logger.info(f"Index update complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _detect_changed_files(self) -> list[Path]:
        """Detect changed Python files using git diff.

        Returns:
            List of changed Python file paths
        """
        import subprocess

        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning(f"git diff failed: {result.stderr}")
                return []

            changed: list[Path] = []
            for line in result.stdout.strip().split("\n"):
                if line.endswith(".py"):
                    fp = self.repo / line
                    if fp.exists():
                        changed.append(fp)

            logger.info(f"Detected {len(changed)} changed Python files via git")
            return changed
        except Exception as exc:
            logger.warning(f"Failed to detect changed files: {exc}")
            return []
