"""SIOF Storage module - distributed graph storage backends."""

from .backend import Edge, Node, StorageBackend
from .compatibility import RepositoryAdapter
from .config import StorageConfig
from .connection_pool import ConnectionPool
from .distributed_repository import DistributedRepository, IsolationLevel
from .exceptions import (
    ConnectionError as StorageConnectionError,
)
from .exceptions import (
    ConnectionLost,
    ConnectionRefused,
    ConnectionTimeout,
    DataConsistencyError,
    DataError,
    DuplicateNode,
    InvalidQuery,
    QueryError,
    QueryFailed,
    QueryTimeout,
    ReferentialIntegrityError,
    StorageException,
    TransactionError,
    TransactionFailed,
    TransactionRolledBack,
    TransactionTimeout,
)
from .falkordb_backend import FalkorDBBackend
from .legacy import Storage
from .migration import MigrationTool
from .neo4j_backend import Neo4jBackend
from .query_optimizer import ExecutionStrategy, QueryOptimizer
from .retry import ErrorCategory, RetryPolicy

__all__ = [
    "ConnectionLost",
    "ConnectionPool",
    "ConnectionRefused",
    "ConnectionTimeout",
    "DataConsistencyError",
    "DataError",
    "DistributedRepository",
    "DuplicateNode",
    "Edge",
    "ErrorCategory",
    "ExecutionStrategy",
    "FalkorDBBackend",
    "InvalidQuery",
    "IsolationLevel",
    "MigrationTool",
    "Neo4jBackend",
    "Node",
    "QueryError",
    "QueryFailed",
    "QueryOptimizer",
    "QueryTimeout",
    "ReferentialIntegrityError",
    "RepositoryAdapter",
    "RetryPolicy",
    "Storage",
    "StorageBackend",
    "StorageConfig",
    "StorageConnectionError",
    "StorageException",
    "TransactionError",
    "TransactionFailed",
    "TransactionRolledBack",
    "TransactionTimeout",
]
