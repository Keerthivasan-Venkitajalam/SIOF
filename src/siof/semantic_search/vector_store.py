"""Vector store abstraction for semantic search backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import InsertResult, SearchResult, VectorStoreStats


class VectorStore(ABC):
    """Abstract contract for vector storage and retrieval."""

    @abstractmethod
    def connect(self, connection_string: str) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def create_collection(self, name: str, schema: dict[str, Any]) -> None:
        pass

    @abstractmethod
    def delete_collection(self, name: str) -> None:
        pass

    @abstractmethod
    def insert_vectors(
        self,
        collection: str,
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> InsertResult:
        pass

    @abstractmethod
    def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        top_k: int = 10,
        threshold: float = 0.7,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        pass

    @abstractmethod
    def delete_vectors(self, collection: str, vector_ids: list[str]) -> int:
        pass

    @abstractmethod
    def get_stats(self) -> VectorStoreStats:
        pass
