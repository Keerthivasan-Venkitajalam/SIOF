"""Core interfaces for SIOF v2.0 architecture.

Defines abstract base classes for all pluggable components,
enabling different implementations and easy testing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ============================================================================
# Storage Interfaces
# ============================================================================


@dataclass
class Node:
    """Graph node representation."""

    id: str
    symbol: str
    kind: str
    file_path: str
    line_number: int
    metadata: dict[str, Any]


@dataclass
class Edge:
    """Graph edge representation."""

    id: str
    source: str
    target: str
    transform_kind: str
    confidence: float
    metadata: dict[str, Any]


@dataclass
class QueryResult:
    """Result of a graph query."""

    nodes: list[Node]
    edges: list[Edge]
    metadata: dict[str, Any]


class StorageBackend(ABC):
    """Abstract storage backend for graph data.

    Implementations:
    - SQLiteBackend (v1.0 compatibility)
    - Neo4jBackend (distributed, ACID)
    - FalkorDBBackend (Redis-based, fast reads)
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to storage."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to storage."""

    @abstractmethod
    def add_node(self, node: Node) -> None:
        """Add a node to the graph."""

    @abstractmethod
    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph."""

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """Retrieve a node by ID."""

    @abstractmethod
    def query(self, cypher: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Execute a Cypher query."""

    @abstractmethod
    def batch_insert(self, nodes: list[Node], edges: list[Edge]) -> None:
        """Bulk insert nodes and edges."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all data."""


# ============================================================================
# Cache Interfaces
# ============================================================================


class CacheBackend(ABC):
    """Abstract cache backend for performance optimization.

    Implementations:
    - MemoryCache (in-process, testing)
    - RedisCache (distributed, production)
    """

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Get value from cache."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache with optional TTL."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete key from cache."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists."""


# ============================================================================
# Authentication Interfaces
# ============================================================================


@dataclass
class User:
    """User identity."""

    id: str
    username: str
    email: str
    roles: list[str]
    org_id: str
    metadata: dict[str, Any]


@dataclass
class AuthToken:
    """Authentication token."""

    token: str
    user_id: str
    expires_at: float
    scopes: list[str]


class AuthProvider(ABC):
    """Abstract authentication provider.

    Implementations:
    - JWTAuthProvider (stateless, JWT tokens)
    - SessionAuthProvider (stateful, Redis sessions)
    - APIKeyAuthProvider (service-to-service)
    """

    @abstractmethod
    def authenticate(self, credentials: dict[str, Any]) -> AuthToken:
        """Authenticate user and return token."""

    @abstractmethod
    def validate_token(self, token: str) -> User | None:
        """Validate token and return user."""

    @abstractmethod
    def revoke_token(self, token: str) -> None:
        """Revoke a token."""

    @abstractmethod
    def refresh_token(self, token: str) -> AuthToken:
        """Refresh an expiring token."""


# ============================================================================
# Semantic Search Interfaces
# ============================================================================


@dataclass
class CodeEmbedding:
    """Vector embedding of code."""

    symbol: str
    vector: list[float]
    metadata: dict[str, Any]


@dataclass
class SearchResult:
    """Semantic search result."""

    symbol: str
    score: float
    node: Node
    metadata: dict[str, Any]


class VectorStore(ABC):
    """Abstract vector store for semantic search.

    Implementations:
    - MilvusVectorStore (distributed, production)
    - FAISSVectorStore (in-memory, development)
    """

    @abstractmethod
    def add_embedding(self, embedding: CodeEmbedding) -> None:
        """Add a code embedding."""

    @abstractmethod
    def search(
        self, query_vector: list[float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[SearchResult]:
        """Search for similar code."""

    @abstractmethod
    def delete_embedding(self, symbol: str) -> None:
        """Delete an embedding."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all embeddings."""


class CodeEmbedder(ABC):
    """Abstract code embedder.

    Implementations:
    - TransformerEmbedder (sentence-transformers)
    - OpenAIEmbedder (OpenAI embeddings API)
    """

    @abstractmethod
    def embed_code(self, code: str, metadata: dict[str, Any] | None = None) -> list[float]:
        """Generate embedding for code."""

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for search query."""


# ============================================================================
# Parallel Processing Interfaces
# ============================================================================


@dataclass
class ParseTask:
    """Task for parallel parsing."""

    file_path: Path
    priority: int = 0


@dataclass
class ParseResult:
    """Result of parsing a file."""

    file_path: Path
    nodes: list[Node]
    edges: list[Edge]
    errors: list[str]
    duration_ms: float


class ParallelExecutor(ABC):
    """Abstract parallel executor for free-threaded parsing.

    Implementations:
    - ThreadPoolExecutor (Python 3.14+ free-threading)
    - ProcessPoolExecutor (fallback for older Python)
    """

    @abstractmethod
    def submit(self, task: ParseTask) -> None:
        """Submit a task for execution."""

    @abstractmethod
    def get_results(self) -> Iterator[ParseResult]:
        """Get completed results."""

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown executor."""

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get execution statistics."""


# ============================================================================
# Observability Interfaces
# ============================================================================


@dataclass
class Metric:
    """Metric data point."""

    name: str
    value: float
    labels: dict[str, str]
    timestamp: float


@dataclass
class Span:
    """Distributed tracing span."""

    trace_id: str
    span_id: str
    operation: str
    start_time: float
    end_time: float | None
    tags: dict[str, Any]


class MetricsCollector(ABC):
    """Abstract metrics collector.

    Implementations:
    - PrometheusCollector (Prometheus metrics)
    - DatadogCollector (Datadog APM)
    """

    @abstractmethod
    def record_counter(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a counter metric."""

    @abstractmethod
    def record_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a gauge metric."""

    @abstractmethod
    def record_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Record a histogram metric."""

    @abstractmethod
    def get_metrics(self) -> list[Metric]:
        """Get all recorded metrics."""


class TracingProvider(ABC):
    """Abstract distributed tracing provider.

    Implementations:
    - OpenTelemetryTracer (OpenTelemetry)
    - JaegerTracer (Jaeger)
    """

    @abstractmethod
    def start_span(self, operation: str, parent_span_id: str | None = None) -> Span:
        """Start a new span."""

    @abstractmethod
    def end_span(self, span: Span) -> None:
        """End a span."""

    @abstractmethod
    def add_span_tag(self, span: Span, key: str, value: Any) -> None:
        """Add a tag to a span."""

    @abstractmethod
    def get_trace(self, trace_id: str) -> list[Span]:
        """Get all spans for a trace."""
