"""Natural language intent query interface for semantic code discovery."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CodeSymbol, SearchResults
from .semantic_search import SemanticSearch


@dataclass
class IntentHistory:
    intent: str
    results: SearchResults


class IntentQuery:
    """Converts user intent to embeddings and executes semantic search."""

    def __init__(self, semantic_search: SemanticSearch):
        self.semantic_search = semantic_search
        self._history: list[IntentHistory] = []

    def query(self, intent: str, *, top_k: int = 10, threshold: float = 0.7) -> SearchResults:
        query_symbol = CodeSymbol(
            symbol_id=f"intent::{intent}",
            name=intent,
            kind="intent",
            language="text",
            file_path="<intent>",
            content=intent,
        )
        results = self.semantic_search.search_by_symbol(
            query_symbol, top_k=top_k, threshold=threshold
        )
        self._history.append(IntentHistory(intent=intent, results=results))
        return results

    def refine_query(
        self, refinement: str, *, top_k: int = 10, threshold: float = 0.7
    ) -> SearchResults:
        if not self._history:
            return self.query(refinement, top_k=top_k, threshold=threshold)
        base_intent = self._history[-1].intent
        combined = f"{base_intent} {refinement}".strip()
        return self.query(combined, top_k=top_k, threshold=threshold)

    def history(self) -> list[IntentHistory]:
        return self._history[:]
