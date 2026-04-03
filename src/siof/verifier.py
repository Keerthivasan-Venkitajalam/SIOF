"""Graph integrity verifier for DTG validation and constraint checking."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VerificationResult:
    """Result of graph integrity verification."""
    valid: bool
    total_nodes: int
    total_edges: int
    violations: list[str] = field(default_factory=list)
    dead_nodes: list[dict[str, Any]] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    orphaned_nodes: list[dict[str, Any]] = field(default_factory=list)
    self_loops: list[dict[str, Any]] = field(default_factory=list)
    invalid_confidence: list[dict[str, Any]] = field(default_factory=list)


class GraphVerifier:
    """Verifies DTG integrity and detects anomalies."""

    def __init__(self, storage: Storage):
        """Initialize verifier with storage backend.

        Args:
            storage: Storage backend instance
        """
        self.storage = storage
        logger.info("Initialized graph verifier")

    def verify(self) -> VerificationResult:
        """Perform comprehensive graph integrity verification.

        Checks:
        1. No self-loops (edges where source == target)
        2. Valid confidence bounds [0.0, 1.0]
        3. Dead nodes (no incoming or outgoing edges)
        4. Orphaned nodes (not reachable from any entry point)
        5. Cycles in transformation graph

        Returns:
            VerificationResult with all violations and statistics
        """
        logger.info("Starting graph integrity verification")

        # Fetch all nodes and edges
        nodes = self._fetch_nodes()
        edges = self._fetch_edges()

        violations = []

        # Check 1: Self-loops
        self_loops = self._check_self_loops(edges)
        if self_loops:
            violations.append(f"Found {len(self_loops)} self-loops")

        # Check 2: Invalid confidence bounds
        invalid_confidence = self._check_confidence_bounds(edges)
        if invalid_confidence:
            violations.append(f"Found {len(invalid_confidence)} edges with invalid confidence")

        # Check 3: Dead nodes
        dead_nodes = self._find_dead_nodes(nodes, edges)
        if dead_nodes:
            violations.append(f"Found {len(dead_nodes)} dead nodes")

        # Check 4: Orphaned nodes
        orphaned_nodes = self._find_orphaned_nodes(nodes, edges)
        if orphaned_nodes:
            violations.append(f"Found {len(orphaned_nodes)} orphaned nodes")

        # Check 5: Cycles
        cycles = self._detect_cycles(nodes, edges)
        if cycles:
            violations.append(f"Found {len(cycles)} cycles in transformation graph")

        valid = len(violations) == 0

        result = VerificationResult(
            valid=valid,
            total_nodes=len(nodes),
            total_edges=len(edges),
            violations=violations,
            dead_nodes=dead_nodes,
            cycles=cycles,
            orphaned_nodes=orphaned_nodes,
            self_loops=self_loops,
            invalid_confidence=invalid_confidence,
        )

        logger.info(f"Verification complete: valid={valid}, violations={len(violations)}")
        return result

    def _fetch_nodes(self) -> list[dict[str, Any]]:
        """Fetch all nodes from storage.

        Returns:
            List of node dictionaries
        """
        cur = self.storage.conn.execute(
            "SELECT symbol, module, kind, location FROM nodes"
        )
        return [dict(r) for r in cur.fetchall()]

    def _fetch_edges(self) -> list[dict[str, Any]]:
        """Fetch all edges from storage.

        Returns:
            List of edge dictionaries
        """
        cur = self.storage.conn.execute(
            "SELECT source, target, transform_symbol, transform_kind, location, confidence FROM edges"
        )
        return [dict(r) for r in cur.fetchall()]

    def _check_self_loops(self, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Check for self-loops (edges where source == target).

        Args:
            edges: List of edge dictionaries

        Returns:
            List of self-loop edges
        """
        self_loops = [e for e in edges if e["source"] == e["target"]]
        if self_loops:
            logger.warning(f"Found {len(self_loops)} self-loops")
        return self_loops

    def _check_confidence_bounds(self, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Check for invalid confidence bounds [0.0, 1.0].

        Args:
            edges: List of edge dictionaries

        Returns:
            List of edges with invalid confidence
        """
        invalid = [e for e in edges if not (0.0 <= e["confidence"] <= 1.0)]
        if invalid:
            logger.warning(f"Found {len(invalid)} edges with invalid confidence")
        return invalid

    def _find_dead_nodes(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Find dead nodes (no incoming or outgoing edges).

        Args:
            nodes: List of node dictionaries
            edges: List of edge dictionaries

        Returns:
            List of dead nodes
        """
        {n["symbol"] for n in nodes}
        edge_sources = {e["source"] for e in edges}
        edge_targets = {e["target"] for e in edges}

        dead = [
            n for n in nodes
            if n["symbol"] not in edge_sources and n["symbol"] not in edge_targets
        ]

        if dead:
            logger.info(f"Found {len(dead)} dead nodes")
        return dead

    def _find_orphaned_nodes(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Find orphaned nodes (not reachable from entry points).

        Entry points are nodes with no incoming edges (sources).

        Args:
            nodes: List of node dictionaries
            edges: List of edge dictionaries

        Returns:
            List of orphaned nodes
        """
        node_symbols = {n["symbol"] for n in nodes}
        edge_targets = {e["target"] for e in edges}

        # Entry points: nodes with no incoming edges
        entry_points = node_symbols - edge_targets

        if not entry_points:
            # If no entry points, all nodes are potentially orphaned
            return nodes

        # BFS from entry points to find reachable nodes
        reachable = set()
        queue = list(entry_points)

        while queue:
            current = queue.pop(0)
            if current in reachable:
                continue
            reachable.add(current)

            # Find all targets of current node
            for edge in edges:
                if edge["source"] == current and edge["target"] not in reachable:
                    queue.append(edge["target"])

        # Orphaned nodes are those not reachable from entry points
        orphaned = [n for n in nodes if n["symbol"] not in reachable]

        if orphaned:
            logger.info(f"Found {len(orphaned)} orphaned nodes")
        return orphaned

    def _detect_cycles(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[list[str]]:
        """Detect cycles in transformation graph using DFS.

        Args:
            nodes: List of node dictionaries
            edges: List of edge dictionaries

        Returns:
            List of cycles (each cycle is a list of symbols)
        """
        # Build adjacency list
        graph = {}
        for n in nodes:
            graph[n["symbol"]] = []

        for e in edges:
            if e["source"] in graph and e["target"] in graph:
                graph[e["source"]].append(e["target"])

        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: list[str]) -> None:
            """DFS to detect cycles."""
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path[:])
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = [*path[cycle_start:], neighbor]
                    cycles.append(cycle)

            rec_stack.remove(node)

        # Run DFS from all unvisited nodes
        for node in graph:
            if node not in visited:
                dfs(node, [])

        if cycles:
            logger.warning(f"Found {len(cycles)} cycles in transformation graph")
        return cycles

    def get_statistics(self) -> dict[str, Any]:
        """Get graph statistics.

        Returns:
            Dictionary with graph statistics
        """
        nodes = self._fetch_nodes()
        edges = self._fetch_edges()

        # Calculate statistics
        node_kinds = {}
        for n in nodes:
            kind = n["kind"]
            node_kinds[kind] = node_kinds.get(kind, 0) + 1

        edge_kinds = {}
        for e in edges:
            kind = e["transform_kind"]
            edge_kinds[kind] = edge_kinds.get(kind, 0) + 1

        # Calculate average confidence
        avg_confidence = sum(e["confidence"] for e in edges) / len(edges) if edges else 0.0

        stats = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_kinds": node_kinds,
            "edge_kinds": edge_kinds,
            "avg_confidence": round(avg_confidence, 3),
            "min_confidence": min((e["confidence"] for e in edges), default=0.0),
            "max_confidence": max((e["confidence"] for e in edges), default=0.0),
        }

        logger.info(f"Graph statistics: {stats}")
        return stats
