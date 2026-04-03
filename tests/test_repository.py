"""Tests for Repository abstraction layer."""

from pathlib import Path

from siof.models import Artifact, DataNode, Finding, IntentRecord, TransformEdge
from siof.repository import Repository


class TestRepository:
    """Tests for Repository class."""

    def test_repository_initialization(self, tmp_path: Path):
        """Test repository initialization."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        assert db_path.exists()
        stats = repo.get_statistics()
        assert stats["artifacts"] == 0
        assert stats["nodes"] == 0
        assert stats["edges"] == 0

        repo.close()

    def test_index_build(self, tmp_path: Path):
        """Test building an index."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        artifacts = [
            Artifact(path="test.py", hash="abc123", parse_ok=True),
        ]
        nodes = [
            DataNode(symbol="test.func", module="test", kind="function", location="test.py:1"),
            DataNode(symbol="test.Class", module="test", kind="class", location="test.py:5"),
        ]
        edges = [
            TransformEdge(
                source="test.func",
                target="test.Class",
                transform_symbol="test.func",
                transform_kind="call",
                location="test.py:10",
                confidence=0.9,
            ),
        ]

        result = repo.index_build(artifacts, nodes, edges)

        assert result["artifacts"] == 1
        assert result["nodes"] == 2
        assert result["edges"] == 1

        stats = repo.get_statistics()
        assert stats["artifacts"] == 1
        assert stats["nodes"] == 2
        assert stats["edges"] == 1

        repo.close()

    def test_find_data_lineage(self, tmp_path: Path):
        """Test finding data lineage."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        nodes = [
            DataNode(symbol="test.input", module="test", kind="variable", location="test.py:1"),
            DataNode(symbol="test.process", module="test", kind="function", location="test.py:5"),
            DataNode(symbol="test.output", module="test", kind="variable", location="test.py:10"),
        ]
        edges = [
            TransformEdge(
                source="test.input",
                target="test.process",
                transform_symbol="test.process",
                transform_kind="parameter",
                location="test.py:5",
                confidence=1.0,
            ),
            TransformEdge(
                source="test.process",
                target="test.output",
                transform_symbol="test.process",
                transform_kind="assignment_transform",
                location="test.py:10",
                confidence=0.9,
            ),
        ]

        repo.index_build([], nodes, edges)

        lineage = repo.find_data_lineage("test.process")

        assert lineage.symbol == "test.process"
        assert lineage.total_edges == 2
        assert len(lineage.edges) == 2

        repo.close()

    def test_impact_of_change(self, tmp_path: Path):
        """Test impact analysis."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        nodes = [
            DataNode(symbol="test.base", module="test", kind="class", location="test.py:1"),
            DataNode(symbol="test.derived", module="test", kind="class", location="test.py:10"),
        ]
        edges = [
            TransformEdge(
                source="test.base",
                target="test.derived",
                transform_symbol="inherits",
                transform_kind="inheritance",
                location="test.py:10",
                confidence=1.0,
            ),
        ]

        repo.index_build([], nodes, edges)

        impact = repo.impact_of_change("test.base")

        assert impact.query == "test.base"
        assert impact.total_impacts >= 1

        repo.close()

    def test_validate_relationship(self, tmp_path: Path):
        """Test relationship validation."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        nodes = [
            DataNode(symbol="test.a", module="test", kind="function", location="test.py:1"),
            DataNode(symbol="test.b", module="test", kind="function", location="test.py:5"),
        ]
        edges = [
            TransformEdge(
                source="test.a",
                target="test.b",
                transform_symbol="test.a",
                transform_kind="call",
                location="test.py:10",
                confidence=0.9,
            ),
        ]

        repo.index_build([], nodes, edges)

        # Valid relationship
        assert repo.validate_relationship("test.a", "test.b") is True
        assert repo.validate_relationship("test.a", "test.b", "call") is True

        # Invalid relationship
        assert repo.validate_relationship("test.b", "test.a") is False
        assert repo.validate_relationship("test.a", "test.b", "inheritance") is False

        repo.close()

    def test_get_dead_paths(self, tmp_path: Path):
        """Test dead path detection."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        nodes = [
            DataNode(symbol="test.used", module="test", kind="function", location="test.py:1"),
            DataNode(symbol="test.unused", module="test", kind="function", location="test.py:5"),
        ]
        edges = [
            TransformEdge(
                source="test.used",
                target="test.used",
                transform_symbol="test.used",
                transform_kind="call",
                location="test.py:10",
                confidence=0.9,
            ),
        ]

        repo.index_build([], nodes, edges)

        dead_paths = repo.get_dead_paths()

        assert dead_paths.total_dead >= 1
        # test.unused should be in dead paths
        dead_symbols = [d["symbol"] for d in dead_paths.dead_nodes]
        assert "test.unused" in dead_symbols

        repo.close()

    def test_get_intent_history(self, tmp_path: Path):
        """Test intent history retrieval."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        records = [
            IntentRecord(
                source="developer@example.com",
                objective="Implement user authentication",
                constraints="Must support OAuth2",
                rationale="Industry standard for secure auth",
                linked_symbol="auth.oauth2_handler",
            ),
            IntentRecord(
                source="developer@example.com",
                objective="Add caching layer",
                constraints="Redis backend",
                rationale="Improve performance",
                linked_symbol="cache.redis_cache",
            ),
        ]

        repo.add_intent_records(records)

        history = repo.get_intent_history("auth.oauth2_handler")

        assert history.total_records >= 1
        assert any(r["linked_symbol"] == "auth.oauth2_handler" for r in history.records)

        repo.close()

    def test_add_findings(self, tmp_path: Path):
        """Test adding findings."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        findings = [
            Finding(
                rule_id="naked_exception",
                severity="high",
                file_path="test.py",
                line=10,
                message="Bare except clause swallows exceptions",
                autofix_applied=False,
            ),
            Finding(
                rule_id="echo_comment",
                severity="low",
                file_path="test.py",
                line=20,
                message="Comment merely restates code",
                autofix_applied=False,
            ),
        ]

        count = repo.add_findings(findings)

        assert count == 2

        stats = repo.get_statistics()
        assert stats["findings"] == 2

        repo.close()

    def test_clear_findings(self, tmp_path: Path):
        """Test clearing findings."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        findings = [
            Finding(
                rule_id="test_rule",
                severity="low",
                file_path="test.py",
                line=1,
                message="Test finding",
                autofix_applied=False,
            ),
        ]

        repo.add_findings(findings)
        stats = repo.get_statistics()
        assert stats["findings"] == 1

        repo.clear_findings()
        stats = repo.get_statistics()
        assert stats["findings"] == 0

        repo.close()

    def test_repository_statistics(self, tmp_path: Path):
        """Test repository statistics."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        artifacts = [
            Artifact(path="test.py", hash="abc123", parse_ok=True),
        ]
        nodes = [
            DataNode(symbol="test.func", module="test", kind="function", location="test.py:1"),
        ]
        edges = []

        repo.index_build(artifacts, nodes, edges)

        stats = repo.get_statistics()

        assert "artifacts" in stats
        assert "nodes" in stats
        assert "edges" in stats
        assert "findings" in stats
        assert "intent_records" in stats
        assert "db_path" in stats
        assert "db_size_mb" in stats

        assert stats["artifacts"] == 1
        assert stats["nodes"] == 1
        assert stats["edges"] == 0

        repo.close()

    def test_repository_clear(self, tmp_path: Path):
        """Test clearing repository."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        artifacts = [
            Artifact(path="test.py", hash="abc123", parse_ok=True),
        ]
        nodes = [
            DataNode(symbol="test.func", module="test", kind="function", location="test.py:1"),
        ]
        edges = []

        repo.index_build(artifacts, nodes, edges)
        stats = repo.get_statistics()
        assert stats["artifacts"] == 1

        repo.clear()
        stats = repo.get_statistics()
        assert stats["artifacts"] == 0
        assert stats["nodes"] == 0
        assert stats["edges"] == 0

        repo.close()

    def test_multiple_operations(self, tmp_path: Path):
        """Test multiple repository operations in sequence."""
        db_path = tmp_path / "test.db"
        repo = Repository(db_path)
        repo.init()

        # Build index
        artifacts = [
            Artifact(path="module1.py", hash="hash1", parse_ok=True),
            Artifact(path="module2.py", hash="hash2", parse_ok=True),
        ]
        nodes = [
            DataNode(
                symbol="mod1.func1", module="module1", kind="function", location="module1.py:1"
            ),
            DataNode(
                symbol="mod1.func2", module="module1", kind="function", location="module1.py:10"
            ),
            DataNode(
                symbol="mod2.func3", module="module2", kind="function", location="module2.py:1"
            ),
        ]
        edges = [
            TransformEdge(
                source="mod1.func1",
                target="mod1.func2",
                transform_symbol="mod1.func1",
                transform_kind="call",
                location="module1.py:15",
                confidence=0.9,
            ),
            TransformEdge(
                source="mod1.func2",
                target="mod2.func3",
                transform_symbol="mod1.func2",
                transform_kind="call",
                location="module1.py:20",
                confidence=0.85,
            ),
        ]

        repo.index_build(artifacts, nodes, edges)

        # Query lineage
        lineage = repo.find_data_lineage("mod1.func1")
        assert lineage.total_edges >= 1

        # Analyze impact
        impact = repo.impact_of_change("mod1.func1")
        assert impact.total_impacts >= 1

        # Add findings
        findings = [
            Finding(
                rule_id="test",
                severity="low",
                file_path="module1.py",
                line=1,
                message="Test",
                autofix_applied=False,
            ),
        ]
        repo.add_findings(findings)

        # Get statistics
        stats = repo.get_statistics()
        assert stats["artifacts"] == 2
        assert stats["nodes"] == 3
        assert stats["edges"] == 2
        assert stats["findings"] == 1

        repo.close()
