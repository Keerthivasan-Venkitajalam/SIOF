from __future__ import annotations

import ast
import hashlib
import logging
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from .models import Artifact, DataNode, TransformEdge, module_name
from .repository import Repository
from .verifier import GraphVerifier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SymbolInfo:
    """Comprehensive symbol metadata extracted from AST."""
    name: str
    kind: str  # function, class, method, property, variable, decorator
    module: str
    location: str  # file:line
    signature: str | None = None  # function/method signature
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    type_hints: dict[str, str] = field(default_factory=dict)  # param/return type hints
    parent_class: str | None = None  # for methods
    scope: str | None = None  # qualified scope path
    is_async: bool = False
    is_generator: bool = False
    is_property: bool = False
    is_abstract: bool = False
    bases: list[str] = field(default_factory=list)  # for classes
    parameters: list[str] = field(default_factory=list)  # for functions/methods


@dataclass(slots=True)
class ScopeLevel:
    """Represents a scope level in the symbol table."""
    name: str
    kind: str  # module, class, function
    symbols: dict[str, SymbolInfo] = field(default_factory=dict)
    parent: ScopeLevel | None = None
    children: list[ScopeLevel] = field(default_factory=list)


@dataclass(slots=True)
class ParseResult:
    artifact: Artifact
    nodes: list[DataNode]
    edges: list[TransformEdge]


class SymbolTable:
    """Manages symbol scopes and hierarchical symbol resolution."""

    def __init__(self, module: str):
        """Initialize symbol table for a module.

        Args:
            module: Module name (e.g., 'package.module')
        """
        self.module = module
        self.root = ScopeLevel(name=module, kind="module")
        self.current_scope = self.root
        self.all_symbols: dict[str, SymbolInfo] = {}

    def push_scope(self, name: str, kind: str) -> ScopeLevel:
        """Enter a new scope (class or function).

        Args:
            name: Scope name
            kind: Scope kind ('class' or 'function')

        Returns:
            New ScopeLevel
        """
        scope = ScopeLevel(name=name, kind=kind, parent=self.current_scope)
        self.current_scope.children.append(scope)
        self.current_scope = scope
        return scope

    def pop_scope(self) -> None:
        """Exit current scope."""
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent

    def add_symbol(self, symbol: SymbolInfo) -> None:
        """Add symbol to current scope.

        Args:
            symbol: SymbolInfo to add
        """
        self.current_scope.symbols[symbol.name] = symbol
        # Store fully qualified name
        qualified = self._get_qualified_name(symbol.name)
        self.all_symbols[qualified] = symbol

    def _get_qualified_name(self, name: str) -> str:
        """Get fully qualified name for symbol in current scope.

        Args:
            name: Symbol name

        Returns:
            Fully qualified name (e.g., 'module.Class.method')
        """
        parts = [self.module]
        scope = self.current_scope
        while scope.parent:
            parts.insert(1, scope.name)
            scope = scope.parent
        parts.append(name)
        return ".".join(parts)

    def get_scope_path(self) -> str:
        """Get current scope path.

        Returns:
            Scope path (e.g., 'module.Class.method')
        """
        parts = [self.module]
        scope = self.current_scope
        while scope.parent:
            parts.insert(1, scope.name)
            scope = scope.parent
        return ".".join(parts)

    def get_all_symbols(self) -> dict[str, SymbolInfo]:
        """Get all symbols in table.

        Returns:
            Dictionary of all symbols
        """
        return self.all_symbols.copy()


