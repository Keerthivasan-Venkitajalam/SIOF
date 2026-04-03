"""End-to-end integration tests."""
from pathlib import Path
import json

from siof.indexer import PythonIndexer
from siof.deslopper import DeSlopper
from siof.mcp_server import MCPGraphServer, MCPRequest
from siof.memex import Memex
from siof.green_guard import GreenGuard


def test_e2e_full_workflow(tmp_path: Path):
    """Test complete workflow: index -> slop -> MCP -> memex -> green."""
    # Setup repo
    repo = tmp_path / "repo"
    repo.mkdir()
    
    # Create sample code with some slop
    (repo / "main.py").write_text(
        "def process(data):\n"
        "    try:\n"
        "        return transform(data)\n"
        "    except:\n"
        "        pass\n"
        "\n"
        "def transform(x):\n"
        "    return x * 2\n"
    )
    
    (repo / "utils.py").write_text(
        "# This is a robust solution\n"
        "def helper():\n"
        "    return 42\n"
    )
    
    db = tmp_path / "siof.db"
    
    # Phase 1: Index
    idx = PythonIndexer(repo=repo, db_path=db)
    idx.init()
    index_result = idx.build()
    idx.close()
    
    assert index_result["files"] == 2
    assert index_result["nodes"] > 0
    assert index_result["edges"] > 0
    
    # Phase 2: De-slopper
    d = DeSlopper(repo=repo, db_path=db)
    slop_result = d.run(mode="audit")
    d.close()
    
    assert len(slop_result.findings) > 0
    assert any(f.rule_id == "NakedExceptionPass" for f in slop_result.findings)
    
    # Phase 3: MCP queries
    server = MCPGraphServer(db_path=db)
    
    # Query lineage
    req = MCPRequest(
        tool="find_data_lineage",
        args={"node_or_symbol": "main.process", "depth": 3},
        role="analyst",
    )
    result = server.handle(req)
    assert result.ok is True
    
    # Query dead paths
    req = MCPRequest(
        tool="get_dead_paths",
        args={},
        role="analyst",
    )
    result = server.handle(req)
    assert result.ok is True
    
    server.close()
    
    # Phase 4: Memex
    m = Memex(repo=repo, db_path=db)
    memex_result = m.ingest()
    m.close()
    
    assert "ingested" in memex_result
    
    # Phase 5: Green Guard
    g = GreenGuard(db_path=db)
    green_result = g.run_command(["python", "-c", "print('test')"])
    g.close()
    
    assert green_result["returncode"] == 0
    assert green_result["status"] == "ok"


def test_e2e_deterministic(tmp_path: Path):
    """Test that e2e workflow produces deterministic results."""
    # Setup repo
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("def f(x):\n    return x + 1\n")
    
    # Run 1
    db1 = tmp_path / "siof1.db"
    idx1 = PythonIndexer(repo=repo, db_path=db1)
    idx1.init()
    result1 = idx1.build()
    idx1.close()
    
    # Run 2
    db2 = tmp_path / "siof2.db"
    idx2 = PythonIndexer(repo=repo, db_path=db2)
    idx2.init()
    result2 = idx2.build()
    idx2.close()
    
    # Results should be identical
    assert result1["files"] == result2["files"]
    assert result1["nodes"] == result2["nodes"]
    assert result1["edges"] == result2["edges"]


def test_e2e_error_handling(tmp_path: Path):
    """Test error handling in e2e workflow."""
    repo = tmp_path / "repo"
    repo.mkdir()
    
    # Create file with syntax error
    (repo / "bad.py").write_text("def f(\n    invalid syntax")
    
    db = tmp_path / "siof.db"
    
    # Index should handle parse errors gracefully
    idx = PythonIndexer(repo=repo, db_path=db)
    idx.init()
    result = idx.build()
    idx.close()
    
    assert result["parse_errors"] == 1
    assert result["nodes"] == 0
    
    # De-slopper should also handle it
    d = DeSlopper(repo=repo, db_path=db)
    slop_result = d.run(mode="audit")
    d.close()
    
    assert any(f.rule_id == "ParseError" for f in slop_result.findings)
