"""Repository abstraction layer for SIOF DTG operations.

Provides high-level repository management, querying, and analysis capabilities
on top of the Storage backend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Artifact, DataNode, Finding, IntentRecord, TransformEdge
from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LineageResult:
    """Result of a lineage query."""
    symbol: str
    depth: int
    edges: list[dict[str, Any]]
    total_edges: int


@dataclass(slots=True)
class ImpactResult:
    """Result of an impact analysis query."""
    query: str
    impacts: list[dict[str, Any]]
    total_impacts: int


@dataclass(slots=True)
class DeadPathResult:
    """Result of dead path analysis."""
    dead_nodes: list[dict[str, Any]]
    total_dead: int


@dataclass(slots=True)
class IntentResult:
    """Result of intent history query."""
    query: str
    records: list[dict[str, Any]]
    total_records: int


class Repository:
    """High-level repository interface for DTG operations.

    Provides semantic queries, analysis, and management operations
    on top of the underlying Storage backend.
    """

    def __init__(self, db_path: str | Path):
        """Initialize repository with database path.

        Args:
            db_path: Path to SQLite database file
        """
        self.storage = Storage(db_path)
        self.db_path = Path(db_path)
        logger.info(f"Initialized repository at {db_path}")

    def init(self) -> None:
        """Initialize database schema."""
        self.storage.init_schema()
        logger.info("Repository schema initialized")

    def close(self) -> None:
        """Close database connection."""
        self.storage.close()
        logger.info("Repository closed")

    def clear(self) -> None:
        """Clear all index data (artifacts, nodes, edges)."""
        self.storage.clear_index()
        logger.info("Repository index cleared")

    def index_build(
        self,
        artifacts: list[Artifact],
        nodes: list[DataNode],
        edges: list[TransformEdge],
    ) -> dict[str, int]:
        """Build/rebuild the complete index.

        Args:
            artifacts: List of parsed artifacts
            nodes: List of DTG nodes
            edges: List of DTG edges

        Returns:
            Dictionary with counts of indexed items
        """
        self.clear()
        self.storage.upsert_artifacts(artifacts)
        self.storage.replace_nodes_edges(nodes, edges)

        result = {
            "artifacts": len(artifacts),
            "nodes": len(nodes),
            "edges": len(edges),
        }
        logger.info(f"Index build complete: {result}")
        return result

    def find_data_lineage(self, symbol: str, depth: int = 3) -> LineageResult:
        """Find data lineage for a symbol.

        Traces the data flow through transformations that affect a given symbol,
        showing all functions/methods that read from or write to that data.

        Args:
            symbol: Symbol name to trace
            depth: Maximum traversal depth (default: 3)

        Returns:
            LineageResult with edges and metadata
        """
        result = self.storage.query_lineage(symbol, depth)
        edges = result.get("edges", [])

        lineage = LineageResult(
            symbol=symbol,
            depth=depth,
            edges=edges,
            total_edges=len(edges),
        )
        logger.debug(f"Found {len(edges)} lineage edges for {symbol}")
        return lineage

    def impact_of_change(self, file_or_symbol: str) -> ImpactResult:
        """Analyze impact of changing a file or symbol.

        Identifies all downstream symbols and transformations affected by
        a change to the specified file or symbol.

        Args:
            file_or_symbol: File path or symbol name to analyze

        Returns:
            ImpactResult with affected nodes and edges
        """
        result = self.storage.query_impact(file_or_symbol)
        impacts = result.get("impacts", [])

        impact = ImpactResult(
            query=file_or_symbol,
            impacts=impacts,
            total_impacts=len(impacts),
        )
        logger.debug(f"Found {len(impacts)} impacted nodes for {file_or_symbol}")
        return impact

    def validate_relationship(
        self,
        source: str,
        target: str,
        relation: str = "any",
    ) -> bool:
        """Validate if a relationship exists between two symbols.

        Args:
            source: Source symbol
            target: Target symbol
            relation: Relationship type to validate (default: "any")

        Returns:
            True if relationship exists, False otherwise
        """
        result = self.storage.query_lineage(source)
        edges = result.get("edges", [])

        for edge in edges:
            if edge["target"] == target:
                if relation == "any" or edge["transform_kind"] == relation:
                    logger.debug(f"Validated relationship: {source} -> {target}")
                    return True

        logger.debug(f"No relationship found: {source} -> {target}")
        return False

    def get_dead_paths(self) -> DeadPathResult:
        """Identify dead code paths (unused symbols).

        Returns:
            DeadPathResult with unused nodes
        """
        result = self.storage.get_dead_paths()
        dead_nodes = result.get("dead_nodes", [])

        dead_paths = DeadPathResult(
            dead_nodes=dead_nodes,
            total_dead=len(dead_nodes),
        )
        logger.info(f"Found {len(dead_nodes)} dead code paths")
        return dead_paths

    def find_unhandled_exceptions(self, scope: str = "") -> dict[str, Any]:
        """Find unhandled exception patterns in scope.

        Identifies try/except blocks that may be swallowing exceptions
        without proper logging or re-raising.

        Args:
            scope: Scope to search (module, class, or function)

        Returns:
            Dictionary with unhandled exception findings
        """
        # This requires De-Slopper integration (Phase 2)
        # For now, return empty result
        logger.debug(f"Searching for unhandled exceptions in {scope}")
        return {"scope": scope, "findings": []}

    def get_intent_history(self, symbol_or_area: str) -> IntentResult:
        """Get intent history for a symbol or area.

        Retrieves developer intent records and architectural decisions
        related to a specific symbol or code area.

        Args:
            symbol_or_area: Symbol name or code area to query

        Returns:
            IntentResult with historical intent records
        """
        result = self.storage.get_intent_history(symbol_or_area)
        records = result.get("records", [])

        intent = IntentResult(
            query=symbol_or_area,
            records=records,
            total_records=len(records),
        )
        logger.debug(f"Found {len(records)} intent records for {symbol_or_area}")
        return intent

    def get_run_energy(self, run_id: str) -> dict[str, Any]:
        """Get energy metrics for a specific run.

        Args:
            run_id: Run identifier

        Returns:
            Dictionary with energy metrics
        """
        result = self.storage.get_energy_run(run_id)
        logger.debug(f"Retrieved energy metrics for run {run_id}")
        return result

    def add_findings(self, findings: list[Finding]) -> int:
        """Add findings (linting results) to repository.

        Args:
            findings: List of findings to add

        Returns:
            Number of findings added
        """
        self.storage.insert_findings(findings)
        logger.info(f"Added {len(findings)} findings")
        return len(findings)

    def clear_findings(self) -> None:
        """Clear all findings."""
        self.storage.clear_findings()
        logger.info("Findings cleared")

    def add_intent_records(self, records: list[IntentRecord]) -> int:
        """Add intent records to repository.

        Args:
            records: List of intent records to add

        Returns:
            Number of records added
        """
        self.storage.insert_intent_records(records)
        logger.info(f"Added {len(records)} intent records")
        return len(records)

    def get_statistics(self) -> dict[str, Any]:
        """Get repository statistics.

        Returns:
            Dictionary with repository statistics
        """
        conn = self.storage.conn

        artifacts_count = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        nodes_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        findings_count = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        intent_count = conn.execute("SELECT COUNT(*) FROM intent_records").fetchone()[0]

        stats = {
            "artifacts": artifacts_count,
            "nodes": nodes_count,
            "edges": edges_count,
            "findings": findings_count,
            "intent_records": intent_count,
            "db_path": str(self.db_path),
            "db_size_mb": self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0,
        }
        logger.info(f"Repository statistics: {stats}")
        return stats
