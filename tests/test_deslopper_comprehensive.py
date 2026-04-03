"""Comprehensive tests for the deslopper module."""
from pathlib import Path

import pytest

from siof.deslopper import DeSlopper


def test_deslopper_naked_exception(tmp_path: Path):
    """Test detection of bare exception with pass."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bad.py").write_text("try:\n    x = 1\nexcept:\n    pass\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert len(result.findings) > 0
    assert any(f.rule_id == "NakedExceptionPass" for f in result.findings)


def test_deslopper_broad_exception(tmp_path: Path):
    """Test detection of broad exception with pass."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bad.py").write_text("try:\n    x = 1\nexcept Exception:\n    pass\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert len(result.findings) > 0
    assert any(f.rule_id == "BroadExceptionPass" for f in result.findings)


def test_deslopper_hedge_words(tmp_path: Path):
    """Test detection of hedge words in comments."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("# This is a robust solution\nx = 1\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert any(f.rule_id == "HedgeComment" for f in result.findings)


def test_deslopper_echo_comment(tmp_path: Path):
    """Test detection of echo comments."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("# Initialize variable\nx = 1\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert any(f.rule_id == "EchoComment" for f in result.findings)


def test_deslopper_suspicious_import(tmp_path: Path):
    """Test detection of suspicious imports."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("import xxxxxxxxxxxxxxxxxxxxx\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert any(f.rule_id == "SuspiciousImport" for f in result.findings)


def test_deslopper_unused_import(tmp_path: Path):
    """Test detection of unused imports."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("import json\nx = 1\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert any(f.rule_id == "UnusedImport" for f in result.findings)


def test_deslopper_fix_mode(tmp_path: Path):
    """Test fix mode applies autofixes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bad_file = repo / "bad.py"
    bad_file.write_text("try:\n    x = 1\nexcept:\n    pass\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="fix")
    d.close()

    # File should be modified
    content = bad_file.read_text()
    assert "except Exception" in content or "handled error" in content


def test_deslopper_strict_mode_pass(tmp_path: Path):
    """Test strict mode passes with no high-severity findings."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "good.py").write_text("def f():\n    return 42\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="strict")
    d.close()

    # Should not raise


def test_deslopper_strict_mode_fail(tmp_path: Path):
    """Test strict mode fails with high-severity findings."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bad.py").write_text("try:\n    x = 1\nexcept:\n    pass\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    
    with pytest.raises(RuntimeError, match="strict mode failed"):
        d.run(mode="strict")
    d.close()


def test_deslopper_parse_error(tmp_path: Path):
    """Test handling of parse errors."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "bad.py").write_text("def f(\n    invalid syntax")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert any(f.rule_id == "ParseError" for f in result.findings)


def test_deslopper_multiple_files(tmp_path: Path):
    """Test scanning multiple files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("try:\n    x = 1\nexcept:\n    pass\n")
    (repo / "b.py").write_text("# This is robust\ny = 2\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    assert len(result.findings) >= 2


def test_deslopper_no_findings(tmp_path: Path):
    """Test file with no slop."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "good.py").write_text(
        "def process(data):\n    try:\n        return data * 2\n    except ValueError as e:\n        print(f'Error: {e}')\n"
    )

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    result = d.run(mode="audit")
    d.close()

    # Should have minimal or no findings
    high_severity = [f for f in result.findings if f.severity in {"high", "critical"}]
    assert len(high_severity) == 0


def test_deslopper_deterministic(tmp_path: Path):
    """Test that deslopper produces deterministic results."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("try:\n    x = 1\nexcept:\n    pass\n")

    db1 = tmp_path / "siof1.db"
    d1 = DeSlopper(repo=repo, db_path=db1)
    result1 = d1.run(mode="audit")
    d1.close()

    db2 = tmp_path / "siof2.db"
    d2 = DeSlopper(repo=repo, db_path=db2)
    result2 = d2.run(mode="audit")
    d2.close()

    assert len(result1.findings) == len(result2.findings)
    assert result1.files_changed == result2.files_changed


def test_deslopper_autofix_idempotent(tmp_path: Path):
    """Test that autofixes are idempotent."""
    repo = tmp_path / "repo"
    repo.mkdir()
    bad_file = repo / "bad.py"
    bad_file.write_text("try:\n    x = 1\nexcept:\n    pass\n")

    db = tmp_path / "siof.db"
    d = DeSlopper(repo=repo, db_path=db)
    
    # First fix
    result1 = d.run(mode="fix")
    content1 = bad_file.read_text()
    
    # Second fix (should not change)
    result2 = d.run(mode="fix")
    content2 = bad_file.read_text()
    
    d.close()

    assert content1 == content2