class SymbolExtractor(ast.NodeVisitor):
    """Comprehensive symbol extraction from Python AST."""

    def __init__(self, module: str, file_path: str):
        """Initialize extractor.

        Args:
            module: Module name
            file_path: File path for location tracking
        """
        self.module = module
        self.file_path = file_path
        self.symbol_table = SymbolTable(module)
        self.current_class: str | None = None
        self.current_function: str | None = None

    def extract(self, tree: ast.AST) -> dict[str, SymbolInfo]:
        """Extract all symbols from AST.

        Args:
            tree: AST tree to extract from

        Returns:
            Dictionary of extracted symbols
        """
        self.visit(tree)
        return self.symbol_table.get_all_symbols()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition."""
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition."""
        self._visit_function(node, is_async=True)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        """Process function definition.

        Args:
            node: Function node
            is_async: Whether function is async
        """
        # Extract decorators
        decorators = [self._get_decorator_name(d) for d in node.decorator_list]

        # Extract parameters
        parameters = [arg.arg for arg in node.args.args]

        # Extract type hints
        type_hints = {}
        for arg in node.args.args:
            if arg.annotation:
                type_hints[arg.arg] = ast.unparse(arg.annotation)
        if node.returns:
            type_hints["return"] = ast.unparse(node.returns)

        # Extract docstring
        docstring = ast.get_docstring(node)

        # Build signature
        signature = self._build_function_signature(node)

        # Determine if generator or property
        is_generator = self._is_generator(node)
        is_property = any(d == "property" for d in decorators)
        is_abstract = any(d in ("abstractmethod", "abstractproperty") for d in decorators)

        # Create symbol
        symbol = SymbolInfo(
            name=node.name,
            kind="method" if self.current_class else "function",
            module=self.module,
            location=f"{self.file_path}:{node.lineno}",
            signature=signature,
            docstring=docstring,
            decorators=decorators,
            type_hints=type_hints,
            parent_class=self.current_class,
            scope=self.symbol_table.get_scope_path(),
            is_async=is_async,
            is_generator=is_generator,
            is_property=is_property,
            is_abstract=is_abstract,
            parameters=parameters,
        )

        self.symbol_table.add_symbol(symbol)

        # Push scope for nested definitions
        old_function = self.current_function
        self.current_function = node.name
        self.symbol_table.push_scope(node.name, "function")
        self.generic_visit(node)
        self.symbol_table.pop_scope()
        self.current_function = old_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition."""
        # Extract decorators
        decorators = [self._get_decorator_name(d) for d in node.decorator_list]

        # Extract base classes
        bases = [ast.unparse(base) for base in node.bases]

        # Extract docstring
        docstring = ast.get_docstring(node)

        # Determine if abstract (check decorators and base classes)
        is_abstract = any(d in ("abstractmethod", "ABC") for d in decorators) or any(b in ("ABC", "ABCMeta") for b in bases)

        # Create symbol
        symbol = SymbolInfo(
            name=node.name,
            kind="class",
            module=self.module,
            location=f"{self.file_path}:{node.lineno}",
            docstring=docstring,
            decorators=decorators,
            scope=self.symbol_table.get_scope_path(),
            is_abstract=is_abstract,
            bases=bases,
        )

        self.symbol_table.add_symbol(symbol)

        # Push scope for class members
        old_class = self.current_class
        self.current_class = node.name
        self.symbol_table.push_scope(node.name, "class")
        self.generic_visit(node)
        self.symbol_table.pop_scope()
        self.current_class = old_class

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignment (module/class level variables)."""
        # Only track top-level and class-level assignments
        if self.current_function:
            self.generic_visit(node)
            return

        for target in node.targets:
            if isinstance(target, ast.Name):
                # Extract type hint if available
                type_hints = {}
                if isinstance(node.value, ast.Call):
                    type_hints["inferred"] = ast.unparse(node.value.func)

                symbol = SymbolInfo(
                    name=target.id,
                    kind="variable",
                    module=self.module,
                    location=f"{self.file_path}:{node.lineno}",
                    type_hints=type_hints,
                    scope=self.symbol_table.get_scope_path(),
                )
                self.symbol_table.add_symbol(symbol)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit annotated assignment."""
        if self.current_function:
            self.generic_visit(node)
            return

        if isinstance(node.target, ast.Name):
            type_hints = {"type": ast.unparse(node.annotation)}

            symbol = SymbolInfo(
                name=node.target.id,
                kind="variable",
                module=self.module,
                location=f"{self.file_path}:{node.lineno}",
                type_hints=type_hints,
                scope=self.symbol_table.get_scope_path(),
            )
            self.symbol_table.add_symbol(symbol)

        self.generic_visit(node)

    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract decorator name from decorator node.

        Args:
            decorator: Decorator AST node

        Returns:
            Decorator name
        """
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Attribute):
            return decorator.attr
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id
            if isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr
        return ast.unparse(decorator)

    def _build_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Build function signature string.

        Args:
            node: Function node

        Returns:
            Function signature
        """
        args = []
        for arg in node.args.args:
            if arg.annotation:
                args.append(f"{arg.arg}: {ast.unparse(arg.annotation)}")
            else:
                args.append(arg.arg)

        # Handle *args and **kwargs
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")

        return_type = ""
        if node.returns:
            return_type = f" -> {ast.unparse(node.returns)}"

        return f"({', '.join(args)}){return_type}"

    def _is_generator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if function is a generator.

        Args:
            node: Function node

        Returns:
            True if function contains yield
        """
        for child in ast.walk(node):
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                return True
        return False


