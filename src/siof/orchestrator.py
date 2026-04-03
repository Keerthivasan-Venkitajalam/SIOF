"""SIOF Orchestrator: Wires all modules together for unified workflow.

Provides high-level orchestration for the complete SIOF pipeline:
1. Index build (Phase 1)
2. De-slopper audit/fix (Phase 2)
3. MCP server (Phase 3)
4. Memex intent extraction (Phase 4)
5. Green Guard energy tracking (Phase 5)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .deslopper import DeSlopper
from .green_guard import GreenGuard
from .indexer import PythonIndexer
from .mcp_server import MCPGraphServer
from .memex import Memex
from .repository import Repository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OrchestrationResult:
    """Result of orchestrated workflow."""
    success: bool
    phase_results: dict[str, Any]
    total_duration_s: float
    error: str | None = None


class SIOFOrchestrator:
    """Orchestrates complete SIOF workflow.

    Wires together all phases:
    - Phase 1: DTG Indexer
    - Phase 2: De-Slopper
    - Phase 3: MCP Server
    - Phase 4: Memex
    - Phase 5: Green Guard
    """

    def __init__(self, repo: Path | str, db_path: Path | str):
        """Initialize orchestrator.

        Args:
            repo: Repository path
            db_path: Database path
        """
        self.repo = Path(repo)
        self.db_path = Path(db_path)
        logger.info(f"Initialized SIOF Orchestrator for {repo}")

    def run_full_pipeline(
        self,
        index_mode: str = "build",
        slop_mode: str = "audit",
        enable_memex: bool = True,
        enable_green_guard: bool = True,
        hard_co2_kg: float | None = None,
    ) -> OrchestrationResult:
        """Run complete SIOF pipeline.

        Args:
            index_mode: "build" or "update"
            slop_mode: "audit", "fix", or "strict"
            enable_memex: Enable Memex intent extraction
            enable_green_guard: Enable Green Guard energy tracking
            hard_co2_kg: Hard CO2 limit for Green Guard

        Returns:
            OrchestrationResult with all phase results
        """
        import time

        start_time = time.time()
        phase_results: dict[str, Any] = {}

        try:
            # Phase 1: Index
            logger.info("Phase 1: DTG Indexer")
            indexer = PythonIndexer(repo=self.repo, db_path=self.db_path)
            indexer.init()
            if index_mode == "build":
                index_result = indexer.build()
            else:
                index_result = indexer.update()
            indexer.close()
            phase_results["phase1_index"] = index_result
            logger.info(f"Phase 1 complete: {index_result}")

            # Phase 2: De-Slopper
            logger.info("Phase 2: De-Slopper")
            deslopper = DeSlopper(repo=self.repo, db_path=self.db_path)
            slop_result = deslopper.run(mode=slop_mode)
            deslopper.close()
            phase_results["phase2_slop"] = {
                "findings": len(slop_result.findings),
                "mode": slop_mode,
            }
            logger.info(f"Phase 2 complete: {len(slop_result.findings)} findings")

            # Phase 3: MCP Server (initialize but don't serve)
            logger.info("Phase 3: MCP Server")
            mcp_server = MCPGraphServer(self.db_path)
            metrics = mcp_server.get_metrics()
            mcp_server.close()
            phase_results["phase3_mcp"] = {
                "status": "ready",
                "metrics": metrics,
            }
            logger.info("Phase 3 complete: MCP server ready")

            # Phase 4: Memex
            if enable_memex:
                logger.info("Phase 4: Memex Intent Layer")
                memex = Memex(repo=self.repo, db_path=self.db_path)
                memex_result = memex.ingest()
                memex.close()
                phase_results["phase4_memex"] = memex_result
                logger.info(f"Phase 4 complete: {memex_result['ingested']} intent records")
            else:
                phase_results["phase4_memex"] = {"skipped": True}

            # Phase 5: Green Guard
            if enable_green_guard:
                logger.info("Phase 5: Green Guard")
                guard = GreenGuard(self.db_path)
                sustainability = guard.sustainability_report()
                guard.close()
                phase_results["phase5_green_guard"] = sustainability
                logger.info(f"Phase 5 complete: {sustainability['total_runs']} runs tracked")
            else:
                phase_results["phase5_green_guard"] = {"skipped": True}

            duration_s = time.time() - start_time
            logger.info(f"Full pipeline complete in {duration_s:.2f}s")

            return OrchestrationResult(
                success=True,
                phase_results=phase_results,
                total_duration_s=duration_s,
            )

        except Exception as exc:
            logger.error(f"Pipeline failed: {exc}", exc_info=True)
            duration_s = time.time() - start_time
            return OrchestrationResult(
                success=False,
                phase_results=phase_results,
                total_duration_s=duration_s,
                error=str(exc),
            )

    def get_repository_stats(self) -> dict[str, Any]:
        """Get comprehensive repository statistics.

        Returns:
            Dictionary with all repository metrics
        """
        repo = Repository(self.db_path)
        stats = repo.get_statistics()
        repo.close()
        return stats

    def validate_kpis(self) -> dict[str, Any]:
        """Validate key performance indicators.

        Returns:
            Dictionary with KPI validation results
        """
        repo = Repository(self.db_path)
        stats = repo.get_statistics()
        repo.close()

        kpis = {
            "nodes_indexed": stats.get("nodes", 0) > 0,
            "edges_indexed": stats.get("edges", 0) > 0,
            "artifacts_parsed": stats.get("artifacts", 0) > 0,
            "findings_detected": stats.get("findings", 0) >= 0,
            "intent_records": stats.get("intent_records", 0) >= 0,
        }

        kpis["all_passed"] = all(kpis.values())
        logger.info(f"KPI validation: {kpis}")
        return kpis
