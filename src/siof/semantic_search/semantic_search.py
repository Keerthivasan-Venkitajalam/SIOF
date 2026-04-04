"""Similarity-based semantic search engine."""

from __future__ import annotations

import time
from typing import Any

from .code_embedder import CodeEmbedder
from .models import CodeSymbol, SearchResults
from .vector_store import VectorStore


class SemanticSearch:
    """Searches vectors by semantic similarity."""

    def __init__(self, *, embedder: CodeEmbedder, vector_store: VectorStore, collection: str = "code_symbols"):
        self.embedder = embedder
        self.vector_store = vector_store
        self.collection = collection

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
        threshold: float = 0.7,
        filters: dict[str, Any] | None = None,
        query: str = "",
    ) -> SearchResults:
        started = time.perf_counter()
        matches = self.vector_store.search(
            self.collection,
            query_vector,
            top_k=top_k,
            threshold=threshold,
            filters=filters,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        avg = sum(m.score for m in matches) / len(matches) if matches else 0.0
        return SearchResults(
            query=query,
            results=matches,
            query_time_ms=elapsed_ms,
            avg_similarity=avg,
            total_candidates=len(matches),
        )

    def search_by_symbol(
        self,
        symbol: CodeSymbol,
        *,
        top_k: int = 10,
        threshold: float = 0.7,
        filters: dict[str, Any] | None = None,
    ) -> SearchResults:
        emb = self.embedder.embed(symbol)
        return self.search(
            emb.vector,
            top_k=top_k,
            threshold=threshold,
            filters=filters,
            query=symbol.name,
        )
