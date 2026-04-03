# SIOF End-to-End Workflow Guide

This guide demonstrates how to use SIOF's complete workflow to analyze, maintain, and improve your Python codebase.

## Overview

SIOF provides five integrated phases that work together:

1. **DTG Indexer** - Parse and index your codebase as a data transformation graph
2. **De-Slopper** - Detect and fix AI-generated code anti-patterns
3. **MCP Server** - Expose graph queries to LLM agents
4. **Memex** - Extract and preserve developer intent
5. **Green Guard** - Track energy consumption and sustainability

## Quick Start

### Using the Orchestrator (Recommended)

The orchestrator runs all phases in a single command:

```python
from siof.orchestrator import SIOFOrchestrator

# Initialize
orch = SIOFOrchestrator(repo=".", db_path="siof.db")

# Run complete pipeline
result = orch.run_full_pipeline(
    index_mode="build",      # or "update" for incremental
    slop_mode="audit",       # or "fix" or "strict"
    enable_memex=True,       # Extract developer intent
    enable_green_guard=True, # Track energy
)

# Check results
if result.success:
    print(f"✅ Pipeline completed in {result.total_duration_s:.2f}s")
    print(f"Files indexed: {result.phase_results['phase1_index']['files']}")
    print(f"Slop findings: {result.phase_results['phase2_slop']['findings']}")
else:
    print(f"❌ Pipeline failed: {result.error}")
```

### Using Individual Components

For more control, use each component separately:

```python
from pathlib import Path
from siof.indexer import PythonIndexer
from siof.deslopper import DeSlopper
from siof.mcp_server import MCPGraphServer, MCPRequest
from siof.memex import Memex
from siof.green_guard import GreenGuard

repo = Path(".")
db = Path("siof.db")

# Phase 1: Index
indexer = PythonIndexer(repo=repo, db_path=db)
indexer.init()
index_result = indexer.build()
indexer.close()

# Phase 2: De-Slop
deslopper = DeSlopper(repo=repo, db_path=db)
slop_result = deslopper.run(mode="audit")
deslopper.close()

# Phase 3: MCP Queries
server = MCPGraphServer(db_path=db)
request = MCPRequest(
    tool="find_data_lineage",
    args={"node_or_symbol": "mymodule.myfunction", "depth": 3},
    role="analyst",
)
response = server.handle(request)
server.close()

# Phase 4: Memex
memex = Memex(repo=repo, db_path=db)
memex_result = memex.ingest()
memex.close()

# Phase 5: Green Guard
guard = GreenGuard(db_path=db)
green_result = guard.run_command(["pytest", "tests/"])
guard.close()
```

## CLI Usage

### Index Your Repository

```bash
# Build fresh index
siof index build --repo /path/to/repo

# Incremental update
siof index update --repo /path/to/repo
```

### Detect AI Slop

```bash
# Audit only (no changes)
siof slop audit --repo /path/to/repo

# Auto-fix issues
siof slop fix --repo /path/to/repo

# Strict mode (fail on any slop)
siof slop fix --repo /path/to/repo --strict
```

### Start MCP Server

```bash
# Start server for LLM agents
siof mcp serve --db siof.db

# Query from another terminal
siof mcp query find_data_lineage mymodule.myfunction
```

### Extract Developer Intent

```bash
# Ingest from git history
siof memex ingest --repo /path/to/repo

# Query intent
siof memex query --symbol myfunction
```

### Track Energy

```bash
# Run command with energy tracking
siof green run pytest tests/

# Set hard CO2 limit
siof green run --hard-co2 0.1 pytest tests/

# View sustainability report
siof green report
```

## Real-World Example

Let's analyze a real project:

```bash
# Clone a project
git clone https://github.com/example/project.git
cd project

# Run SIOF analysis
python -m examples.e2e_workflow .

# Review findings
sqlite3 siof.db "SELECT rule_id, COUNT(*) FROM findings GROUP BY rule_id;"

# Fix AI slop
siof slop fix --repo .

# Start MCP server for AI agents
siof mcp serve --db siof.db
```

## Integration with AI Agents

SIOF's MCP server exposes your codebase to LLM agents:

```python
from siof.mcp_server import MCPGraphServer, MCPRequest

server = MCPGraphServer("siof.db")

# Agent queries data lineage
request = MCPRequest(
    tool="find_data_lineage",
    args={"node_or_symbol": "authenticate", "depth": 5},
    role="analyst",
)
response = server.handle(request)

if response.ok:
    lineage = response.result
    print(f"Found {len(lineage['edges'])} transformations")
```

## Performance Considerations

### Indexing Performance

- Small projects (<100 files): ~1-2 seconds
- Medium projects (100-1000 files): ~5-15 seconds
- Large projects (1000+ files): ~30-60 seconds

Use incremental updates for faster re-indexing:

```python
# First time: full build
indexer.build()

# After changes: incremental update
indexer.update()  # Only re-parses changed files
```

### Memory Usage

SIOF uses SQLite for storage, keeping memory usage low:

- Indexing: ~50-100 MB for typical projects
- MCP server: ~20-30 MB
- De-slopper: ~30-50 MB

## Best Practices

### 1. Run SIOF in CI/CD

Add to your GitHub Actions workflow:

```yaml
- name: Run SIOF Analysis
  run: |
    pip install siof
    siof index build --repo .
    siof slop audit --repo .
```

### 2. Use Strict Mode for Quality Gates

```bash
# Fail CI if any AI slop is detected
siof slop fix --repo . --strict
```

### 3. Track Energy in CI

```bash
# Monitor test suite energy consumption
siof green run --hard-co2 0.5 pytest tests/
```

### 4. Query Before Refactoring

Before making changes, understand the impact:

```python
from siof.repository import Repository

repo = Repository("siof.db")
impact = repo.impact_of_change("mymodule.myfunction")
print(f"This change affects {len(impact.affected_nodes)} symbols")
repo.close()
```

## Troubleshooting

### Parse Errors

If indexing fails on some files:

```python
result = indexer.build()
if result["parse_errors"] > 0:
    print(f"Warning: {result['parse_errors']} files failed to parse")
```

### MCP Server Not Responding

Check if the database exists and has data:

```bash
sqlite3 siof.db "SELECT COUNT(*) FROM nodes;"
```

### High Energy Consumption

Review which commands consume the most energy:

```python
guard = GreenGuard("siof.db")
report = guard.sustainability_report()
print(f"Average energy per run: {report['avg_energy_wh']:.4f} Wh")
```

## Next Steps

- Read the [API documentation](../README.md)
- Explore [example applications](../examples/)
- Check the [roadmap](../README.md#roadmap) for upcoming features
- Report issues on [GitHub](https://github.com/Keerthivasan-Venkitajalam/SIOF/issues)
