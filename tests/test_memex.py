from pathlib import Path

from siof.memex import Memex


def test_memex_prompt_ingest(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    siof_dir = repo / ".siof"
    siof_dir.mkdir()
    (siof_dir / "prompts.log").write_text("improve parser reliability\n", encoding="utf-8")

    m = Memex(repo=repo, db_path=tmp_path / "siof.db")
    out = m.ingest()
    q = m.query("parser")
    m.close()

    assert out["ingested"] >= 1
    assert len(q["records"]) >= 1
