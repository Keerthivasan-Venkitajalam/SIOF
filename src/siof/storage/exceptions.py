"""Exception hierarchy for storage backend operations."""

from typing import Any


class StorageException(Exception):
    """Base exception for all storage-related errors.

    Attributes:
        message: Human-readable error message
        context: Additional context about the error
        metadata: Backend-specific error metadata
    """

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize StorageException.

        Args:
            message: Error message
            context: Additional context (operation, parameters, etc.)
            metadata: Backend-specific metadata
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.metadata = metadata or {}

    def __str__(self) -> str:
        """Return formatted error message."""
        msg = self.message
        if self.context:
            msg += f" (context: {self.context})"
        return msg


# Connection-related exceptions


class ConnectionError(StorageException):
    """Base exception for connection-related errors."""


class ConnectionRefused(ConnectionError):
    """Raised when the backend refuses the connection.

    This typically indicates the backend is not running or not accepting
    connections on the specified address/port.
    """


class ConnectionTimeout(ConnectionError):
    """Raised when connection attempt times out.

    This typically indicates network issues or the backend is overloaded.
    """


class ConnectionLost(ConnectionError):
    """Raised when an established connection is lost.

    This typically indicates a network issue or the backend crashed.
    """


# Query-related exceptions


class QueryError(StorageException):
    """Base exception for query execution errors."""


class InvalidQuery(QueryError):
    """Raised when query syntax is invalid.

    This indicates a programming error in the query string.
    """


class QueryTimeout(QueryError):
    """Raised when query execution times out.

    This typically indicates the query is too complex or the backend is slow.
    """


class QueryFailed(QueryError):
    """Raised when query execution fails for other reasons.

    This could indicate data inconsistency, missing nodes/edges, etc.
    """


# Data-related exceptions


class DataError(StorageException):
    """Base exception for data consistency errors."""


class DuplicateNode(DataError):
    """Raised when attempting to create a node with a duplicate ID.

    This indicates a programming error or race condition.
    """


class ReferentialIntegrityError(DataError):
    """Raised when referential integrity constraints are violated.

    This occurs when:
    - Creating an edge with non-existent source or target node
    - Deleting a node that has incoming or outgoing edges
    """


class DataConsistencyError(DataError):
    """Raised when data consistency checks fail.

    This indicates the graph has become corrupted or inconsistent.
    """


# Transaction-related exceptions


class TransactionError(StorageException):
    """Base exception for transaction-related errors."""


class TransactionFailed(TransactionError):
    """Raised when a transaction operation fails.

    This could indicate a programming error or backend issue.
    """


class TransactionTimeout(TransactionError):
    """Raised when a transaction times out.

    This typically indicates the transaction is taking too long.
    """


class TransactionRolledBack(TransactionError):
    """Raised when a transaction is rolled back.

    This could be due to explicit rollback or automatic rollback on error.
    """
