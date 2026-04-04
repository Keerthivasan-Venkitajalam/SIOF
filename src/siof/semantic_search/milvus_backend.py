"""Milvus-compatible backend with in-memory fallback and connection pooling."""

from __future__ import annotations

import math
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from .models import InsertResult, SearchResult, VectorStoreStats
from .vector_store import VectorStore


@dataclass
class _VectorRow:
    vector_id: str
    vector: list[float]
    metadata: dict[str, Any]


class MilvusBackend(VectorStore):
    """VectorStore implementation with optional Milvus-compatible behavior.

    This implementation is intentionally self-contained for local development
    and tests; it provides the same API contract and can be replaced with a
    true pymilvus-backed transport without changing callers.
    """

    def __init__(self, pool_size: int = 10, max_retries: int = 3):
        if pool_size < 1:
            raise ValueError("pool_size must be >= 1")
        self.pool_size = pool_size
        self.max_retries = max_retries
        self._connected = False
        self._lock = threading.RLock()
        self._collections: dict[str, dict[str, Any]] = {}
        self._pool = deque(maxlen=pool_size)
        self._searches = 0
        self._inserts = 0
        self._deletes = 0

    def connect(self, connection_string: str) -> None:
        if not connection_string:
            raise ValueError("connection_string is required")
        with self._lock:
            self._connected = True
            self._pool.clear()
            for idx in range(self.pool_size):
                self._pool.append(f"conn-{idx}")

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self._pool.clear()

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MilvusBackend is not connected")

    def create_collection(self, name: str, schema: dict[str, Any]) -> None:
        self._ensure_connected()
        with self._lock:
            self._collections[name] = {
                "schema": schema,
                "rows": {},
            }

    def delete_collection(self, name: str) -> None:
        self._ensure_connected()
        with self._lock:
            self._collections.pop(name, None)

    def insert_vectors(
        self,
        collection: str,
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
    ) -> InsertResult:
        self._ensure_connected()
        if len(vectors) != len(metadata):
            raise ValueError("vectors and metadata lengths must match")
        with self._lock:
            if collection not in self._collections:
                raise KeyError(f"Collection not found: {collection}")
            rows = self._collections[collection]["rows"]
            inserted_ids: list[str] = []
            for vec, meta in zip(vectors, metadata):
                vector_id = str(meta.get("vector_id") or uuid.uuid4())
                rows[vector_id] = _VectorRow(vector_id=vector_id, vector=list(vec), metadata=dict(meta))
                inserted_ids.append(vector_id)
            self._inserts += len(inserted_ids)
            return InsertResult(inserted_ids=inserted_ids, count=len(inserted_ids), collection=collection)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            raise ValueError("Vector dimensions must match")
        dot = sum(x * y for x, y in zip(a, b))
        an = math.sqrt(sum(x * x for x in a))
        bn = math.sqrt(sum(y * y for y in b))
        if an == 0 or bn == 0:
            return 0.0
        return dot / (an * bn)

    @staticmethod
    def _metadata_matches(meta: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, value in filters.items():
            if meta.get(key) != value:
                return False
        return True

    def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        top_k: int = 10,
        threshold: float = 0.7,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        self._ensure_connected()
        with self._lock:
            if collection not in self._collections:
                raise KeyError(f"Collection not found: {collection}")
            rows = self._collections[collection]["rows"].values()
            filters = filters or {}
            scored: list[SearchResult] = []
            for row in rows:
                if filters and not self._metadata_matches(row.metadata, filters):
                    continue
                score = self._cosine_similarity(query_vector, row.vector)
                if score >= threshold:
                    scored.append(
                        SearchResult(
                            symbol_id=row.metadata.get("symbol_id", row.vector_id),
                            score=score,
                            metadata=dict(row.metadata),
                        )
                    )
            scored.sort(key=lambda r: r.score, reverse=True)
            self._searches += 1
            return scored[:top_k]

    def delete_vectors(self, collection: str, vector_ids: list[str]) -> int:
        self._ensure_connected()
        with self._lock:
            if collection not in self._collections:
                raise KeyError(f"Collection not found: {collection}")
            rows = self._collections[collection]["rows"]
            removed = 0
            for vector_id in vector_ids:
                if rows.pop(vector_id, None) is not None:
                    removed += 1
            self._deletes += removed
            return removed

    def get_stats(self) -> VectorStoreStats:
        with self._lock:
            collections = len(self._collections)
            vectors = sum(len(c["rows"]) for c in self._collections.values())
            return VectorStoreStats(
                collections=collections,
                vectors=vectors,
                searches=self._searches,
                inserts=self._inserts,
                deletes=self._deletes,
            )
