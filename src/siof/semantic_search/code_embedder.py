"""Code symbol embedder with deterministic lightweight fallback model."""

from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import dataclass

from .embedding_cache import EmbeddingCache
from .models import CodeSymbol, Embedding


@dataclass
class EmbedderMetrics:
    """Embedding performance diagnostics."""

    embedded_symbols: int = 0
    total_duration_ms: float = 0.0
    batch_calls: int = 0


class CodeEmbedder:
    """Embeds code symbols using deterministic hash-based vectors.

    The deterministic fallback avoids heavy runtime dependencies while keeping
    a stable semantic-search API and reproducible vectors for tests.
    """

    def __init__(
        self,
        *,
        model_name: str = "all-MiniLM-L6-v2",
        dimension: int = 384,
        cache: EmbeddingCache | None = None,
    ):
        if dimension < 8:
            raise ValueError("dimension must be >= 8")
        self.model_name = model_name
        self.dimension = dimension
        self.cache = cache
        self._metrics = EmbedderMetrics()

    def _seed_for_symbol(self, symbol: CodeSymbol) -> int:
        text = "|".join(
            [
                symbol.symbol_id,
                symbol.name,
                symbol.kind,
                symbol.language,
                symbol.file_path,
                symbol.signature,
                symbol.docstring,
                symbol.content,
            ]
        )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _normalize(self, vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return [0.0 for _ in vector]
        return [v / norm for v in vector]

    def _embed_uncached(self, symbol: CodeSymbol) -> Embedding:
        seed = self._seed_for_symbol(symbol)
        rng = random.Random(seed)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]
        vector = self._normalize(raw)
        return Embedding(
            symbol_id=symbol.symbol_id,
            vector=vector,
            dimension=self.dimension,
            model_name=self.model_name,
            metadata={
                "language": symbol.language,
                "kind": symbol.kind,
                "file_path": symbol.file_path,
            },
        )

    def embed(self, symbol: CodeSymbol) -> Embedding:
        started = time.perf_counter()
        cache_key = symbol.symbol_id
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        emb = self._embed_uncached(symbol)
        if self.cache:
            self.cache.put(cache_key, emb)
        self._metrics.embedded_symbols += 1
        self._metrics.total_duration_ms += (time.perf_counter() - started) * 1000.0
        return emb

    def batch_embed(self, symbols: list[CodeSymbol], batch_size: int = 32) -> list[Embedding]:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        out: list[Embedding] = []
        self._metrics.batch_calls += 1
        for i in range(0, len(symbols), batch_size):
            chunk = symbols[i : i + batch_size]
            for symbol in chunk:
                out.append(self.embed(symbol))
        return out

    def get_metrics(self) -> dict[str, float | int]:
        avg_ms = (
            self._metrics.total_duration_ms / self._metrics.embedded_symbols
            if self._metrics.embedded_symbols
            else 0.0
        )
        return {
            "embedded_symbols": self._metrics.embedded_symbols,
            "batch_calls": self._metrics.batch_calls,
            "avg_embedding_ms": avg_ms,
        }
