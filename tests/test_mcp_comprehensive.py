"""Comprehensive tests for the MCP server module."""

from pathlib import Path

import pytest

from siof.indexer import PythonIndexer
from siof.mcp_server import MCPGraphServer, MCPRequest


@pytest.fixture
def indexed_repo(tmp_path: Path):
    """Create a repo with indexed data."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def process(data):\n    return transform(data)\n\ndef transform(x):\n    return x * 2\n"
    )

    db = tmp_path / "siof.db"
    idx = PythonIndexer(repo=repo, db_path=db)
    idx.init()
    idx.build()
    idx.close()

    return db


def test_mcp_find_lineage(indexed_repo: Path):
    """Test find_data_lineage tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="find_data_lineage",
        args={"node_or_symbol": "a.process", "depth": 3},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_impact_of_change(indexed_repo: Path):
    """Test impact_of_change tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="impact_of_change",
        args={"file_or_symbol": "a.py"},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_validate_relationship(indexed_repo: Path):
    """Test validate_relationship tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="validate_relationship",
        args={"source": "a.process", "target": "a.transform", "relation": "any"},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_get_dead_paths(indexed_repo: Path):
    """Test get_dead_paths tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="get_dead_paths",
        args={"scope": ""},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_get_intent_history(indexed_repo: Path):
    """Test get_intent_history tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="get_intent_history",
        args={"symbol_or_area": "a.process"},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_get_run_energy(indexed_repo: Path):
    """Test get_run_energy tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="get_run_energy",
        args={"run_id": "nonexistent"},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_find_unhandled_exceptions(indexed_repo: Path):
    """Test find_unhandled_exceptions tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="find_unhandled_exceptions",
        args={"scope": ""},
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is True
    assert result.result is not None


def test_mcp_unauthorized_access(indexed_repo: Path):
    """Test that unauthorized access is denied."""
    server = MCPGraphServer(db_path=indexed_repo)

    # Try to access a mutating tool without proper role
    req = MCPRequest(
        tool="apply_patch_to_file",
        args={"file_path": "test.py", "patch": "test"},
        role="viewer",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is False
    assert "unauthorized" in result.error


def test_mcp_admin_access(indexed_repo: Path):
    """Test that admin with token can access mutating tools."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="apply_patch_to_file",
        args={},
        role="admin",
        approval_token="valid_token",
    )
    result = server.handle(req)
    server.close()

    # Should not be unauthorized (may fail for other reasons)
    assert "unauthorized" not in (result.error or "")


def test_mcp_missing_args(indexed_repo: Path):
    """Test handling of missing required arguments."""
    server = MCPGraphServer(db_path=indexed_repo)

    req = MCPRequest(
        tool="find_data_lineage",
        args={},  # Missing node_or_symbol
        role="analyst",
    )
    result = server.handle(req)
    server.close()

    assert result.ok is False
    assert result.error is not None


def test_mcp_unknown_tool(indexed_repo: Path):
    """Test handling of unknown tool."""
    server = MCPGraphServer(db_path=indexed_repo)

    # Unknown tools are not in the policy, so they get unauthorized
    req = MCPRequest(
        tool="nonexistent_tool",
        args={},
        role="admin",
    )
    result = server.handle(req)
    server.close()

    # Unknown tools are not authorized (not in READ_ONLY or MUTATING)
    assert result.ok is False


def test_mcp_stdio_protocol(indexed_repo: Path, capsys):
    """Test stdio protocol handling."""
    import json
    import sys
    from io import StringIO

    server = MCPGraphServer(db_path=indexed_repo)

    # Simulate stdin with a request
    old_stdin = sys.stdin
    old_stdout = sys.stdout

    try:
        sys.stdin = StringIO('{"tool":"get_dead_paths","args":{},"role":"analyst"}\nquit\n')
        sys.stdout = StringIO()

        server.serve_stdio()

        output = sys.stdout.getvalue()
        lines = output.strip().split("\n")

        # Should have at least one response
        assert len(lines) >= 1
        response = json.loads(lines[0])
        assert "ok" in response
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        server.close()


def test_mcp_invalid_json(indexed_repo: Path):
    """Test handling of invalid JSON in stdio."""
    import sys
    from io import StringIO

    server = MCPGraphServer(db_path=indexed_repo)

    old_stdin = sys.stdin
    old_stdout = sys.stdout

    try:
        sys.stdin = StringIO("invalid json\nquit\n")
        sys.stdout = StringIO()

        server.serve_stdio()

        output = sys.stdout.getvalue()
        lines = output.strip().split("\n")

        # Should have error response
        assert len(lines) >= 1
        import json

        response = json.loads(lines[0])
        assert response["ok"] is False
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        server.close()