@dataclass(slots=True)
class FileMetadata:
    """Metadata for discovered Python file."""
    path: Path
    size: int
    hash: str
    language: str = "python"


@dataclass(slots=True)
class DependencySeed:
    """Extracted dependency seed from a file."""
    module: str
    imports: list[str] = field(default_factory=list)
    from_imports: dict[str, list[str]] = field(default_factory=dict)
    local_symbols: list[str] = field(default_factory=list)


def _hash_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class FileDiscovery:
    """Recursively discover Python files in repository with metadata extraction."""

    # Directories to skip during traversal
    SKIP_DIRS: ClassVar[set[str]] = {
        ".venv", "venv", "env",
        "__pycache__",
        ".egg-info", ".eggs",
        "node_modules",
        ".git", ".hg", ".svn",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        "dist", "build",
        ".coverage",
    }

    def __init__(self, repo: Path, follow_symlinks: bool = False):
        """Initialize file discovery.

        Args:
            repo: Repository root path
            follow_symlinks: Whether to follow symbolic links (default: False for safety)
        """
        self.repo = repo
        self.follow_symlinks = follow_symlinks
        self._visited_inodes: set[int] = set()

    def discover(self) -> list[FileMetadata]:
        """Discover all Python files in repository.

        Returns:
            List of FileMetadata for discovered Python files
        """
        files: list[FileMetadata] = []
        self._visited_inodes.clear()

        try:
            self._walk_directory(self.repo, files)
        except Exception as exc:
            logger.error(f"Error during file discovery: {exc}")

        logger.info(f"Discovered {len(files)} Python files")
        return files

    def _walk_directory(self, directory: Path, files: list[FileMetadata]) -> None:
        """Recursively walk directory tree, skipping irrelevant directories.

        Args:
            directory: Current directory to walk
            files: Accumulator list for discovered files
        """
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError) as exc:
            logger.warning(f"Cannot read directory {directory}: {exc}")
            return

        for entry in entries:
            # Skip irrelevant directories
            # Note: follow_symlinks parameter for is_dir() requires Python 3.13+
            # For Python 3.11-3.12, we check symlinks separately
            try:
                is_directory = entry.is_dir()
            except OSError:
                continue

            if is_directory:
                if entry.name in self.SKIP_DIRS:
                    continue

                # Handle symlinks safely
                if entry.is_symlink() and not self.follow_symlinks:
                    continue

                # Detect circular references via inode tracking
                try:
                    stat = entry.stat(follow_symlinks=False)
                    inode = stat.st_ino
                    if inode in self._visited_inodes:
                        logger.debug(f"Skipping circular symlink: {entry}")
                        continue
                    self._visited_inodes.add(inode)
                except (OSError, ValueError):
                    logger.debug(f"Cannot stat {entry}, skipping")
                    continue

                self._walk_directory(entry, files)

            # Collect Python files
            else:
                try:
                    is_python_file = entry.is_file() and entry.suffix == ".py"
                except OSError:
                    continue

                if is_python_file:
                    # Handle symlinks for files
                    if entry.is_symlink() and not self.follow_symlinks:
                        continue
                    try:
                        metadata = self._extract_file_metadata(entry)
                        files.append(metadata)
                    except Exception as exc:
                        logger.warning(f"Error extracting metadata for {entry}: {exc}")

    def _extract_file_metadata(self, file_path: Path) -> FileMetadata:
        """Extract metadata for a Python file.

        Args:
            file_path: Path to Python file

        Returns:
            FileMetadata with size and hash
        """
        try:
            content = file_path.read_bytes()
            size = len(content)
            hash_val = hashlib.sha256(content).hexdigest()
            return FileMetadata(path=file_path, size=size, hash=hash_val)
        except Exception as exc:
            logger.error(f"Failed to read {file_path}: {exc}")
            raise


