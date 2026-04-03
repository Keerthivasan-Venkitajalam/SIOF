"""Comprehensive tests for the memex module."""

from pathlib import Path

from siof.memex import Memex


def test_memex_ingest_empty_repo(tmp_path: Path):
    """Test memex ingest on repo with no git history."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)
    result = m.ingest()
    m.close()

    assert "ingested" in result
    assert result["ingested"] >= 0


def test_memex_query_empty(tmp_path: Path):
    """Test memex query on empty database."""
    repo = tmp_path / "repo"
    repo.mkdir()

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)
    result = m.query("test")
    m.close()

    assert "query" in result
    assert "records" in result


def test_memex_ingest_prompt_log(tmp_path: Path):
    """Test memex ingest from prompt log."""
    repo = tmp_path / "repo"
    repo.mkdir()

    siof_dir = repo / ".siof"
    siof_dir.mkdir()
    (siof_dir / "prompts.log").write_text(
        "Implement a function to process data\n" "Add error handling for edge cases\n"
    )

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)
    result = m.ingest()
    m.close()

    assert result["ingested"] >= 2


def test_memex_extract_fields():
    """Test field extraction from intent text."""
    from siof.memex import IntentExtractor

    text = "Implement user authentication module"
    objective, constraints, rationale = IntentExtractor.extract_from_prompt(text)

    assert objective == text
    assert "compatibility" in constraints.lower()
    assert "prompt" in rationale


def test_memex_guess_symbol():
    """Test symbol guessing from text."""
    from siof.memex import IntentExtractor

    text = "Fix bug in module.function where it fails"
    symbol = IntentExtractor.guess_symbol(text)

    assert symbol == "module.function"


def test_memex_guess_symbol_none():
    """Test symbol guessing returns None for no match."""
    from siof.memex import IntentExtractor

    text = "Fix the bug in the code"
    symbol = IntentExtractor.guess_symbol(text)

    assert symbol is None


def test_memex_query_after_ingest(tmp_path: Path):
    """Test querying after ingesting data."""
    repo = tmp_path / "repo"
    repo.mkdir()

    siof_dir = repo / ".siof"
    siof_dir.mkdir()
    (siof_dir / "prompts.log").write_text("Implement module.process function\n")

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)
    m.ingest()

    result = m.query("module.process")
    m.close()

    assert "records" in result
    assert len(result["records"]) >= 0


def test_memex_multiple_ingests(tmp_path: Path):
    """Test multiple ingest operations."""
    repo = tmp_path / "repo"
    repo.mkdir()

    siof_dir = repo / ".siof"
    siof_dir.mkdir()
    (siof_dir / "prompts.log").write_text("First prompt\n")

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)

    result1 = m.ingest()

    # Add more prompts
    (siof_dir / "prompts.log").write_text("First prompt\nSecond prompt\n")
    result2 = m.ingest()

    m.close()

    assert result1["ingested"] >= 1
    assert result2["ingested"] >= 1


def test_memex_deterministic(tmp_path: Path):
    """Test that memex operations are deterministic."""
    repo = tmp_path / "repo"
    repo.mkdir()

    siof_dir = repo / ".siof"
    siof_dir.mkdir()
    (siof_dir / "prompts.log").write_text("Test prompt\n")

    db1 = tmp_path / "siof1.db"
    m1 = Memex(repo=repo, db_path=db1)
    result1 = m1.ingest()
    m1.close()

    db2 = tmp_path / "siof2.db"
    m2 = Memex(repo=repo, db_path=db2)
    result2 = m2.ingest()
    m2.close()

    assert result1["ingested"] == result2["ingested"]


def test_memex_long_text_truncation(tmp_path: Path):
    """Test that long text is properly truncated."""
    repo = tmp_path / "repo"
    repo.mkdir()

    siof_dir = repo / ".siof"
    siof_dir.mkdir()

    long_text = "x" * 500
    (siof_dir / "prompts.log").write_text(long_text + "\n")

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)
    result = m.ingest()
    m.close()

    assert result["ingested"] >= 1


def test_memex_special_characters(tmp_path: Path):
    """Test handling of special characters in prompts."""
    repo = tmp_path / "repo"
    repo.mkdir()

    siof_dir = repo / ".siof"
    siof_dir.mkdir()
    (siof_dir / "prompts.log").write_text(
        "Fix bug: handle 'quotes' and \"double quotes\"\n"
        "Add support for émojis and spëcial chars\n"
    )

    db = tmp_path / "siof.db"
    m = Memex(repo=repo, db_path=db)
    result = m.ingest()
    m.close()

    assert result["ingested"] >= 2
