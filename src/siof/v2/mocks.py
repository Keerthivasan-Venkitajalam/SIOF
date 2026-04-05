"""Mock implementations of v2.0 interfaces for testing and development.

These mocks provide in-memory implementations that can be used for:
- Unit testing without external dependencies
- Development without infrastructure setup
- Integration testing with predictable behavior
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from .interfaces import (
    AuthProvider,
    AuthToken,
    CacheBackend,
    CodeEmbedder,
    CodeEmbedding,
    Edge,
    Metric,
    MetricsCollector,
    Node,
    ParallelExecutor,
    ParseResult,
    ParseTask,
    QueryResult,
    SearchResult,
    Span,
    StorageBackend,
    TracingProvider,
    User,
    VectorStore,
)

# ============================================================================
# Mock Storage
# ============================================================================


class MockStorageBackend(StorageBackend):
    """In-memory storage backend for testing."""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges[edge.id] = edge

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResult:
        # Simple mock: return all nodes and edges
        return QueryResult(
            nodes=list(self.nodes.values()),
            edges=list(self.edges.values()),
            metadata={"query": cypher, "params": params},
        )

    def batch_insert(self, nodes: list[Node], edges: list[Edge]) -> None:
        for node in nodes:
            self.add_node(node)
        for edge in edges:
            self.add_edge(edge)

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()


# ============================================================================
# Mock Cache
# ============================================================================


class MockCacheBackend(CacheBackend):
    """In-memory cache backend for testing."""

    def __init__(self):
        self.data: dict[str, tuple[Any, float | None]] = {}

    def get(self, key: str) -> Any | None:
        if key not in self.data:
            return None
        value, ttl = self.data[key]
        if ttl is not None and time.time() > ttl:
            del self.data[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + ttl if ttl else None
        self.data[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def clear(self) -> None:
        self.data.clear()

    def exists(self, key: str) -> bool:
        return self.get(key) is not None


# ============================================================================
# Mock Authentication
# ============================================================================


class MockAuthProvider(AuthProvider):
    """Mock authentication provider for testing."""

    def __init__(self):
        self.users: dict[str, User] = {}
        self.tokens: dict[str, AuthToken] = {}

    def authenticate(self, credentials: dict[str, Any]) -> AuthToken:
        raw_username = credentials.get("username")
        username = raw_username if isinstance(raw_username, str) and raw_username else "mock-user"

        # Mock: accept any username/password
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            username=username,
            email=f"{username}@example.com",
            roles=["analyst"],
            org_id="default",
            metadata={},
        )
        self.users[user_id] = user

        token = AuthToken(
            token=str(uuid.uuid4()),
            user_id=user_id,
            expires_at=time.time() + 3600,
            scopes=["read", "write"],
        )
        self.tokens[token.token] = token
        return token

    def validate_token(self, token: str) -> User | None:
        auth_token = self.tokens.get(token)
        if not auth_token:
            return None
        if time.time() > auth_token.expires_at:
            return None
        return self.users.get(auth_token.user_id)

    def revoke_token(self, token: str) -> None:
        self.tokens.pop(token, None)

    def refresh_token(self, token: str) -> AuthToken:
        old_token = self.tokens.get(token)
        if not old_token:
            raise ValueError("Invalid token")

        new_token = AuthToken(
            token=str(uuid.uuid4()),
            user_id=old_token.user_id,
            expires_at=time.time() + 3600,
            scopes=old_token.scopes,
        )
        self.tokens[new_token.token] = new_token
        return new_token


# ============================================================================
# Mock Semantic Search
# ============================================================================


class MockVectorStore(VectorStore):
    """In-memory vector store for testing."""

    def __init__(self):
        self.embeddings: dict[str, CodeEmbedding] = {}

    def add_embedding(self, embedding: CodeEmbedding) -> None:
        self.embeddings[embedding.symbol] = embedding

    def search(
        self, query_vector: list[float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[SearchResult]:
        # Mock: return random results
        results: list[SearchResult] = []
        for symbol, embedding in list(self.embeddings.items())[:top_k]:
            # Mock similarity score
            score = 0.9 - (len(results) * 0.1)
            results.append(
                SearchResult(
                    symbol=symbol,
                    score=score,
                    node=Node(
                        id=symbol,
                        symbol=symbol,
                        kind="function",
                        file_path="mock.py",
                        line_number=1,
                        metadata={},
                    ),
                    metadata={},
                )
            )
        return results

    def delete_embedding(self, symbol: str) -> None:
        self.embeddings.pop(symbol, None)

    def clear(self) -> None:
        self.embeddings.clear()


class MockCodeEmbedder(CodeEmbedder):
    """Mock code embedder for testing."""

    def embed_code(self, code: str, metadata: dict[str, Any] | None = None) -> list[float]:
        # Mock: return deterministic vector based on code hash
        return [float(hash(code) % 100) / 100.0 for _ in range(384)]

    def embed_query(self, query: str) -> list[float]:
        # Mock: return deterministic vector based on query hash
        return [float(hash(query) % 100) / 100.0 for _ in range(384)]


# ============================================================================
# Mock Parallel Processing
# ============================================================================


class MockParallelExecutor(ParallelExecutor):
    """Mock parallel executor for testing."""

    def __init__(self):
        self.tasks: list[ParseTask] = []
        self.results: list[ParseResult] = []
        self.stats = {"submitted": 0, "completed": 0, "errors": 0}

    def submit(self, task: ParseTask) -> None:
        self.tasks.append(task)
        self.stats["submitted"] += 1

        # Mock: immediately create result
        result = ParseResult(
            file_path=task.file_path,
            nodes=[],
            edges=[],
            errors=[],
            duration_ms=10.0,
        )
        self.results.append(result)
        self.stats["completed"] += 1

    def get_results(self) -> Iterator[ParseResult]:
        while self.results:
            yield self.results.pop(0)

    def shutdown(self) -> None:
        self.tasks.clear()
        self.results.clear()

    def get_stats(self) -> dict[str, Any]:
        return self.stats.copy()


# ============================================================================
# Mock Observability
# ============================================================================


class MockMetricsCollector(MetricsCollector):
    """Mock metrics collector for testing."""

    def __init__(self):
        self.metrics: list[Metric] = []

    def record_counter(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        self.metrics.append(
            Metric(name=name, value=value, labels=labels or {}, timestamp=time.time())
        )

    def record_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        self.metrics.append(
            Metric(name=name, value=value, labels=labels or {}, timestamp=time.time())
        )

    def record_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        self.metrics.append(
            Metric(name=name, value=value, labels=labels or {}, timestamp=time.time())
        )

    def get_metrics(self) -> list[Metric]:
        return self.metrics.copy()


class MockTracingProvider(TracingProvider):
    """Mock tracing provider for testing."""

    def __init__(self):
        self.spans: dict[str, list[Span]] = defaultdict(list)
        self.active_spans: dict[str, Span] = {}

    def start_span(self, operation: str, parent_span_id: str | None = None) -> Span:
        trace_id = parent_span_id or str(uuid.uuid4())
        span = Span(
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
            operation=operation,
            start_time=time.time(),
            end_time=None,
            tags={},
        )
        self.active_spans[span.span_id] = span
        return span

    def end_span(self, span: Span) -> None:
        span.end_time = time.time()
        self.spans[span.trace_id].append(span)
        self.active_spans.pop(span.span_id, None)

    def add_span_tag(self, span: Span, key: str, value: Any) -> None:
        span.tags[key] = value

    def get_trace(self, trace_id: str) -> list[Span]:
        return self.spans.get(trace_id, [])
