from __future__ import annotations

from siof.semantic_search import (
    CodeEmbedder,
    CodeSymbol,
    EmbeddingCache,
    IntentQuery,
    MilvusBackend,
    SemanticSearch,
)


def _symbol(symbol_id: str, name: str, language: str = "python") -> CodeSymbol:
    return CodeSymbol(
        symbol_id=symbol_id,
        name=name,
        kind="function",
        language=language,
        file_path=f"{name}.py",
        signature=f"def {name}(): ...",
        content=name,
    )


def test_embedder_is_deterministic():
    embedder = CodeEmbedder(dimension=64)
    s = _symbol("1", "load_config")
    v1 = embedder.embed(s).vector
    v2 = embedder.embed(s).vector
    assert v1 == v2


def test_embedding_cache_tracks_hits_and_misses():
    cache = EmbeddingCache(max_size=2)
    embedder = CodeEmbedder(dimension=32, cache=cache)
    s = _symbol("1", "f")
    embedder.embed(s)
    embedder.embed(s)
    stats = cache.get_stats()
    assert stats["hits"] >= 1


def test_milvus_backend_insert_and_search():
    backend = MilvusBackend(pool_size=2)
    backend.connect("milvus://localhost:19530")
    backend.create_collection("code_symbols", {"dimension": 32})

    embedder = CodeEmbedder(dimension=32)
    a = _symbol("a", "parse_file")
    b = _symbol("b", "render_html")
    ea = embedder.embed(a)
    eb = embedder.embed(b)

    backend.insert_vectors(
        "code_symbols",
        [ea.vector, eb.vector],
        [
            {"vector_id": "a", "symbol_id": "a", "language": "python"},
            {"vector_id": "b", "symbol_id": "b", "language": "python"},
        ],
    )

    results = backend.search("code_symbols", ea.vector, top_k=2, threshold=0.0)
    assert results
    assert results[0].symbol_id == "a"


def test_semantic_search_by_symbol():
    backend = MilvusBackend()
    backend.connect("milvus://localhost:19530")
    backend.create_collection("code_symbols", {"dimension": 64})

    embedder = CodeEmbedder(dimension=64)
    s1 = _symbol("s1", "build_index")
    e1 = embedder.embed(s1)
    backend.insert_vectors("code_symbols", [e1.vector], [{"vector_id": "s1", "symbol_id": "s1"}])

    search = SemanticSearch(embedder=embedder, vector_store=backend)
    found = search.search_by_symbol(s1, top_k=1, threshold=0.0)
    assert found.results[0].symbol_id == "s1"


def test_intent_query_returns_results_and_history():
    backend = MilvusBackend()
    backend.connect("milvus://localhost:19530")
    backend.create_collection("code_symbols", {"dimension": 64})

    embedder = CodeEmbedder(dimension=64)
    symbol = _symbol("sx", "optimize_query")
    emb = embedder.embed(symbol)
    backend.insert_vectors("code_symbols", [emb.vector], [{"vector_id": "sx", "symbol_id": "sx"}])

    semantic = SemanticSearch(embedder=embedder, vector_store=backend)
    intent = IntentQuery(semantic)
    res = intent.query("optimize query", top_k=1, threshold=0.0)
    assert res.results
    assert intent.history()
