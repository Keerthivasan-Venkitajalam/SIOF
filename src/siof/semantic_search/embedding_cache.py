"""Thread-safe LRU embedding cache with optional persistence."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path

from .models import Embedding


class EmbeddingCache:
    """Simple LRU cache for embeddings."""

    def __init__(self, max_size: int = 10000, persist_path: str | None = None):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self.max_size = max_size
        self.persist_path = Path(persist_path) if persist_path else None
        self._lock = threading.RLock()
        self._store: OrderedDict[str, Embedding] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        if self.persist_path and self.persist_path.exists():
            self._load()

    def get(self, key: str) -> Embedding | None:
        with self._lock:
            emb = self._store.get(key)
            if emb is None:
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return emb

    def put(self, key: str, embedding: Embedding) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = embedding
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)
                self._evictions += 1

    def remove(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def save(self) -> None:
        if not self.persist_path:
            return
        with self._lock:
            data = {
                key: {
                    "symbol_id": value.symbol_id,
                    "vector": value.vector,
                    "dimension": value.dimension,
                    "model_name": value.model_name,
                    "metadata": value.metadata,
                }
                for key, value in self._store.items()
            }
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.persist_path.write_text(json.dumps(data), encoding="utf-8")

    def _load(self) -> None:
        if self.persist_path is None:
            return
        raw = json.loads(self.persist_path.read_text(encoding="utf-8"))
        for key, value in raw.items():
            self._store[key] = Embedding(
                symbol_id=value["symbol_id"],
                vector=[float(v) for v in value["vector"]],
                dimension=int(value["dimension"]),
                model_name=value["model_name"],
                metadata=dict(value.get("metadata", {})),
            )

    def get_stats(self) -> dict[str, float | int]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total else 0.0
            return {
                "size": len(self._store),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
            }
