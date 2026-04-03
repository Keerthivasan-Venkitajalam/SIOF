from pathlib import Path

from siof.deslopper import DeSlopper


def test_deslopper_detects_naked_exception(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    f = repo / "bad.py"
    f.write_text(
        "def g():\n    try:\n        return 1\n    except:\n        pass\n", encoding="utf-8"
    )

    d = DeSlopper(repo=repo, db_path=tmp_path / "siof.db")
    result = d.run(mode="audit")
    d.close()

    assert any(x.rule_id == "NakedExceptionPass" for x in result.findings)


def test_deslopper_fix_mode(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    f = repo / "bad.py"
    f.write_text(
        "def g():\n    try:\n        return 1\n    except:\n        pass\n", encoding="utf-8"
    )

    d = DeSlopper(repo=repo, db_path=tmp_path / "siof.db")
    result = d.run(mode="fix")
    d.close()

    assert result.files_changed == 1
    assert "except Exception as exc" in f.read_text(encoding="utf-8")
