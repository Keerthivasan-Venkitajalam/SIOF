"""Tests for SIOF v2.0 interfaces and mocks."""

from pathlib import Path

from siof.v2.interfaces import CodeEmbedding, Edge, Node, ParseTask
from siof.v2.mocks import (
    MockAuthProvider,
    MockCacheBackend,
    MockCodeEmbedder,
    MockMetricsCollector,
    MockParallelExecutor,
    MockStorageBackend,
    MockTracingProvider,
    MockVectorStore,
)


class TestMockStorage:
    """Test mock storage backend."""

    def test_connect_disconnect(self):
        storage = MockStorageBackend()
        assert not storage.connected

        storage.connect()
        assert storage.connected

        storage.disconnect()
        assert not storage.connected

    def test_add_and_get_node(self):
        storage = MockStorageBackend()
        storage.connect()

        node = Node(
            id="test1",
            symbol="test.function",
            kind="function",
            file_path="test.py",
            line_number=10,
            metadata={},
        )

        storage.add_node(node)
        retrieved = storage.get_node("test1")

        assert retrieved is not None
        assert retrieved.symbol == "test.function"
        assert retrieved.kind == "function"

    def test_add_edge(self):
        storage = MockStorageBackend()
        storage.connect()

        edge = Edge(
            id="edge1",
            source="node1",
            target="node2",
            transform_kind="calls",
            confidence=0.9,
            metadata={},
        )

        storage.add_edge(edge)
        assert "edge1" in storage.edges

    def test_batch_insert(self):
        storage = MockStorageBackend()
        storage.connect()

        nodes = [
            Node(
                id=f"node{i}",
                symbol=f"symbol{i}",
                kind="function",
                file_path="test.py",
                line_number=i,
                metadata={},
            )
            for i in range(10)
        ]

        edges = [
            Edge(
                id=f"edge{i}",
                source=f"node{i}",
                target=f"node{i+1}",
                transform_kind="calls",
                confidence=0.8,
                metadata={},
            )
            for i in range(9)
        ]

        storage.batch_insert(nodes, edges)

        assert len(storage.nodes) == 10
        assert len(storage.edges) == 9

    def test_clear(self):
        storage = MockStorageBackend()
        storage.connect()

        node = Node(
            id="test1",
            symbol="test",
            kind="function",
            file_path="test.py",
            line_number=1,
            metadata={},
        )
        storage.add_node(node)

        storage.clear()
        assert len(storage.nodes) == 0


class TestMockCache:
    """Test mock cache backend."""

    def test_set_and_get(self):
        cache = MockCacheBackend()

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self):
        cache = MockCacheBackend()
        assert cache.get("nonexistent") is None

    def test_delete(self):
        cache = MockCacheBackend()

        cache.set("key1", "value1")
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_exists(self):
        cache = MockCacheBackend()

        cache.set("key1", "value1")
        assert cache.exists("key1")
        assert not cache.exists("key2")

    def test_ttl_expiry(self):
        import time

        cache = MockCacheBackend()

        cache.set("key1", "value1", ttl=1)
        assert cache.get("key1") == "value1"

        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_clear(self):
        cache = MockCacheBackend()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None


class TestMockAuth:
    """Test mock authentication provider."""

    def test_authenticate(self):
        auth = MockAuthProvider()

        token = auth.authenticate({"username": "testuser", "password": "testpass"})

        assert token.token is not None
        assert token.user_id is not None
        assert "read" in token.scopes

    def test_validate_token(self):
        auth = MockAuthProvider()

        token = auth.authenticate({"username": "testuser", "password": "testpass"})
        user = auth.validate_token(token.token)

        assert user is not None
        assert user.username == "testuser"
        assert "analyst" in user.roles

    def test_validate_invalid_token(self):
        auth = MockAuthProvider()

        user = auth.validate_token("invalid-token")
        assert user is None

    def test_revoke_token(self):
        auth = MockAuthProvider()

        token = auth.authenticate({"username": "testuser", "password": "testpass"})
        auth.revoke_token(token.token)

        user = auth.validate_token(token.token)
        assert user is None

    def test_refresh_token(self):
        auth = MockAuthProvider()

        token1 = auth.authenticate({"username": "testuser", "password": "testpass"})
        token2 = auth.refresh_token(token1.token)

        assert token2.token != token1.token
        assert token2.user_id == token1.user_id


