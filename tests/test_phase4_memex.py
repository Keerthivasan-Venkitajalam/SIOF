"""Comprehensive tests for Phase 4: Memex Intent Layer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from siof.memex import IntentExtractor, IntentScore, Memex
from siof.models import IntentRecord


class TestIntentExtractor:
    """Test intent extraction from various sources."""

    def test_extract_from_commit_simple(self) -> None:
        """Test extracting intent from simple commit message."""
        message = "Add user authentication module"
        objective, constraints, rationale = IntentExtractor.extract_from_commit(message)

        assert objective == "Add user authentication module"
        assert "compatibility" in constraints
        assert "commit" in rationale

    def test_extract_from_commit_multiline(self) -> None:
        """Test extracting intent from multiline commit message."""
        message = "Add user authentication\n\nConstraint: must support OAuth2\nReason: enterprise requirement"
        objective, constraints, rationale = IntentExtractor.extract_from_commit(message)

        assert "Add user authentication" in objective
        assert "constraint" in constraints.lower() or "compatibility" in constraints

    def test_extract_from_pr_simple(self) -> None:
        """Test extracting intent from PR."""
        title = "Implement caching layer"
        description = "Adds Redis-based caching for performance"
        objective, constraints, rationale = IntentExtractor.extract_from_pr(title, description)

        assert objective == "Implement caching layer"
        assert "compatibility" in constraints
        assert "PR" in rationale

    def test_extract_from_prompt(self) -> None:
        """Test extracting intent from prompt."""
        prompt = "Refactor database queries for performance"
        objective, constraints, rationale = IntentExtractor.extract_from_prompt(prompt)

        assert objective == "Refactor database queries for performance"
        assert "compatibility" in constraints
        assert "prompt" in rationale

    def test_guess_symbol_valid(self) -> None:
        """Test guessing symbol from text."""
        text = "Updated module.function to handle edge cases"
        symbol = IntentExtractor.guess_symbol(text)

        assert symbol == "module.function"

    def test_guess_symbol_multiple(self) -> None:
        """Test guessing symbol with multiple matches."""
        text = "Link auth.login to user.create"
        symbol = IntentExtractor.guess_symbol(text)

        # Should return first match
        assert symbol == "auth.login"

    def test_guess_symbol_none(self) -> None:
        """Test guessing symbol when none present."""
        text = "General refactoring and cleanup"
        symbol = IntentExtractor.guess_symbol(text)

        assert symbol is None


class TestMemex:
    """Test Memex intent layer."""

    @pytest.fixture
    def memex_repo(self) -> Path:
        """Create test repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            yield repo

    @pytest.fixture
    def memex(self, memex_repo: Path) -> Memex:
        """Create Memex instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            memex = Memex(memex_repo, db_path)
            yield memex
            memex.close()

    def test_memex_initialization(self, memex: Memex) -> None:
        """Test Memex initialization."""
        assert memex.repo is not None
        assert memex.db is not None
        assert memex.extractor is not None

    def test_ingest_empty_repo(self, memex: Memex) -> None:
        """Test ingesting from empty repository."""
        result = memex.ingest()

        assert "ingested" in result
        assert result["ingested"] == 0

    def test_ingest_with_prompts(self, memex_repo: Path) -> None:
        """Test ingesting from prompt log."""
        # Create prompt log
        siof_dir = memex_repo / ".siof"
        siof_dir.mkdir()
        prompt_log = siof_dir / "prompts.log"
        prompt_log.write_text("Add authentication\nImplement caching\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            memex = Memex(memex_repo, db_path)
            result = memex.ingest()
            memex.close()

        assert result["ingested"] == 2
        assert result["prompts"] == 2

    def test_ingest_with_prs(self, memex_repo: Path) -> None:
        """Test ingesting from PR descriptions."""
        # Create PR files
        siof_dir = memex_repo / ".siof"
        siof_dir.mkdir()
        pr_dir = siof_dir / "prs"
        pr_dir.mkdir()

        (pr_dir / "pr_1.md").write_text("Add authentication\nImplements OAuth2 support")
        (pr_dir / "pr_2.md").write_text("Implement caching\nAdds Redis layer")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            memex = Memex(memex_repo, db_path)
            result = memex.ingest()
            memex.close()

        assert result["ingested"] == 2
        assert result["prs"] == 2

    def test_query_intent(self, memex: Memex) -> None:
        """Test querying intent history."""
        result = memex.query("auth.login")

        assert isinstance(result, dict)
        assert "records" in result or "query" in result

    def test_score_relevance_exact_match(self, memex: Memex) -> None:
        """Test scoring with exact symbol match."""
        records = [
            IntentRecord(
                source="git_commit",
                objective="Add authentication",
                constraints="maintain compatibility",
                rationale="enterprise requirement",
                linked_symbol="auth.login",
            ),
            IntentRecord(
                source="prompt_log",
                objective="Implement caching",
                constraints="maintain compatibility",
                rationale="performance improvement",
                linked_symbol="cache.redis",
            ),
        ]

        scores = memex.score_relevance("auth.login", records)

        assert len(scores) > 0
        assert scores[0].relevance == 1.0
        assert scores[0].symbol == "auth.login"

    def test_score_relevance_partial_match(self, memex: Memex) -> None:
        """Test scoring with partial symbol match."""
        records = [
            IntentRecord(
                source="git_commit",
                objective="Add authentication",
                constraints="maintain compatibility",
                rationale="enterprise requirement",
                linked_symbol="auth.login",
            ),
        ]

        scores = memex.score_relevance("auth", records)

        assert len(scores) > 0
        assert scores[0].relevance == 0.7

    def test_score_relevance_objective_match(self, memex: Memex) -> None:
        """Test scoring with objective match."""
        records = [
            IntentRecord(
                source="git_commit",
                objective="Add authentication module",
                constraints="maintain compatibility",
                rationale="enterprise requirement",
                linked_symbol=None,
            ),
        ]

        scores = memex.score_relevance("authentication", records)

        assert len(scores) > 0
        assert scores[0].relevance == 0.5

    def test_score_relevance_no_match(self, memex: Memex) -> None:
        """Test scoring with no match."""
        records = [
            IntentRecord(
                source="git_commit",
                objective="Add authentication",
                constraints="maintain compatibility",
                rationale="enterprise requirement",
                linked_symbol="auth.login",
            ),
        ]

        scores = memex.score_relevance("database", records)

        assert len(scores) == 0

    def test_score_relevance_sorting(self, memex: Memex) -> None:
        """Test that scores are sorted by relevance."""
        records = [
            IntentRecord(
                source="git_commit",
                objective="Add authentication",
                constraints="maintain compatibility",
                rationale="enterprise requirement",
                linked_symbol="auth.login",
            ),
            IntentRecord(
                source="prompt_log",
                objective="Implement authentication",
                constraints="maintain compatibility",
                rationale="security improvement",
                linked_symbol=None,
            ),
            IntentRecord(
                source="pr",
                objective="Refactor auth module",
                constraints="maintain compatibility",
                rationale="code quality",
                linked_symbol="auth",
            ),
        ]

        scores = memex.score_relevance("auth.login", records)

        # Should have at least one match
        assert len(scores) > 0
        # Should be sorted by relevance descending
        for i in range(len(scores) - 1):
            assert scores[i].relevance >= scores[i + 1].relevance


class TestMemexIntegration:
    """Integration tests for Memex."""

    def test_full_memex_workflow(self) -> None:
        """Test complete Memex workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()

            # Create prompt log
            siof_dir = repo / ".siof"
            siof_dir.mkdir()
            (siof_dir / "prompts.log").write_text("Add auth.login\nImplement cache.redis\n")

            db_path = Path(tmpdir) / "test.db"
            memex = Memex(repo, db_path)

            # Ingest
            result = memex.ingest()
            assert result["ingested"] == 2

            # Query
            query_result = memex.query("auth.login")
            assert query_result is not None

            memex.close()

    def test_memex_with_multiple_sources(self) -> None:
        """Test Memex with multiple intent sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()

            # Create multiple sources
            siof_dir = repo / ".siof"
            siof_dir.mkdir()
            (siof_dir / "prompts.log").write_text("Add authentication\n")

            pr_dir = siof_dir / "prs"
            pr_dir.mkdir()
            (pr_dir / "pr_1.md").write_text("Implement caching\n")

            db_path = Path(tmpdir) / "test.db"
            memex = Memex(repo, db_path)

            result = memex.ingest()
            assert result["ingested"] == 2
            assert result["prompts"] == 1
            assert result["prs"] == 1

            memex.close()
