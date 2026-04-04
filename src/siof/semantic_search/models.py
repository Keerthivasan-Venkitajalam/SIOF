"""Data models for semantic search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeSymbol:
    """Symbol representation for embedding and indexing."""

    symbol_id: str
    name: str
    kind: str
    language: str
    file_path: str
    signature: str = ""
    docstring: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Embedding:
    """Vector embedding with metadata."""

    symbol_id: str
    vector: list[float]
    dimension: int
    model_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Single semantic match."""

    symbol_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResults:
    """Result container with diagnostics."""

    query: str
    results: list[SearchResult]
    query_time_ms: float
    avg_similarity: float
    total_candidates: int


@dataclass
class InsertResult:
    """Batch insert outcome."""

    inserted_ids: list[str]
    count: int
    collection: str


@dataclass
class VectorStoreStats:
    """Vector store runtime statistics."""

    collections: int
    vectors: int
    searches: int
    inserts: int
    deletes: int