class TestMockVectorStore:
    """Test mock vector store."""

    def test_add_and_search(self):
        store = MockVectorStore()

        embedding = CodeEmbedding(
            symbol="test.function", vector=[0.1, 0.2, 0.3], metadata={}
        )

        store.add_embedding(embedding)

        results = store.search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) > 0
        assert results[0].symbol == "test.function"

    def test_delete_embedding(self):
        store = MockVectorStore()

        embedding = CodeEmbedding(
            symbol="test.function", vector=[0.1, 0.2, 0.3], metadata={}
        )

        store.add_embedding(embedding)
        store.delete_embedding("test.function")

        results = store.search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 0

    def test_clear(self):
        store = MockVectorStore()

        for i in range(10):
            embedding = CodeEmbedding(
                symbol=f"func{i}", vector=[float(i)] * 384, metadata={}
            )
            store.add_embedding(embedding)

        store.clear()
        results = store.search([0.0] * 384, top_k=10)
        assert len(results) == 0


class TestMockCodeEmbedder:
    """Test mock code embedder."""

    def test_embed_code(self):
        embedder = MockCodeEmbedder()

        vector = embedder.embed_code("def test(): pass")

        assert len(vector) == 384
        assert all(isinstance(v, float) for v in vector)

    def test_embed_query(self):
        embedder = MockCodeEmbedder()

        vector = embedder.embed_query("find authentication function")

        assert len(vector) == 384
        assert all(isinstance(v, float) for v in vector)

    def test_deterministic(self):
        embedder = MockCodeEmbedder()

        code = "def test(): pass"
        vector1 = embedder.embed_code(code)
        vector2 = embedder.embed_code(code)

        assert vector1 == vector2


class TestMockParallelExecutor:
    """Test mock parallel executor."""

    def test_submit_and_get_results(self):
        executor = MockParallelExecutor()

        task = ParseTask(file_path=Path("test.py"), priority=0)
        executor.submit(task)

        results = list(executor.get_results())
        assert len(results) == 1
        assert results[0].file_path == Path("test.py")

    def test_get_stats(self):
        executor = MockParallelExecutor()

        for i in range(5):
            task = ParseTask(file_path=Path(f"test{i}.py"), priority=0)
            executor.submit(task)

        stats = executor.get_stats()
        assert stats["submitted"] == 5
        assert stats["completed"] == 5

    def test_shutdown(self):
        executor = MockParallelExecutor()

        task = ParseTask(file_path=Path("test.py"), priority=0)
        executor.submit(task)

        executor.shutdown()
        assert len(executor.tasks) == 0
        assert len(executor.results) == 0


class TestMockMetrics:
    """Test mock metrics collector."""

    def test_record_counter(self):
        collector = MockMetricsCollector()

        collector.record_counter("requests_total", 1.0, {"method": "GET"})

        metrics = collector.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].name == "requests_total"
        assert metrics[0].value == 1.0

    def test_record_gauge(self):
        collector = MockMetricsCollector()

        collector.record_gauge("memory_usage", 1024.0, {"unit": "MB"})

        metrics = collector.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].name == "memory_usage"

    def test_record_histogram(self):
        collector = MockMetricsCollector()

        collector.record_histogram("request_duration", 0.5, {"endpoint": "/api"})

        metrics = collector.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].name == "request_duration"


class TestMockTracing:
    """Test mock tracing provider."""

    def test_start_and_end_span(self):
        tracer = MockTracingProvider()

        span = tracer.start_span("test_operation")
        assert span.operation == "test_operation"
        assert span.end_time is None

        tracer.end_span(span)
        assert span.end_time is not None

    def test_add_span_tag(self):
        tracer = MockTracingProvider()

        span = tracer.start_span("test_operation")
        tracer.add_span_tag(span, "user_id", "123")

        assert span.tags["user_id"] == "123"

    def test_get_trace(self):
        tracer = MockTracingProvider()

        span1 = tracer.start_span("operation1")
        tracer.end_span(span1)

        span2 = tracer.start_span("operation2", parent_span_id=span1.trace_id)
        tracer.end_span(span2)

        trace = tracer.get_trace(span1.trace_id)
        assert len(trace) == 2
