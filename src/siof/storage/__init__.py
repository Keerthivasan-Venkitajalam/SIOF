"""SIOF Storage module - distributed graph storage backends."""

from .legacy import Storage
from .backend import StorageBackend, Node, Edge
from .connection_pool import ConnectionPool
from .retry import RetryPolicy, ErrorCategory
from .exceptions import (
    StorageException,
    ConnectionError as StorageConnectionError,
    ConnectionRefused,
    ConnectionTimeout,
    ConnectionLost,
    QueryError,
    InvalidQuery,
    QueryTimeout,
    QueryFailed,
    DataError,
    DuplicateNode,
    ReferentialIntegrityError,
    DataConsistencyError,
    TransactionError,
    TransactionFailed,
    TransactionTimeout,
    TransactionRolledBack,
)
from .config import StorageConfig
from .neo4j_backend import Neo4jBackend
from .falkordb_backend import FalkorDBBackend
from .distributed_repository import DistributedRepository, IsolationLevel
from .query_optimizer import QueryOptimizer, ExecutionStrategy
from .migration import MigrationTool
from .compatibility import RepositoryAdapter

__all__ = [
    "Storage",
    "StorageBackend",
    "Node",
    "Edge",
    "ConnectionPool",
    "RetryPolicy",
    "ErrorCategory",
    "StorageException",
    "StorageConnectionError",
    "ConnectionRefused",
    "ConnectionTimeout",
    "ConnectionLost",
    "QueryError",
    "InvalidQuery",
    "QueryTimeout",
    "QueryFailed",
    "DataError",
    "DuplicateNode",
    "ReferentialIntegrityError",
    "DataConsistencyError",
    "TransactionError",
    "TransactionFailed",
    "TransactionTimeout",
    "TransactionRolledBack",
    "StorageConfig",
    "Neo4jBackend",
    "FalkorDBBackend",
    "DistributedRepository",
    "IsolationLevel",
    "QueryOptimizer",
    "ExecutionStrategy",
    "MigrationTool",
    "RepositoryAdapter",
]
