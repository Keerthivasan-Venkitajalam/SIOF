"""DTG integration helpers for vector semantic search."""

from __future__ import annotations

from .code_embedder import CodeEmbedder
from .models import CodeSymbol
from .vector_store import VectorStore


class DTGEmbeddingIntegrator:
    """Syncs DTG symbols into vector search collection."""

    def __init__(self, *, embedder: CodeEmbedder, vector_store: VectorStore, collection: str = "code_symbols"):
        self.embedder = embedder
        self.vector_store = vector_store
        self.collection = collection

    def ensure_collection(self, dimension: int) -> None:
        schema = {
            "dimension": dimension,
            "metric": "cosine",
            "fields": ["vector", "symbol_id", "language", "kind", "file_path"],
        }
        try:
            self.vector_store.create_collection(self.collection, schema)
        except Exception:
            # Collection likely already exists.
            pass

    def upsert_symbols(self, symbols: list[CodeSymbol]) -> int:
        embeddings = self.embedder.batch_embed(symbols)
        vectors = [emb.vector for emb in embeddings]
        metadata = [
            {
                "vector_id": emb.symbol_id,
                "symbol_id": emb.symbol_id,
                "language": emb.metadata.get("language"),
                "kind": emb.metadata.get("kind"),
                "file_path": emb.metadata.get("file_path"),
            }
            for emb in embeddings
        ]
        result = self.vector_store.insert_vectors(self.collection, vectors, metadata)
        return result.count

    def delete_symbols(self, symbol_ids: list[str]) -> int:
        return self.vector_store.delete_vectors(self.collection, symbol_ids)
