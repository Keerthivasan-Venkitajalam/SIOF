"""Memex: Intent extraction and semantic memory index.

Extracts developer intent from commits, PRs, and prompt logs,
linking intent to DTG entities for architectural decision tracking.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import IntentRecord
from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IntentScore:
    """Relevance score for intent record."""
    record_id: str
    symbol: str
    relevance: float  # 0.0-1.0
    source: str
    objective: str


class IntentExtractor:
    """Extracts intent from various sources."""

    @staticmethod
    def extract_from_commit(message: str) -> tuple[str, str, str]:
        """Extract objective, constraints, rationale from commit message."""
        lines = message.strip().split('\n')
        objective = lines[0][:180] if lines else ""

        # Extract constraints from message body
        constraints = "maintain compatibility and semantic integrity"
        if len(lines) > 1:
            body = '\n'.join(lines[1:])
            if 'constraint' in body.lower() or 'require' in body.lower():
                constraints = body[:200]

        rationale = f"Derived from commit: {objective}"
        return objective, constraints, rationale

    @staticmethod
    def extract_from_pr(title: str, description: str = "") -> tuple[str, str, str]:
        """Extract objective, constraints, rationale from PR."""
        objective = title[:180]
        constraints = "maintain compatibility and semantic integrity"
        if description:
            if 'constraint' in description.lower():
                constraints = description[:200]
        rationale = f"Derived from PR: {objective}"
        return objective, constraints, rationale

    @staticmethod
    def extract_from_prompt(prompt: str) -> tuple[str, str, str]:
        """Extract objective, constraints, rationale from prompt."""
        objective = prompt[:180]
        constraints = "maintain compatibility and semantic integrity"
        rationale = f"Derived from prompt: {objective}"
        return objective, constraints, rationale

    @staticmethod
    def guess_symbol(text: str) -> str | None:
        """Guess symbol from text."""
        # Match module.symbol pattern
        m = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)", text)
        if m:
            return m.group(1)
        return None


class Memex:
    """Intent extraction and semantic memory index.

    Extracts developer intent from commits, PRs, and prompt logs,
    linking intent to DTG entities for architectural decision tracking.
    """

    def __init__(self, repo: Path, db_path: Path):
        """Initialize Memex.

        Args:
            repo: Repository path
            db_path: Database path
        """
        self.repo = Path(repo)
        self.db = Storage(db_path)
        self.db.init_schema()
        self.extractor = IntentExtractor()
        logger.info(f"Initialized Memex for {repo}")

    def close(self) -> None:
        """Close database connection."""
        self.db.close()

    def ingest(self) -> dict[str, Any]:
        """Ingest intent records from git commits and prompt logs.

        Returns:
            Dictionary with ingestion statistics
        """
        records: list[IntentRecord] = []

        # Commit-based intent extraction
        commit_count = self._ingest_commits(records)

        # PR-based intent extraction (if available)
        pr_count = self._ingest_prs(records)

        # Prompt logs (optional convention)
        prompt_count = self._ingest_prompts(records)

        if records:
            self.db.insert_intent_records(records)
            logger.info(f"Total ingested: {len(records)} intent records")

        return {
            "ingested": len(records),
            "commits": commit_count,
            "prs": pr_count,
            "prompts": prompt_count,
        }

    def _ingest_commits(self, records: list[IntentRecord]) -> int:
        """Ingest intent from git commits.

        Args:
            records: List to append records to

        Returns:
            Number of commits ingested
        """
        try:
            log = subprocess.check_output(
                ["git", "-C", str(self.repo), "--no-pager", "log", "--pretty=%B", "-n", "50"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            commit_count = 0
            for message in log.split('\n\n'):
                if not message.strip():
                    continue
                objective, constraints, rationale = self.extractor.extract_from_commit(message)
                records.append(
                    IntentRecord(
                        source="git_commit",
                        objective=objective,
                        constraints=constraints,
                        rationale=rationale,
                        linked_symbol=self.extractor.guess_symbol(message),
                    )
                )
                commit_count += 1
            logger.info(f"Ingested {commit_count} commit messages")
            return commit_count
        except Exception as exc:
            logger.warning(f"Failed to ingest git commits: {exc}")
            return 0

    def _ingest_prs(self, records: list[IntentRecord]) -> int:
        """Ingest intent from PR descriptions.

        Args:
            records: List to append records to

        Returns:
            Number of PRs ingested
        """
        pr_dir = self.repo / ".siof" / "prs"
        if not pr_dir.exists():
            return 0

        pr_count = 0
        for pr_file in pr_dir.glob("*.md"):
            try:
                content = pr_file.read_text(encoding="utf-8", errors="ignore")
                lines = content.split('\n')
                title = lines[0] if lines else ""
                description = '\n'.join(lines[1:]) if len(lines) > 1 else ""

                objective, constraints, rationale = self.extractor.extract_from_pr(title, description)
                records.append(
                    IntentRecord(
                        source="pr",
                        objective=objective,
                        constraints=constraints,
                        rationale=rationale,
                        linked_symbol=self.extractor.guess_symbol(content),
                    )
                )
                pr_count += 1
            except Exception as exc:
                logger.warning(f"Failed to ingest PR {pr_file}: {exc}")

        logger.info(f"Ingested {pr_count} PR descriptions")
        return pr_count

    def _ingest_prompts(self, records: list[IntentRecord]) -> int:
        """Ingest intent from prompt logs.

        Args:
            records: List to append records to

        Returns:
            Number of prompts ingested
        """
        prompt_log = self.repo / ".siof" / "prompts.log"
        if not prompt_log.exists():
            return 0

        prompt_count = 0
        for line in prompt_log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            objective, constraints, rationale = self.extractor.extract_from_prompt(line)
            records.append(
                IntentRecord(
                    source="prompt_log",
                    objective=objective,
                    constraints=constraints,
                    rationale=rationale,
                    linked_symbol=self.extractor.guess_symbol(line),
                )
            )
            prompt_count += 1

        logger.info(f"Ingested {prompt_count} prompt log entries")
        return prompt_count

    def query(self, text: str) -> dict[str, Any]:
        """Query intent history for a symbol or area.

        Args:
            text: Symbol or area to query

        Returns:
            Dictionary with intent records
        """
        logger.info(f"Querying intent history for: {text}")
        return self.db.get_intent_history(text)

    def score_relevance(self, symbol: str, records: list[IntentRecord]) -> list[IntentScore]:
        """Score relevance of intent records to a symbol.

        Args:
            symbol: Symbol to score against
            records: Intent records to score

        Returns:
            List of scored records sorted by relevance
        """
        scores: list[IntentScore] = []

        for i, record in enumerate(records):
            relevance = 0.0

            # Exact symbol match
            if record.linked_symbol == symbol:
                relevance = 1.0
            # Partial match
            elif record.linked_symbol and symbol in record.linked_symbol:
                relevance = 0.7
            # Objective contains symbol
            elif symbol in record.objective.lower():
                relevance = 0.5

            if relevance > 0.0:
                scores.append(
                    IntentScore(
                        record_id=f"record_{i}",
                        symbol=symbol,
                        relevance=relevance,
                        source=record.source,
                        objective=record.objective,
                    )
                )

        # Sort by relevance descending
        scores.sort(key=lambda s: s.relevance, reverse=True)
        logger.debug(f"Scored {len(scores)} records for {symbol}")
        return scores
