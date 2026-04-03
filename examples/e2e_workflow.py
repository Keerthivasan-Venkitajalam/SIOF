#!/usr/bin/env python3
"""End-to-end SIOF workflow demonstration.

This example shows how to use SIOF to analyze a Python project,
detect AI-generated code issues, query the data transformation graph,
extract developer intent, and track sustainability metrics.
"""

import sys
from pathlib import Path

from siof.orchestrator import SIOFOrchestrator


def main():
    """Run complete SIOF workflow on a repository."""
    # Get repository path from command line or use current directory
    repo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    db_path = repo_path / "siof.db"

    print("=" * 70)
    print("SIOF End-to-End Workflow")
    print("=" * 70)
    print(f"Repository: {repo_path.absolute()}")
    print(f"Database: {db_path.absolute()}")
    print()

    # Initialize orchestrator
    orchestrator = SIOFOrchestrator(repo=repo_path, db_path=db_path)

    # Run full pipeline
    print("Running full SIOF pipeline...")
    print("-" * 70)

    result = orchestrator.run_full_pipeline(
        index_mode="build",  # Build fresh index
        slop_mode="audit",  # Audit for AI slop (don't auto-fix)
        enable_memex=True,  # Extract developer intent
        enable_green_guard=True,  # Track energy consumption
    )

    print()
    print("=" * 70)
    print("Pipeline Results")
    print("=" * 70)

    if result.success:
        print(f"✅ Pipeline completed successfully in {result.total_duration_s:.2f}s")
        print()

        # Phase 1: Indexing
        if "phase1_index" in result.phase_results:
            index_result = result.phase_results["phase1_index"]
            print("📊 Phase 1: DTG Indexer")
            print(f"   Files indexed: {index_result.get('files', 0)}")
            print(f"   Nodes created: {index_result.get('nodes', 0)}")
            print(f"   Edges created: {index_result.get('edges', 0)}")
            print(f"   Parse errors: {index_result.get('parse_errors', 0)}")
            print()

        # Phase 2: De-Slopper
        if "phase2_slop" in result.phase_results:
            slop_result = result.phase_results["phase2_slop"]
            print("🧹 Phase 2: De-Slopper")
            print(f"   Mode: {slop_result.get('mode', 'unknown')}")
            print(f"   Findings: {slop_result.get('findings', 0)}")
            print()

        # Phase 3: MCP Server
        if "phase3_mcp" in result.phase_results:
            mcp_result = result.phase_results["phase3_mcp"]
            print("🔌 Phase 3: MCP Server")
            print(f"   Status: {mcp_result.get('status', 'unknown')}")
            metrics = mcp_result.get("metrics", {})
            print(f"   Total requests: {metrics.get('total_requests', 0)}")
            print(f"   Total errors: {metrics.get('total_errors', 0)}")
            print()

        # Phase 4: Memex
        if "phase4_memex" in result.phase_results:
            memex_result = result.phase_results["phase4_memex"]
            if not memex_result.get("skipped"):
                print("📝 Phase 4: Memex Intent Layer")
                print(f"   Intent records ingested: {memex_result.get('ingested', 0)}")
                print()

        # Phase 5: Green Guard
        if "phase5_green_guard" in result.phase_results:
            green_result = result.phase_results["phase5_green_guard"]
            if not green_result.get("skipped"):
                print("🌱 Phase 5: Green Guard")
                print(f"   Total runs tracked: {green_result.get('total_runs', 0)}")
                print(f"   Total CO2: {green_result.get('total_co2_kg', 0):.6f} kg")
                print(f"   Total energy: {green_result.get('total_energy_wh', 0):.4f} Wh")
                print()

        # Repository statistics
        print("=" * 70)
        print("Repository Statistics")
        print("=" * 70)
        stats = orchestrator.get_repository_stats()
        print(f"Total nodes: {stats.get('nodes', 0)}")
        print(f"Total edges: {stats.get('edges', 0)}")
        print(f"Total artifacts: {stats.get('artifacts', 0)}")
        print(f"Total findings: {stats.get('findings', 0)}")
        print(f"Total intent records: {stats.get('intent_records', 0)}")
        print()

        # KPI validation
        print("=" * 70)
        print("KPI Validation")
        print("=" * 70)
        kpis = orchestrator.validate_kpis()
        for kpi_name, passed in kpis.items():
            status = "✅" if passed else "❌"
            print(f"{status} {kpi_name}: {passed}")
        print()

        if kpis["all_passed"]:
            print("🎉 All KPIs passed!")
        else:
            print("⚠️  Some KPIs failed")

    else:
        print(f"❌ Pipeline failed: {result.error}")
        print(f"Duration: {result.total_duration_s:.2f}s")
        return 1

    print()
    print("=" * 70)
    print("Next Steps")
    print("=" * 70)
    print("1. Review findings in the database")
    print("2. Start MCP server: siof mcp serve --db siof.db")
    print("3. Query the graph: siof mcp query find_data_lineage <symbol>")
    print("4. Fix AI slop: siof slop fix --repo .")
    print("5. Track energy: siof green run <command>")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
