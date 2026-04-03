<h1 align="center"><img src="https://raw.githubusercontent.com/Keerthivasan-Venkitajalam/SIOF/main/branding/sioflogo.png" width="300"></h1><br>

[![PyPI version](https://img.shields.io/pypi/v/siof.svg)](https://pypi.org/project/siof/)
[![Python Version](https://img.shields.io/pypi/pyversions/siof.svg)](https://pypi.org/project/siof/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-242%20passing-brightgreen.svg)](https://github.com/Keerthivasan-Venkitajalam/SIOF)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Typing](https://img.shields.io/badge/typing-100%25-blue.svg)](https://github.com/Keerthivasan-Venkitajalam/SIOF)

SIOF (Semantic Integrity and Orchestration Framework) is the fundamental toolkit for AI-native Python development.

- **Source code:** https://github.com/Keerthivasan-Venkitajalam/SIOF
- **Bug reports:** https://github.com/Keerthivasan-Venkitajalam/SIOF/issues
- **PyPI:** https://pypi.org/project/siof/

It provides:

- **Data Transformation Graph (DTG) indexing** - Map your codebase as data lineage, not control flow
- **AI slop detection** - Deterministic pattern matching for machine-generated anti-patterns
- **MCP graph server** - Expose your codebase to LLM agents via Model Context Protocol
- **Developer intent extraction (Memex)** - Preserve architectural reasoning across AI-generated mutations
- **Sustainability tracking (Green Guard)** - Monitor energy consumption and enforce carbon thresholds

## Installation

```bash
pip install siof
```

## Quick Start

### Index Your Repository

```bash
siof index build --repo /path/to/repo
```

### Detect AI-Generated Anti-Patterns

```bash
siof slop audit --repo /path/to/repo
siof slop fix --repo /path/to/repo
```

### Start MCP Server for AI Agents

```bash
siof mcp serve --db siof.db
```

### Python API

```python
from siof.orchestrator import SIOFOrchestrator

# Run complete pipeline
orch = SIOFOrchestrator(repo=".", db_path="siof.db")
result = orch.run_full_pipeline(
    index_mode="build",
    slop_mode="audit",
    enable_memex=True,
    enable_green_guard=True,
)

print(f"Success: {result.success}")
print(f"Duration: {result.total_duration_s:.2f}s")
```

## Core Features

### 1. DTG Indexer

Parses Python repositories into Data Transformation Graphs, mapping data lineage instead of control flow:

```python
from siof.indexer import PythonIndexer

indexer = PythonIndexer(repo=".", db_path="siof.db")
indexer.init()
result = indexer.build()
print(f"Indexed {result['nodes']} nodes and {result['edges']} edges")
```

### 2. De-Slopper Engine

Detects and fixes AI-generated code anti-patterns:

- **NakedExceptionPass** - Bare `except: pass` blocks that swallow errors
- **BroadExceptionPass** - Overly broad exception handlers
- **HedgeComment** - LLM-generated hedge words ("robust", "comprehensive")
- **EchoComment** - Comments that merely restate code mechanics
- **SuspiciousImport** - Hallucinated dependencies
- **UnusedImport** - Dead imports

```python
from siof.deslopper import DeSlopper

deslopper = DeSlopper(repo=".", db_path="siof.db")
result = deslopper.run(mode="fix")  # audit, fix, or strict
print(f"Found {len(result.findings)} issues")
```

### 3. MCP Graph Server

Exposes your DTG to LLM agents via Model Context Protocol:

```python
from siof.mcp_server import MCPGraphServer

server = MCPGraphServer("siof.db")
# Provides tools: find_data_lineage, impact_of_change, get_dead_paths, etc.
```

Features:
- **RBAC** with role hierarchy (viewer/analyst/admin/service)
- **Rate limiting** per role and organization
- **Distributed tracing** with trace IDs
- **Schema validation** for all tool inputs

### 4. Memex Intent Layer

Extracts and preserves developer intent from commits, PRs, and prompts:

```python
from siof.memex import Memex

memex = Memex(repo=".", db_path="siof.db")
result = memex.ingest()  # Extracts from git commits, PRs, prompts
print(f"Ingested {result['ingested']} intent records")

# Query intent
records = memex.query_intent(symbol="authenticate")
scores = memex.score_relevance("authenticate", records)
```

### 5. Green Guard

Tracks energy consumption and enforces sustainability thresholds:

```python
from siof.green_guard import GreenGuard

guard = GreenGuard("siof.db")
result = guard.run_command("pytest", hard_co2_kg=0.1)
print(f"Energy: {result.energy_wh:.4f} Wh, CO2: {result.co2_kg:.6f} kg")

# Sustainability report
report = guard.sustainability_report()
print(f"Total runs: {report['total_runs']}")
print(f"Total CO2: {report['total_co2_kg']:.6f} kg")
```

## Testing

SIOF requires `pytest`. Tests can be run after installation with:

```bash
pytest tests/
```

All 242 tests pass in ~11 seconds.

## Architecture

```mermaid
graph TD
    CLI[CLI Interface<br/>siof index/slop/mcp/memex/green]
    API[Python API<br/>SIOFOrchestrator]
    
    CLI --> ORCH
    API --> ORCH
    
    ORCH[Orchestrator<br/>Pipeline Manager]
    
    ORCH --> IDX[DTG Indexer<br/>Graph Construction]
    ORCH --> SLOP[De-Slopper<br/>Anti-Pattern Detection]
    ORCH --> MCP[MCP Server<br/>Agent Interface]
    ORCH --> MEM[Memex<br/>Intent Extraction]
    ORCH --> GREEN[Green Guard<br/>Sustainability]
    
    IDX --> REPO[Repository Layer<br/>File I/O + AST]
    SLOP --> REPO
    MCP --> REPO
    MEM --> REPO
    GREEN --> REPO
    
    REPO --> DB[(SQLite<br/>DTG + Metadata)]
    
    MCP --> POL[Policy Engine<br/>RBAC + Rate Limit]
    MEM --> INTENT[Intent Extractor<br/>Git + Prompts]
    GREEN --> ENERGY[Energy Calculator<br/>CO2 Tracking]
    
    style CLI fill:#e1f5ff
    style API fill:#e1f5ff
    style ORCH fill:#fff4e1
    style IDX fill:#e8f5e9
    style SLOP fill:#e8f5e9
    style MCP fill:#e8f5e9
    style MEM fill:#e8f5e9
    style GREEN fill:#e8f5e9
    style REPO fill:#ffe4e1
    style DB fill:#f3e5f5
    style POL fill:#fff9e6
    style INTENT fill:#fff9e6
    style ENERGY fill:#fff9e6
```

## Why SIOF?

The AI-native development era (vibe coding) has introduced a new class of technical debt: **AI slop**. LLMs generate code probabilistically, leading to:

- Silent error swallowing via bare `except: pass`
- Hallucinated imports and dead code paths
- Verbose, meaningless documentation
- Loss of architectural intent over time

Traditional linters (Pylint, Flake8, Ruff) catch syntax errors but miss semantic anti-patterns. SIOF bridges this gap with:

1. **DTG-based analysis** - Understand data lineage, not just control flow
2. **Deterministic de-slopping** - Fix AI-specific anti-patterns automatically
3. **MCP integration** - Give AI agents proper context (120x token reduction)
4. **Intent preservation** - Maintain the "why" behind the code
5. **Sustainability** - Track and limit computational waste

## Roadmap

### v1.0 (Current) ✅
- DTG Indexer with incremental updates
- De-Slopper with audit/fix/strict modes
- MCP server with RBAC and rate limiting
- Memex intent extraction
- Green Guard sustainability tracking

### v2.0 (Planned)
- Free-threaded parsing (10x speedup on Python 3.14+)
- Distributed graph storage (Neo4j/FalkorDB)
- Enterprise MCP server (JWT, Redis, stateless)
- Vector-based semantic search (Milvus)
- Edge deployment (K3s, regional caching)
- Kubernetes orchestration (Helm charts)
- Full observability stack (OpenTelemetry, Prometheus, Grafana)

## Contributing

SIOF welcomes contributions! Whether you're fixing bugs, adding features, improving documentation, or reporting issues, your help is appreciated.

### Ways to Contribute

- Report bugs and request features via [GitHub Issues](https://github.com/Keerthivasan-Venkitajalam/SIOF/issues)
- Submit pull requests for bug fixes or new features
- Improve documentation and examples
- Share your use cases and feedback

### Development Setup

```bash
git clone https://github.com/Keerthivasan-Venkitajalam/SIOF.git
cd SIOF
pip install -e ".[dev,test]"
pytest tests/
```

## License

SIOF is released under the [MIT License](LICENSE).

## Author

Created by **Keerthivasan S V** - Built for the AI-native development era.

## Citation

If you use SIOF in your research or project, please cite:

```bibtex
@software{siof2026,
  author = {Keerthivasan S V},
  title = {SIOF: Semantic Integrity and Orchestration Framework},
  year = {2026},
  url = {https://github.com/Keerthivasan-Venkitajalam/SIOF}
}
```
