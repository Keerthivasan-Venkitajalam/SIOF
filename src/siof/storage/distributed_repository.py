"""Distributed repository layer with backend abstraction and retry logic."""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from enum import Enum
from typing import Any

from siof.storage.backend import Edge, Node, StorageBackend
from siof.storage.exceptions import TransactionFailed
from siof.storage.retry import RetryPolicy

logger = logging.getLogger(__name__)


class IsolationLevel(Enum):
    """Transaction isolation levels."""

    READ_UNCOMMITTED = "read_uncommitted"
    READ_COMMITTED = "read_committed"
    REPEATABLE_READ = "repeatable_read"
    SERIALIZABLE = "serializable"


class DistributedRepository:
    """Unified query interface for distributed graph storage.

    This class provides a high-level API for interacting with distributed
    graph backends (Neo4j, FalkorDB, etc.) while abstracting away backend
    specifics. It integrates retry logic, caching, and query optimization.

    Attributes:
        backend: The underlying StorageBackend instance
        retry_policy: RetryPolicy for handling transient failures
        cache: LRU cache for frequently accessed nodes
        cache_size: Maximum number of cached items
        cache_ttl_seconds: Time-to-live for cached items
    """

    def __init__(
        self,
        backend: StorageBackend,
        cache_size: int = 1000,
        cache_ttl_seconds: int = 600,
        retry_policy: RetryPolicy | None = None,
        transaction_timeout_seconds: int = 300,
    ) -> None:
        """Initialize DistributedRepository.

        Args:
            backend: StorageBackend instance to use
            cache_size: Maximum number of cached items (default: 1000)
            cache_ttl_seconds: Cache TTL in seconds (default: 600)
            retry_policy: RetryPolicy instance (default: new instance with defaults)
            transaction_timeout_seconds: Transaction timeout in seconds (default: 300)

        Raises:
            ValueError: If parameters are invalid
        """
        if not backend:
            raise ValueError("backend cannot be None")
        if cache_size < 0:
            raise ValueError(f"cache_size must be non-negative, got {cache_size}")
        if cache_ttl_seconds < 0:
            raise ValueError(f"cache_ttl_seconds must be non-negative, got {cache_ttl_seconds}")
        if transaction_timeout_seconds < 0:
            raise ValueError(
                f"transaction_timeout_seconds must be non-negative, got {transaction_timeout_seconds}"
            )

        self.backend = backend
        self.cache_size = cache_size
        self.cache_ttl_seconds = cache_ttl_seconds
        self.retry_policy = retry_policy or RetryPolicy()
        self.transaction_timeout_seconds = transaction_timeout_seconds

        # Cache structure: {key: (value, timestamp)}
        self.cache: dict[str, tuple[Node, float]] = {}

        # Cache statistics
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0

        # Transaction state
        self._transaction_active = False
        self._transaction_start_time: float | None = None
        self._transaction_savepoints: list[str] = []
        self._isolation_level = IsolationLevel.READ_COMMITTED

        # Transaction metrics
        self._active_transactions = 0
        self._committed_transactions = 0
        self._rolled_back_transactions = 0

    def create_node(self, node: Node) -> None:
        """Create a new node with retry logic.

        Args:
            node: Node object to create

        Raises:
            StorageException: If creation fails after retries
        """
        logger.debug(f"Creating node: {node.id}")

        try:
            self.retry_policy.execute(self.backend.create_node, node)
            self._invalidate_cache()
            logger.debug(f"Successfully created node: {node.id}")
        except Exception as e:
            logger.error(f"Failed to create node {node.id}: {e}")
            raise

    def read_node(self, node_id: str) -> Node | None:
        """Read a node with caching and retry logic.

        Args:
            node_id: The node ID to read

        Returns:
            Node object if found, None otherwise

        Raises:
            StorageException: If read fails after retries
        """
        logger.debug(f"Reading node: {node_id}")

        # Check cache first
        cached_node = self._cache_get(node_id)
        if cached_node is not None:
            self._cache_hits += 1
            logger.debug(f"Cache hit for node: {node_id}")
            return cached_node

        self._cache_misses += 1

        # Read from backend with retry
        try:
            node = self.retry_policy.execute(self.backend.read_node, node_id)

            if node is None:
                logger.debug(f"Node not found: {node_id}")
                return None

            if not isinstance(node, Node):
                logger.warning(
                    f"Unexpected node type from backend for {node_id}: {type(node).__name__}"
                )
                return None

            # Cache result if found
            self._cache_put(node_id, node)

            logger.debug(f"Successfully read node: {node_id}")
            return node

        except Exception as e:
            logger.error(f"Failed to read node {node_id}: {e}")
            raise

    def update_node(self, node: Node) -> None:
        """Update an existing node with retry logic.

        Args:
            node: Node object with updated properties

        Raises:
            StorageException: If update fails after retries
        """
        logger.debug(f"Updating node: {node.id}")

        try:
            self.retry_policy.execute(self.backend.update_node, node)
            self._invalidate_cache()
            logger.debug(f"Successfully updated node: {node.id}")
        except Exception as e:
            logger.error(f"Failed to update node {node.id}: {e}")
            raise

    def delete_node(self, node_id: str) -> None:
        """Delete a node with retry logic.

        Args:
            node_id: The node ID to delete

        Raises:
            StorageException: If deletion fails after retries
        """
        logger.debug(f"Deleting node: {node_id}")

        try:
            self.retry_policy.execute(self.backend.delete_node, node_id)
            self._invalidate_cache()
            logger.debug(f"Successfully deleted node: {node_id}")
        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            raise

    def create_edge(self, edge: Edge) -> None:
        """Create a new edge with retry logic.

        Args:
            edge: Edge object to create

        Raises:
            StorageException: If creation fails after retries
        """
        logger.debug(f"Creating edge: {edge.source_id} -> {edge.target_id}")

        try:
            self.retry_policy.execute(self.backend.create_edge, edge)
            self._invalidate_cache()
            logger.debug(f"Successfully created edge: {edge.source_id} -> {edge.target_id}")
        except Exception as e:
            logger.error(f"Failed to create edge {edge.source_id} -> {edge.target_id}: {e}")
            raise

    def delete_edge(self, source_id: str, target_id: str) -> None:
        """Delete an edge with retry logic.

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Raises:
            StorageException: If deletion fails after retries
        """
        logger.debug(f"Deleting edge: {source_id} -> {target_id}")

        try:
            self.retry_policy.execute(self.backend.delete_edge, source_id, target_id)
            self._invalidate_cache()
            logger.debug(f"Successfully deleted edge: {source_id} -> {target_id}")
        except Exception as e:
            logger.error(f"Failed to delete edge {source_id} -> {target_id}: {e}")
            raise

    def find_lineage(self, node_id: str) -> list[Node]:
        """Find all upstream nodes in the data lineage.

        This method finds all nodes that contribute to the given node
        by traversing incoming edges recursively.

        Args:
            node_id: The node ID to find lineage for

        Returns:
            List of upstream Node objects

        Raises:
            StorageException: If query fails
        """
        logger.debug(f"Finding lineage for node: {node_id}")

        try:
            query = """
            MATCH (n:Node {id: $id})<-[*]-(upstream:Node)
            RETURN DISTINCT upstream
            """

            results = self.retry_policy.execute(
                self.backend.query,
                query,
                {"id": node_id},
            )

            nodes = []
            for result in results:
                node = self._result_to_node(result)
                if node:
                    nodes.append(node)

            logger.debug(f"Found {len(nodes)} upstream nodes for {node_id}")
            return nodes

        except Exception as e:
            logger.error(f"Failed to find lineage for {node_id}: {e}")
            raise

    def find_dependents(self, node_id: str) -> list[Node]:
        """Find all downstream nodes that depend on this node.

        This method finds all nodes that are affected by the given node
        by traversing outgoing edges recursively.

        Args:
            node_id: The node ID to find dependents for

        Returns:
            List of downstream Node objects

        Raises:
            StorageException: If query fails
        """
        logger.debug(f"Finding dependents for node: {node_id}")

        try:
            query = """
            MATCH (n:Node {id: $id})-[*]->(downstream:Node)
            RETURN DISTINCT downstream
            """

            results = self.retry_policy.execute(
                self.backend.query,
                query,
                {"id": node_id},
            )

            nodes = []
            for result in results:
                node = self._result_to_node(result)
                if node:
                    nodes.append(node)

            logger.debug(f"Found {len(nodes)} downstream nodes for {node_id}")
            return nodes

        except Exception as e:
            logger.error(f"Failed to find dependents for {node_id}: {e}")
            raise

    def find_path(self, source_id: str, target_id: str) -> list[Node] | None:
        """Find the shortest path between two nodes.

        This method finds the shortest path from source to target node
        by traversing edges.

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Returns:
            List of Node objects representing the path, or None if no path exists

        Raises:
            StorageException: If query fails
        """
        logger.debug(f"Finding path from {source_id} to {target_id}")

        try:
            query = """
            MATCH path = shortestPath(
                (source:Node {id: $source_id})-[*]->(target:Node {id: $target_id})
            )
            RETURN [node IN nodes(path) | node] as path_nodes
            """

            results = self.retry_policy.execute(
                self.backend.query,
                query,
                {"source_id": source_id, "target_id": target_id},
            )

            if not results:
                logger.debug(f"No path found from {source_id} to {target_id}")
                return None

            # Extract path nodes from first result
            path_nodes = []
            first_result = results[0]

            # Handle different result formats
            path_data = first_result.get("path_nodes")
            if not path_data:
                logger.debug("No path_nodes in result")
                return None

            for node_data in path_data:
                node = self._result_to_node({"n": node_data})
                if node:
                    path_nodes.append(node)

            logger.debug(f"Found path with {len(path_nodes)} nodes")
            return path_nodes if path_nodes else None

        except Exception as e:
            logger.error(f"Failed to find path from {source_id} to {target_id}: {e}")
            raise

    def find_cycles(self) -> list[list[Node]]:
        """Find all circular dependencies in the graph.

        This method detects cycles in the graph which indicate circular
        dependencies that should be resolved.

        Returns:
            List of cycles, where each cycle is a list of Node objects

        Raises:
            StorageException: If query fails
        """
        logger.debug("Finding cycles in graph")

        try:
            query = """
            MATCH (n:Node)
            WHERE EXISTS((n)-[*]->(n))
            RETURN DISTINCT n
            """

            results = self.retry_policy.execute(
                self.backend.query,
                query,
                {},
            )

            cycles = []
            for result in results:
                node = self._result_to_node(result)
                if node:
                    cycles.append([node])

            logger.debug(f"Found {len(cycles)} cycles in graph")
            return cycles

        except Exception as e:
            logger.error(f"Failed to find cycles: {e}")
            raise

    def query_nodes(self, filters: dict[str, Any]) -> list[Node]:
        """Query nodes with flexible filtering.

        Args:
            filters: Dictionary of filter conditions (e.g., {"type": "Symbol"})

        Returns:
            List of matching Node objects

        Raises:
            StorageException: If query fails
        """
        logger.debug(f"Querying nodes with filters: {filters}")

        try:
            # Build WHERE clause from filters
            where_clauses = []
            params = {}

            for key, value in filters.items():
                where_clauses.append(f"n.{key} = ${key}")
                params[key] = value

            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

            query = f"""
            MATCH (n:Node)
            WHERE {where_clause}
            RETURN n
            """

            results = self.retry_policy.execute(
                self.backend.query,
                query,
                params,
            )

            nodes = []
            for result in results:
                node = self._result_to_node(result)
                if node:
                    nodes.append(node)

            logger.debug(f"Found {len(nodes)} nodes matching filters")
            return nodes

        except Exception as e:
            logger.error(f"Failed to query nodes: {e}")
            raise

    def query_edges(self, filters: dict[str, Any]) -> list[Edge]:
        """Query edges with flexible filtering.

        Args:
            filters: Dictionary of filter conditions (e.g., {"edge_type": "CALLS"})

        Returns:
            List of matching Edge objects

        Raises:
            StorageException: If query fails
        """
        logger.debug(f"Querying edges with filters: {filters}")

        try:
            # Build WHERE clause from filters
            where_clauses = []
            params = {}

            for key, value in filters.items():
                where_clauses.append(f"r.{key} = ${key}")
                params[key] = value

            where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

            query = f"""
            MATCH (source:Node)-[r:EDGE]->(target:Node)
            WHERE {where_clause}
            RETURN source, r, target
            """

            results = self.retry_policy.execute(
                self.backend.query,
                query,
                params,
            )

            edges = []
            for result in results:
                edge = self._result_to_edge(result)
                if edge:
                    edges.append(edge)

            logger.debug(f"Found {len(edges)} edges matching filters")
            return edges

        except Exception as e:
            logger.error(f"Failed to query edges: {e}")
            raise

    def begin_transaction(
        self,
        isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> None:
        """Begin a new transaction.

        Args:
            isolation_level: Transaction isolation level (default: READ_COMMITTED)

        Raises:
            TransactionFailed: If transaction is already active or backend fails
        """
        if self._transaction_active:
            raise TransactionFailed("Transaction already active")

        logger.debug(f"Beginning transaction with isolation level: {isolation_level.value}")

        try:
            self.retry_policy.execute(self.backend.begin_transaction)
            self._transaction_active = True
            self._transaction_start_time = time.time()
            self._isolation_level = isolation_level
            self._active_transactions += 1
            logger.debug("Transaction started successfully")
        except Exception as e:
            logger.error(f"Failed to begin transaction: {e}")
            raise TransactionFailed(f"Failed to begin transaction: {e}") from e

    def commit_transaction(self) -> None:
        """Commit the current transaction.

        Raises:
            TransactionFailed: If no transaction is active or backend fails
        """
        if not self._transaction_active:
            raise TransactionFailed("No active transaction to commit")

        # Check for timeout
        if self._transaction_start_time:
            elapsed = time.time() - self._transaction_start_time
            if elapsed > self.transaction_timeout_seconds:
                logger.warning(
                    f"Transaction timeout: {elapsed}s > {self.transaction_timeout_seconds}s"
                )
                self.rollback_transaction()
                raise TransactionFailed(
                    f"Transaction timeout: {elapsed}s > {self.transaction_timeout_seconds}s"
                )

        logger.debug("Committing transaction")

        try:
            self.retry_policy.execute(self.backend.commit_transaction)
            self._transaction_active = False
            self._transaction_start_time = None
            self._transaction_savepoints.clear()
            self._committed_transactions += 1
            self._invalidate_cache()
            logger.debug("Transaction committed successfully")
        except Exception as e:
            logger.error(f"Failed to commit transaction: {e}")
            self._transaction_active = False
            raise TransactionFailed(f"Failed to commit transaction: {e}") from e

    def rollback_transaction(self) -> None:
        """Rollback the current transaction.

        Raises:
            TransactionFailed: If no transaction is active or backend fails
        """
        if not self._transaction_active:
            raise TransactionFailed("No active transaction to rollback")

        logger.debug("Rolling back transaction")

        try:
            self.retry_policy.execute(self.backend.rollback_transaction)
            self._transaction_active = False
            self._transaction_start_time = None
            self._transaction_savepoints.clear()
            self._rolled_back_transactions += 1
            self._invalidate_cache()
            logger.debug("Transaction rolled back successfully")
        except Exception as e:
            logger.error(f"Failed to rollback transaction: {e}")
            self._transaction_active = False
            raise TransactionFailed(f"Failed to rollback transaction: {e}") from e

    @contextmanager
    def transaction(
        self,
        isolation_level: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> Generator[None, None, None]:
        """Context manager for transactions.

        Usage:
            with repository.transaction():
                repository.create_node(node)
                repository.create_edge(edge)

        Args:
            isolation_level: Transaction isolation level

        Yields:
            None

        Raises:
            TransactionFailed: If transaction fails
        """
        self.begin_transaction(isolation_level)
        try:
            yield
            self.commit_transaction()
        except Exception as e:
            logger.error(f"Transaction failed, rolling back: {e}")
            try:
                self.rollback_transaction()
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {rollback_error}")
            raise

    def create_savepoint(self, savepoint_name: str) -> None:
        """Create a savepoint within the current transaction.

        Savepoints allow partial rollback within a transaction.

        Args:
            savepoint_name: Name of the savepoint

        Raises:
            TransactionFailed: If no transaction is active
        """
        if not self._transaction_active:
            raise TransactionFailed("No active transaction for savepoint")

        logger.debug(f"Creating savepoint: {savepoint_name}")

        try:
            # Execute savepoint query on backend
            query = f"SAVEPOINT {savepoint_name}"
            self.retry_policy.execute(self.backend.query, query, {})
            self._transaction_savepoints.append(savepoint_name)
            logger.debug(f"Savepoint created: {savepoint_name}")
        except Exception as e:
            logger.error(f"Failed to create savepoint: {e}")
            raise TransactionFailed(f"Failed to create savepoint: {e}") from e

    def rollback_to_savepoint(self, savepoint_name: str) -> None:
        """Rollback to a specific savepoint.

        Args:
            savepoint_name: Name of the savepoint to rollback to

        Raises:
            TransactionFailed: If savepoint doesn't exist or rollback fails
        """
        if not self._transaction_active:
            raise TransactionFailed("No active transaction")

        if savepoint_name not in self._transaction_savepoints:
            raise TransactionFailed(f"Savepoint not found: {savepoint_name}")

        logger.debug(f"Rolling back to savepoint: {savepoint_name}")

        try:
            # Execute rollback query on backend
            query = f"ROLLBACK TO SAVEPOINT {savepoint_name}"
            self.retry_policy.execute(self.backend.query, query, {})

            # Remove savepoints after this one
            idx = self._transaction_savepoints.index(savepoint_name)
            self._transaction_savepoints = self._transaction_savepoints[: idx + 1]

            logger.debug(f"Rolled back to savepoint: {savepoint_name}")
        except Exception as e:
            logger.error(f"Failed to rollback to savepoint: {e}")
            raise TransactionFailed(f"Failed to rollback to savepoint: {e}") from e

    def set_isolation_level(self, isolation_level: IsolationLevel) -> None:
        """Set the isolation level for the current transaction.

        Args:
            isolation_level: The isolation level to set

        Raises:
            TransactionFailed: If no transaction is active
        """
        if not self._transaction_active:
            raise TransactionFailed("No active transaction")

        logger.debug(f"Setting isolation level to: {isolation_level.value}")
        self._isolation_level = isolation_level

    def get_transaction_metrics(self) -> dict[str, Any]:
        """Get transaction metrics.

        Returns:
            Dictionary containing:
            - active_transactions: Number of active transactions
            - committed_transactions: Total committed transactions
            - rolled_back_transactions: Total rolled back transactions
            - current_transaction_active: Whether a transaction is currently active
            - current_transaction_duration_seconds: Duration of current transaction (if active)
            - current_isolation_level: Current isolation level
        """
        current_duration = None
        if self._transaction_active and self._transaction_start_time:
            current_duration = time.time() - self._transaction_start_time

        return {
            "active_transactions": self._active_transactions,
            "committed_transactions": self._committed_transactions,
            "rolled_back_transactions": self._rolled_back_transactions,
            "current_transaction_active": self._transaction_active,
            "current_transaction_duration_seconds": current_duration,
            "current_isolation_level": self._isolation_level.value,
            "savepoints": len(self._transaction_savepoints),
        }

    def _cache_put(self, key: str, value: Node) -> None:
        """Add item to cache with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
        """
        # Check if cache is full
        if len(self.cache) >= self.cache_size:
            # Remove oldest entry (first item in dict)
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            self._cache_evictions += 1
            logger.debug(f"Evicted cache entry: {oldest_key}")

        # Add new entry with timestamp
        self.cache[key] = (value, time.time())
        logger.debug(f"Cached item: {key}")

    def _cache_get(self, key: str) -> Node | None:
        """Get item from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value if found and not expired, None otherwise
        """
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]

        # Check if expired
        if time.time() - timestamp > self.cache_ttl_seconds:
            del self.cache[key]
            logger.debug(f"Cache entry expired: {key}")
            return None

        return value

    def _invalidate_cache(self) -> None:
        """Clear all cache entries after mutations."""
        self.cache.clear()
        logger.debug("Cache invalidated")

    def get_cache_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary containing:
            - hits: Total cache hits
            - misses: Total cache misses
            - evictions: Total cache evictions
            - hit_rate: Hit rate as percentage
            - size: Current cache size
            - max_size: Maximum cache size
        """
        total_accesses = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_accesses * 100) if total_accesses > 0 else 0.0

        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "evictions": self._cache_evictions,
            "hit_rate": hit_rate,
            "size": len(self.cache),
            "max_size": self.cache_size,
        }

    @staticmethod
    def _required_str(value: Any) -> str | None:
        """Return non-empty string values, otherwise None."""
        if isinstance(value, str) and value:
            return value
        return None

    def _result_to_node(self, result: dict[str, Any]) -> Node | None:
        """Convert query result to Node object.

        Args:
            result: Query result dictionary

        Returns:
            Node object or None if conversion fails
        """
        try:
            # Handle different result formats from different backends
            if "n" in result:
                n = result["n"]
            elif "upstream" in result:
                n = result["upstream"]
            elif "downstream" in result:
                n = result["downstream"]
            else:
                # Try to extract first node-like object
                for value in result.values():
                    if isinstance(value, dict) and "id" in value:
                        n = value
                        break
                else:
                    return None

            # Extract node properties
            if isinstance(n, dict):
                node_id = self._required_str(n.get("id"))
                node_type = self._required_str(n.get("type"))
                node_name = self._required_str(n.get("name"))
                metadata_raw = n.get("metadata", {})
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}

                if node_id is None or node_type is None or node_name is None:
                    return None

                return Node(
                    id=node_id,
                    type=node_type,
                    name=node_name,
                    metadata=metadata,
                )
            else:
                # Handle backend-specific node objects
                node_id = self._required_str(getattr(n, "id", None))
                node_type = self._required_str(getattr(n, "type", None))
                node_name = self._required_str(getattr(n, "name", None))
                metadata_raw = getattr(n, "metadata", {})
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}

                if node_id is None or node_type is None or node_name is None:
                    return None

                return Node(
                    id=node_id,
                    type=node_type,
                    name=node_name,
                    metadata=metadata,
                )

        except Exception as e:
            logger.debug(f"Failed to convert result to node: {e}")
            return None

    def _result_to_edge(self, result: dict[str, Any]) -> Edge | None:
        """Convert query result to Edge object.

        Args:
            result: Query result dictionary

        Returns:
            Edge object or None if conversion fails
        """
        try:
            # Extract source, edge, and target from result
            source = result.get("source")
            edge = result.get("r")
            target = result.get("target")

            if not all([source, edge, target]):
                return None

            # Extract edge properties
            source_id_raw = (
                source.get("id") if isinstance(source, dict) else getattr(source, "id", None)
            )
            target_id_raw = (
                target.get("id") if isinstance(target, dict) else getattr(target, "id", None)
            )
            edge_type_raw = (
                edge.get("edge_type")
                if isinstance(edge, dict)
                else getattr(edge, "edge_type", None)
            )

            source_id = self._required_str(source_id_raw)
            target_id = self._required_str(target_id_raw)
            edge_type = self._required_str(edge_type_raw)

            if source_id is None or target_id is None or edge_type is None:
                return None

            if isinstance(edge, dict):
                metadata_raw = edge.get("metadata", {})
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
                return Edge(
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=edge_type,
                    metadata=metadata,
                )
            else:
                # Handle backend-specific edge objects
                metadata_raw = getattr(edge, "metadata", {})
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
                return Edge(
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=edge_type,
                    metadata=metadata,
                )

        except Exception as e:
            logger.debug(f"Failed to convert result to edge: {e}")
            return None

    def get_backend_info(self) -> dict[str, Any]:
        """Get information about the underlying backend.

        Returns:
            Dictionary containing backend name, version, and status
        """
        return {
            "backend_name": self.backend.get_backend_name(),
            "backend_version": self.backend.get_backend_version(),
            "connected": self.backend.get_connection_status(),
            "metrics": self.backend.get_metrics(),
        }
