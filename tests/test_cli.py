"""Tests for the CLI module."""
from pathlib import Path

from siof.cli import build_parser, main


def test_build_parser():
    """Test parser construction."""
    parser = build_parser()
    assert parser is not None


def test_parser_index_build(tmp_path: Path):
    """Test index build command parsing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "index", "--repo", str(repo), "build"]

    result = main(argv)
    assert result == 0


def test_parser_index_verify(tmp_path: Path):
    """Test index verify command parsing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    db = tmp_path / "siof.db"

    # First build
    main(["--db", str(db), "index", "--repo", str(repo), "build"])

    # Then verify
    argv = ["--db", str(db), "index", "--repo", str(repo), "verify"]
    result = main(argv)
    assert result == 0


def test_parser_slop_audit(tmp_path: Path):
    """Test slop audit command."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "slop", "--repo", str(repo), "audit"]

    result = main(argv)
    assert result == 0


def test_parser_slop_fix(tmp_path: Path):
    """Test slop fix command."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "slop", "--repo", str(repo), "fix"]

    result = main(argv)
    assert result == 0


def test_parser_slop_strict_pass(tmp_path: Path):
    """Test slop strict command with no findings."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "slop", "--repo", str(repo), "strict"]

    result = main(argv)
    assert result == 0


def test_parser_slop_strict_fail(tmp_path: Path):
    """Test slop strict command with findings."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("try:\n    x = 1\nexcept:\n    pass\n")

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "slop", "--repo", str(repo), "strict"]

    # Strict mode should raise an exception which gets caught and returns 1
    try:
        result = main(argv)
        # If it doesn't raise, it should return 1
        assert result == 1
    except RuntimeError:
        # Exception is expected for strict mode with findings
        pass


def test_parser_memex_ingest(tmp_path: Path):
    """Test memex ingest command."""
    repo = tmp_path / "repo"
    repo.mkdir()

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "memex", "--repo", str(repo), "ingest"]

    result = main(argv)
    assert result == 0


def test_parser_memex_query(tmp_path: Path):
    """Test memex query command."""
    repo = tmp_path / "repo"
    repo.mkdir()

    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "memex", "--repo", str(repo), "query", "test"]

    result = main(argv)
    assert result == 0


def test_parser_green_run(tmp_path: Path):
    """Test green run command."""
    db = tmp_path / "siof.db"
    argv = ["--db", str(db), "green", "run", "python", "-c", "print('test')"]

    result = main(argv)
    assert result == 0


def test_parser_green_report(tmp_path: Path):
    """Test green report command."""
    db = tmp_path / "siof.db"

    # First run a command
    main(["--db", str(db), "green", "run", "python", "-c", "print('test')"])

    # Get the run_id from the database
    from siof.storage import Storage
    storage = Storage(db)
    storage.init_schema()
    row = storage.conn.execute("SELECT run_id FROM energy_runs LIMIT 1").fetchone()
    storage.close()

    if row:
        run_id = row[0]
        argv = ["--db", str(db), "green", "report", run_id]
        result = main(argv)
        assert result == 0


def test_parser_default_db_path(tmp_path: Path):
    """Test default database path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(): pass")

    # Change to repo directory
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(repo)
        argv = ["index", "build"]
        result = main(argv)
        assert result == 0
    finally:
        os.chdir(old_cwd)
