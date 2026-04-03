from pathlib import Path

from siof.indexer import PythonIndexer
from siof.mcp_server import MCPGraphServer, MCPRequest


def test_mcp_lineage(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(x):\n    return x\n", encoding="utf-8")

    db = tmp_path / "siof.db"
    idx = PythonIndexer(repo=repo, db_path=db)
    idx.init()
    idx.build()
    idx.close()

    server = MCPGraphServer(db)
    res = server.handle(MCPRequest(tool="find_data_lineage", args={"node_or_symbol": "a.f"}, role="analyst"))
    server.close()

    assert res.ok is True
    assert res.result is not None