class DependencySeedExtractor:
    """Extract dependency seeds (imports, module structure) from Python files."""

    def __init__(self, repo: Path):
        """Initialize extractor.

        Args:
            repo: Repository root path
        """
        self.repo = repo

    def extract(self, file_path: Path) -> DependencySeed | None:
        """Extract dependency seed from a Python file.

        Args:
            file_path: Path to Python file

        Returns:
            DependencySeed with imports and local symbols, or None on error
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except SyntaxError as exc:
            logger.warning(f"Syntax error in {file_path}: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Failed to parse {file_path}: {exc}")
            return None

        mod = module_name(self.repo, file_path)
        imports: list[str] = []
        from_imports: dict[str, list[str]] = {}
        local_symbols: list[str] = []

        for node in ast.walk(tree):
            # Extract import statements
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)

            # Extract from...import statements
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                if module not in from_imports:
                    from_imports[module] = []
                from_imports[module].extend(names)

            # Extract top-level function and class definitions
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if isinstance(node, ast.FunctionDef):
                    local_symbols.append(f"{mod}.{node.name}")
                else:
                    local_symbols.append(f"{mod}.{node.name}")

        return DependencySeed(
            module=mod,
            imports=imports,
            from_imports=from_imports,
            local_symbols=local_symbols,
        )

    def extract_batch(self, file_paths: Iterable[Path]) -> dict[str, DependencySeed]:
        """Extract dependency seeds from multiple files.

        Args:
            file_paths: Iterable of file paths

        Returns:
            Dictionary mapping module name to DependencySeed
        """
        seeds: dict[str, DependencySeed] = {}
        for file_path in file_paths:
            seed = self.extract(file_path)
            if seed:
                seeds[seed.module] = seed
        return seeds


def discover_python_files(repo: Path) -> list[Path]:
    """Discover Python files in repo, excluding common non-source directories."""
    discovery = FileDiscovery(repo)
    metadata_list = discovery.discover()
    return [m.path for m in metadata_list]


class PythonIndexer:
    """Indexes Python repositories into a DTG (Data Transformation Graph)."""

    def __init__(self, repo: Path, db_path: Path, workers: int | None = None):
        self.repo = repo
        self.db_path = db_path
        self.repository = Repository(db_path)
        self.workers = workers or max(2, (os.cpu_count() or 4))
        self.file_discovery = FileDiscovery(repo)
        self.seed_extractor = DependencySeedExtractor(repo)
        logger.info(f"Initialized indexer for {repo} with {self.workers} workers")

    def init(self) -> None:
        """Initialize database schema."""
        self.repository.init()
        logger.info("Database schema initialized")

    def close(self) -> None:
        """Close database connection."""
        self.repository.close()

    def discover_files(self) -> list[FileMetadata]:
        """Discover Python files in repository.

        Returns:
            List of FileMetadata for discovered files
        """
        return self.file_discovery.discover()

    def extract_dependency_seeds(self, files: list[Path]) -> dict[str, DependencySeed]:
        """Extract dependency seeds from files.

        Args:
            files: List of file paths

        Returns:
            Dictionary mapping module name to DependencySeed
        """
        return self.seed_extractor.extract_batch(files)

    def build(self) -> dict:
        """Build complete DTG index from scratch."""
        logger.info(f"Starting full index build for {self.repo}")

        # Phase 1: File discovery
        file_metadata = self.discover_files()
        files = [m.path for m in file_metadata]
        logger.info(f"Discovered {len(files)} Python files")

        # Phase 2: Dependency seed extraction
        seeds = self.extract_dependency_seeds(files)
        logger.info(f"Extracted {len(seeds)} dependency seeds")

        # Phase 3: Parse and build DTG
        results = self._parse_parallel(files)

        artifacts = [r.artifact for r in results]
        nodes = [n for r in results for n in r.nodes]
        edges = [e for r in results for e in r.edges]

        parse_errors = sum(1 for a in artifacts if not a.parse_ok)
        if parse_errors > 0:
            logger.warning(f"{parse_errors} files had parse errors")

        # Use Repository to build index
        result = self.repository.index_build(artifacts, nodes, edges)
        result["parse_errors"] = parse_errors
        result["dependency_seeds"] = len(seeds)
        result["files"] = len(files)

        logger.info(f"Index build complete: {result}")
        return result

    def update(self, changed_files: Iterable[Path] | None = None) -> dict:
        """Update index for changed files.

        If changed_files is not provided, detects changes using git diff.
        Otherwise, processes the specified files.

        Args:
            changed_files: List of changed file paths (optional)

        Returns:
            Dictionary with update statistics
        """
        logger.info("Starting incremental index update")

        # Detect changed files if not provided
        if changed_files is None:
            changed_files = self._detect_changed_files()
        else:
            changed_files = list(changed_files)

        if not changed_files:
            logger.info("No changed files detected")
            # Return current statistics
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

        # Parse changed files
        results = self._parse_parallel(changed_files)

        artifacts = [r.artifact for r in results]
        nodes = [n for r in results for n in r.nodes]
        edges = [e for r in results for e in r.edges]

        parse_errors = sum(1 for a in artifacts if not a.parse_ok)
        if parse_errors > 0:
            logger.warning(f"{parse_errors} files had parse errors")

        # Update artifacts in storage (upsert)
        self.repository.storage.upsert_artifacts(artifacts)

        # For incremental updates, we need to:
        # 1. Remove old nodes/edges for changed files
        # 2. Add new nodes/edges
        # For v1, we'll do a full rebuild for determinism
        # TODO: Implement true incremental updates in v2

        # Get all current data
        all_artifacts_result = self.repository.storage.conn.execute(
            "SELECT path, hash, parse_ok, error FROM artifacts"
        ).fetchall()
        all_artifacts = [
            Artifact(path=r["path"], hash=r["hash"], parse_ok=bool(r["parse_ok"]), error=r["error"])
            for r in all_artifacts_result
        ]

        all_nodes_result = self.repository.storage.conn.execute(
            "SELECT symbol, module, kind, location FROM nodes"
        ).fetchall()
        all_nodes = [
            DataNode(symbol=r["symbol"], module=r["module"], kind=r["kind"], location=r["location"])
            for r in all_nodes_result
        ]

        all_edges_result = self.repository.storage.conn.execute(
            "SELECT source, target, transform_symbol, transform_kind, location, confidence FROM edges"
        ).fetchall()
        all_edges = [
            TransformEdge(
                source=r["source"],
                target=r["target"],
                transform_symbol=r["transform_symbol"],
                transform_kind=r["transform_kind"],
                location=r["location"],
                confidence=r["confidence"],
            )
            for r in all_edges_result
        ]

        # Remove old nodes/edges for changed files
        changed_paths = {str(f.relative_to(self.repo)) for f in changed_files}
        all_nodes = [n for n in all_nodes if not any(p in n.location for p in changed_paths)]
        all_edges = [e for e in all_edges if not any(p in e.location for p in changed_paths)]

        # Add new nodes/edges
        all_nodes.extend(nodes)
        all_edges.extend(edges)

        # Update repository
        self.repository.storage.replace_nodes_edges(all_nodes, all_edges)

        # Return total statistics after update
        result = {
            "artifacts": len(all_artifacts),
            "nodes": len(all_nodes),
            "edges": len(all_edges),
            "parse_errors": parse_errors,
            "dependency_seeds": len(self.extract_dependency_seeds(changed_files)),
            "files": len(all_artifacts),
            "updated": True,
        }
        logger.info(f"Index update complete: {result}")
        return result

    def _detect_changed_files(self) -> list[Path]:
        """Detect changed Python files using git diff.

        Returns:
            List of changed Python file paths
        """
        try:
            import subprocess

            # Get list of changed files from git
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

            changed_files = []
            for line in result.stdout.strip().split("\n"):
                if line.endswith(".py"):
                    file_path = self.repo / line
                    if file_path.exists():
                        changed_files.append(file_path)

            logger.info(f"Detected {len(changed_files)} changed Python files via git")
            return changed_files

        except Exception as exc:
            logger.warning(f"Failed to detect changed files: {exc}")
            return []

    def verify(self) -> dict:
        """Verify graph integrity and detect anomalies.

        Checks:
        1. No self-loops
        2. Valid confidence bounds
        3. Dead nodes
        4. Orphaned nodes
        5. Cycles in transformation graph

        Returns:
            Dictionary with verification results
        """
        logger.info("Starting graph integrity verification")
        verifier = GraphVerifier(self.repository.storage)
        result = verifier.verify()

        # Get statistics
        stats = verifier.get_statistics()

        return {
            "valid": result.valid,
            "total_nodes": result.total_nodes,
            "total_edges": result.total_edges,
            "violations": result.violations,
            "dead_nodes": len(result.dead_nodes),
            "dead_paths": result.dead_nodes,
            "cycles": len(result.cycles),
            "cycle_details": result.cycles,
            "orphaned_nodes": len(result.orphaned_nodes),
            "orphaned_details": result.orphaned_nodes,
            "self_loops": len(result.self_loops),
            "self_loop_details": result.self_loops,
            "invalid_confidence": len(result.invalid_confidence),
            "invalid_confidence_details": result.invalid_confidence,
            "statistics": stats,
        }

    def _parse_parallel(self, files: list[Path]) -> list[ParseResult]:
        """Parse files in parallel using thread pool with progress tracking."""
        out: list[ParseResult] = []
        total = len(files)
        processed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = [ex.submit(self._parse_file, p) for p in files]
            for fut in as_completed(futs):
                try:
                    out.append(fut.result())
                    processed += 1
                    if processed % max(1, total // 10) == 0 or processed == total:
                        logger.info(f"Parsed {processed}/{total} files ({100*processed//total}%)")
                except Exception as exc:
                    logger.error(f"Parse task failed: {exc}")
        return out

    def _parse_file(self, file_path: Path) -> ParseResult:
        """Parse a single Python file and extract DTG nodes/edges with comprehensive symbol extraction."""
        rel = str(file_path.relative_to(self.repo))
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            logger.error(f"Failed to read {rel}: {exc}")
            return ParseResult(
                artifact=Artifact(path=rel, hash="", parse_ok=False, error=str(exc)),
                nodes=[],
                edges=[],
            )

        digest = _hash_text(text)
        mod = module_name(self.repo, file_path)

        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            artifact = Artifact(path=rel, hash=digest, parse_ok=False, error=str(exc))
            logger.warning(f"Parse error in {rel}: {exc}")
            return ParseResult(artifact=artifact, nodes=[], edges=[])

        # Extract comprehensive symbols using SymbolExtractor
        extractor = SymbolExtractor(mod, rel)
        symbols = extractor.extract(tree)

        # Build DTG using dedicated builder
        builder = DTGBuilder(mod, rel)

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
                        symbol = f"{mod}.{target.id}"
                        if isinstance(node.value, ast.Call):
                            fn_name = _call_name(node.value)
                            if fn_name:
                                builder.add_assignment_transform_edge(
                                    fn_name,
                                    symbol,
                                    location=f"{rel}:{node.lineno}",
                                    confidence=0.8,
                                )

        # Verify graph integrity
        violations = builder.verify_integrity()
        if violations:
            logger.debug(f"Graph integrity issues in {rel}: {violations}")

        nodes, edges = builder.build()
        artifact = Artifact(path=rel, hash=digest, parse_ok=True, error=None)
        return ParseResult(artifact=artifact, nodes=nodes, edges=edges)


class DTGBuilder:
    """Builds DTG nodes and edges from parsed symbols and AST analysis.

    Responsible for:
    - Creating DataNode instances from symbols
    - Creating TransformEdge instances for relationships
    - Computing edge confidence scores
    - Enforcing graph integrity constraints
    """

    def __init__(self, module: str, file_path: str):
        """Initialize DTG builder for a specific module.

        Args:
            module: Fully qualified module name (e.g., 'myapp.core.models')
            file_path: Relative file path for location tracking
        """
        self.module = module
        self.file_path = file_path
        self.nodes: list[DataNode] = []
        self.edges: list[TransformEdge] = []
        self._node_symbols: set[str] = set()  # Track created nodes to prevent duplicates

    def add_symbol_node(self, qualified_name: str, symbol: SymbolInfo) -> str:
        """Create a DataNode from a SymbolInfo and add to graph.

        Args:
            qualified_name: Fully qualified symbol name (from SymbolExtractor.extract() keys)
            symbol: SymbolInfo containing symbol metadata

        Returns:
            Fully qualified symbol name for reference in edges
        """
        # Prevent duplicate nodes
        if qualified_name in self._node_symbols:
            return qualified_name

        self.nodes.append(
            DataNode(
                symbol=qualified_name,
                module=self.module,
                kind=symbol.kind,
                location=symbol.location,
            )
        )
        self._node_symbols.add(qualified_name)
        return qualified_name

    def add_parameter_edges(self, qualified_name: str, symbol: SymbolInfo) -> None:
        """Create edges for function/method parameters.

        Args:
            qualified_name: Fully qualified symbol name
            symbol: SymbolInfo for a function or method
        """
        if symbol.kind not in ("function", "method"):
            return

        if not symbol.parameters:
            return

        for param in symbol.parameters:
            param_symbol = f"{qualified_name}:{param}"

            # Create parameter node if not already present
            if param_symbol not in self._node_symbols:
                self.nodes.append(
                    DataNode(
                        symbol=param_symbol,
                        module=self.module,
                        kind="parameter",
                        location=symbol.location,
                    )
                )
                self._node_symbols.add(param_symbol)

            # Create edge from parameter to function
            self.edges.append(
                TransformEdge(
                    source=param_symbol,
                    target=qualified_name,
                    transform_symbol=qualified_name,
                    transform_kind="parameter",
                    location=symbol.location,
                    confidence=1.0,  # Parameters are deterministic
                )
            )

    def add_inheritance_edges(self, qualified_name: str, symbol: SymbolInfo) -> None:
        """Create edges for class inheritance relationships.

        Args:
            qualified_name: Fully qualified symbol name
            symbol: SymbolInfo for a class
        """
        if symbol.kind != "class":
            return

        if not symbol.bases:
            return

        for base in symbol.bases:
            self.edges.append(
                TransformEdge(
                    source=base,
                    target=qualified_name,
                    transform_symbol="inherits",
                    transform_kind="inheritance",
                    location=symbol.location,
                    confidence=1.0,  # Inheritance is deterministic
                )
            )

    def add_decorator_edges(self, qualified_name: str, symbol: SymbolInfo) -> None:
        """Create edges for decorator relationships.

        Args:
            qualified_name: Fully qualified symbol name
            symbol: SymbolInfo with decorators
        """
        if not symbol.decorators:
            return

        for decorator in symbol.decorators:
            self.edges.append(
                TransformEdge(
                    source=decorator,
                    target=qualified_name,
                    transform_symbol=decorator,
                    transform_kind="decorator",
                    location=symbol.location,
                    confidence=0.95,  # High confidence but not 100% (could be dynamic)
                )
            )

    def add_call_edge(
        self,
        source_symbol: str,
        target_symbol: str,
        transform_kind: str = "call",
        location: str = "",
        confidence: float = 0.8,
    ) -> None:
        """Create an edge for a function call or transformation.

        Args:
            source_symbol: Source symbol name
            target_symbol: Target symbol name
            transform_kind: Type of transformation (call, assignment_transform, etc.)
            location: Location in source code
            confidence: Confidence score (0.0-1.0)
        """
        if not location:
            location = self.file_path

        self.edges.append(
            TransformEdge(
                source=source_symbol,
                target=target_symbol,
                transform_symbol=source_symbol,
                transform_kind=transform_kind,
                location=location,
                confidence=max(0.0, min(1.0, confidence)),  # Clamp to [0, 1]
            )
        )

    def add_assignment_transform_edge(
        self,
        source_symbol: str,
        target_symbol: str,
        location: str = "",
        confidence: float = 0.8,
    ) -> None:
        """Create an edge for an assignment transformation.

        Args:
            source_symbol: Source function/expression
            target_symbol: Target variable
            location: Location in source code
            confidence: Confidence score
        """
        self.add_call_edge(
            source_symbol,
            target_symbol,
            transform_kind="assignment_transform",
            location=location,
            confidence=confidence,
        )

    def build(self) -> tuple[list[DataNode], list[TransformEdge]]:
        """Return the built DTG nodes and edges.

        Returns:
            Tuple of (nodes, edges)
        """
        return self.nodes, self.edges

    def verify_integrity(self) -> list[str]:
        """Verify graph integrity constraints.

        Returns:
            List of integrity violation messages (empty if valid)
        """
        violations: list[str] = []

        # Check for self-loops (except allowed cases)
        for edge in self.edges:
            if edge.source == edge.target and edge.transform_kind not in ("parameter",):
                violations.append(
                    f"Self-loop detected: {edge.source} -> {edge.target} "
                    f"(kind={edge.transform_kind})"
                )

        # Check for dangling edges (edges referencing non-existent nodes)
        node_symbols = self._node_symbols
        for edge in self.edges:
            # Note: We allow dangling edges to external symbols (cross-module references)
            # Only check for obvious issues
            if edge.source.startswith(f"{self.module}.") and edge.source not in node_symbols:
                # This is a local symbol that should exist
                pass  # Allow for now - may be external reference

        # Check confidence scores are valid
        for edge in self.edges:
            if not (0.0 <= edge.confidence <= 1.0):
                violations.append(
                    f"Invalid confidence score: {edge.confidence} "
                    f"(must be in [0.0, 1.0])"
                )

        return violations


def _call_name(call: ast.Call) -> str | None:
    """Extract function name from a Call node."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _expr_name(expr: ast.expr) -> str | None:
    """Extract name from an expression (for base classes, etc)."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None
