"""Tests for graph integrity verifier."""

from pathlib import Path

import pytest

from siof.models import DataNode, TransformEdge
from siof.storage import Storage
from siof.verifier import GraphVerifier


class TestGraphVerifier:
    """Tests for GraphVerifier class."""

    def test_verifier_initialization(self, tmp_path: Path):
        """Test verifier initialization."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        verifier = GraphVerifier(storage)
        assert verifier.storage is storage

        storage.close()

    def test_verify_empty_graph(self, tmp_path: Path):
        """Test verification of empty graph."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is True
        assert result.total_nodes == 0
        assert result.total_edges == 0
        assert len(result.violations) == 0

        storage.close()

    def test_verify_valid_graph(self, tmp_path: Path):
        """Test verification of valid graph."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.g", module="a", kind="function", location="a.py:5"),
            DataNode(symbol="b.h", module="b", kind="function", location="b.py:1"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.g",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:10",
                confidence=0.9,
            ),
            TransformEdge(
                source="a.g",
                target="b.h",
                transform_symbol="a.g",
                transform_kind="call",
                location="a.py:15",
                confidence=0.85,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is True
        assert result.total_nodes == 3
        assert result.total_edges == 2
        assert len(result.violations) == 0

        storage.close()

    def test_detect_self_loops(self, tmp_path: Path):
        """Test detection of self-loops."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.f",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:10",
                confidence=0.9,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is False
        assert len(result.self_loops) == 1
        assert "self-loops" in result.violations[0]

        storage.close()

    def test_detect_invalid_confidence(self, tmp_path: Path):
        """Test detection of invalid confidence bounds."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.g", module="a", kind="function", location="a.py:5"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.g",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:10",
                confidence=1.5,  # Invalid: > 1.0
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is False
        assert len(result.invalid_confidence) == 1
        assert "invalid confidence" in result.violations[0]

        storage.close()

    def test_find_dead_nodes(self, tmp_path: Path):
        """Test detection of dead nodes."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.g", module="a", kind="function", location="a.py:5"),
            DataNode(symbol="a.unused", module="a", kind="function", location="a.py:10"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.g",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:15",
                confidence=0.9,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is False
        assert len(result.dead_nodes) == 1
        assert result.dead_nodes[0]["symbol"] == "a.unused"
        assert "dead nodes" in result.violations[0]

        storage.close()

    def test_find_orphaned_nodes(self, tmp_path: Path):
        """Test detection of orphaned nodes (disconnected components)."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.g", module="a", kind="function", location="a.py:5"),
            DataNode(symbol="b.h", module="b", kind="function", location="b.py:1"),
            DataNode(symbol="b.i", module="b", kind="function", location="b.py:5"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.g",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:10",
                confidence=0.9,
            ),
            # b.h and b.i form a separate component not reachable from a.f
            TransformEdge(
                source="b.h",
                target="b.i",
                transform_symbol="b.h",
                transform_kind="call",
                location="b.py:10",
                confidence=0.9,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        # Both components are valid (no violations)
        # b.h and b.i form their own entry point
        assert result.valid is True
        assert len(result.orphaned_nodes) == 0

        storage.close()

    def test_detect_cycles(self, tmp_path: Path):
        """Test detection of cycles."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.g", module="a", kind="function", location="a.py:5"),
            DataNode(symbol="a.h", module="a", kind="function", location="a.py:10"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.g",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:15",
                confidence=0.9,
            ),
            TransformEdge(
                source="a.g",
                target="a.h",
                transform_symbol="a.g",
                transform_kind="call",
                location="a.py:20",
                confidence=0.9,
            ),
            TransformEdge(
                source="a.h",
                target="a.f",
                transform_symbol="a.h",
                transform_kind="call",
                location="a.py:25",
                confidence=0.9,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is False
        assert len(result.cycles) >= 1
        # Check that cycles are detected (may also have orphaned nodes)
        assert any("cycles" in v for v in result.violations)

        storage.close()

    def test_get_statistics(self, tmp_path: Path):
        """Test graph statistics."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.C", module="a", kind="class", location="a.py:5"),
            DataNode(symbol="a.g", module="a", kind="function", location="a.py:10"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.C",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:15",
                confidence=0.9,
            ),
            TransformEdge(
                source="a.C",
                target="a.g",
                transform_symbol="a.C",
                transform_kind="inheritance",
                location="a.py:20",
                confidence=1.0,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        stats = verifier.get_statistics()

        assert stats["total_nodes"] == 3
        assert stats["total_edges"] == 2
        assert stats["node_kinds"]["function"] == 2
        assert stats["node_kinds"]["class"] == 1
        assert stats["edge_kinds"]["call"] == 1
        assert stats["edge_kinds"]["inheritance"] == 1
        assert stats["avg_confidence"] == 0.95
        assert stats["min_confidence"] == 0.9
        assert stats["max_confidence"] == 1.0

        storage.close()

    def test_multiple_violations(self, tmp_path: Path):
        """Test detection of multiple violations."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        nodes = [
            DataNode(symbol="a.f", module="a", kind="function", location="a.py:1"),
            DataNode(symbol="a.unused", module="a", kind="function", location="a.py:5"),
        ]
        edges = [
            TransformEdge(
                source="a.f",
                target="a.f",
                transform_symbol="a.f",
                transform_kind="call",
                location="a.py:10",
                confidence=1.5,  # Invalid confidence
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is False
        assert len(result.violations) >= 2
        assert len(result.self_loops) == 1
        assert len(result.invalid_confidence) == 1
        assert len(result.dead_nodes) == 1

        storage.close()

    def test_complex_graph_verification(self, tmp_path: Path):
        """Test verification of complex graph."""
        db_path = tmp_path / "test.db"
        storage = Storage(db_path)
        storage.init_schema()

        # Create a more complex graph
        nodes = [
            DataNode(symbol="main.run", module="main", kind="function", location="main.py:1"),
            DataNode(symbol="lib.process", module="lib", kind="function", location="lib.py:1"),
            DataNode(symbol="lib.validate", module="lib", kind="function", location="lib.py:10"),
            DataNode(symbol="util.log", module="util", kind="function", location="util.py:1"),
            DataNode(symbol="util.error", module="util", kind="function", location="util.py:5"),
        ]
        edges = [
            TransformEdge(
                source="main.run",
                target="lib.process",
                transform_symbol="main.run",
                transform_kind="call",
                location="main.py:5",
                confidence=0.95,
            ),
            TransformEdge(
                source="lib.process",
                target="lib.validate",
                transform_symbol="lib.process",
                transform_kind="call",
                location="lib.py:5",
                confidence=0.9,
            ),
            TransformEdge(
                source="lib.validate",
                target="util.log",
                transform_symbol="lib.validate",
                transform_kind="call",
                location="lib.py:15",
                confidence=0.85,
            ),
            TransformEdge(
                source="lib.process",
                target="util.error",
                transform_symbol="lib.process",
                transform_kind="call",
                location="lib.py:20",
                confidence=0.8,
            ),
        ]

        storage.replace_nodes_edges(nodes, edges)

        verifier = GraphVerifier(storage)
        result = verifier.verify()

        assert result.valid is True
        assert result.total_nodes == 5
        assert result.total_edges == 4
        assert len(result.violations) == 0

        stats = verifier.get_statistics()
        assert stats["total_nodes"] == 5
        assert stats["total_edges"] == 4
        assert stats["avg_confidence"] == 0.875

        storage.close()
