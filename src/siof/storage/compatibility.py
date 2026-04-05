"""Backward compatibility layer for v1.0 Repository API."""

import logging
import warnings
from typing import Any

from siof.storage.backend import Edge, Node
from siof.storage.distributed_repository import DistributedRepository, IsolationLevel

logger = logging.getLogger(__name__)


class RepositoryAdapter:
    """Adapter providing v1.0 Repository API compatibility.

    This class wraps DistributedRepository and provides the same public API
    as the v1.0 Repository, allowing existing code to work with v2.0 backends
    without modification.

    Attributes:
        _repository: Underlying DistributedRepository instance
    """

    def __init__(self, repository: DistributedRepository) -> None:
        """Initialize RepositoryAdapter.

        Args:
            repository: DistributedRepository instance to wrap

        Raises:
            ValueError: If repository is None
        """
        if not repository:
            raise ValueError("repository cannot be None")

        self._repository = repository
        logger.info("RepositoryAdapter initialized")

    # ========================================================================
    # Node Operations (v1.0 API)
    # ========================================================================

    def add_node(
        self,
        node_id: str,
        node_type: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a node to the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.add_node().

        Args:
            node_id: Unique identifier for the node
            node_type: Type/label of the node
            name: Human-readable name
            metadata: Optional metadata dictionary

        Raises:
            ValueError: If parameters are invalid
        """
        if not node_id or not node_type or not name:
            raise ValueError("node_id, node_type, and name are required")

        node = Node(
            id=node_id,
            type=node_type,
            name=name,
            metadata=metadata or {},
        )

        self._repository.create_node(node)
        logger.debug(f"Added node: {node_id}")

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Get a node from the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.get_node().

        Args:
            node_id: The node ID to retrieve

        Returns:
            Dictionary with node properties or None if not found
        """
        node = self._repository.read_node(node_id)

        if not node:
            return None

        return {
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "metadata": node.metadata,
        }

    def update_node(
        self,
        node_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update a node in the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.update_node().

        Args:
            node_id: The node ID to update
            metadata: Updated metadata dictionary

        Raises:
            ValueError: If node not found
        """
        node = self._repository.read_node(node_id)

        if not node:
            raise ValueError(f"Node not found: {node_id}")

        # Update metadata
        if metadata:
            node.metadata.update(metadata)

        self._repository.update_node(node)
        logger.debug(f"Updated node: {node_id}")

    def delete_node(self, node_id: str) -> None:
        """Delete a node from the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.delete_node().

        Args:
            node_id: The node ID to delete

        Raises:
            ValueError: If node not found
        """
        node = self._repository.read_node(node_id)

        if not node:
            raise ValueError(f"Node not found: {node_id}")

        self._repository.delete_node(node_id)
        logger.debug(f"Deleted node: {node_id}")

    def get_all_nodes(self) -> list[dict[str, Any]]:
        """Get all nodes from the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.get_all_nodes().

        Returns:
            List of node dictionaries
        """
        nodes = self._repository.query_nodes({})

        return [
            {
                "id": node.id,
                "type": node.type,
                "name": node.name,
                "metadata": node.metadata,
            }
            for node in nodes
        ]

    # ========================================================================
    # Edge Operations (v1.0 API)
    # ========================================================================

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add an edge to the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.add_edge().

        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            edge_type: Type/label of the edge
            metadata: Optional metadata dictionary

        Raises:
            ValueError: If parameters are invalid
        """
        if not source_id or not target_id or not edge_type:
            raise ValueError("source_id, target_id, and edge_type are required")

        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            metadata=metadata or {},
        )

        self._repository.create_edge(edge)
        logger.debug(f"Added edge: {source_id} -> {target_id}")

    def get_edge(
        self,
        source_id: str,
        target_id: str,
    ) -> dict[str, Any] | None:
        """Get an edge from the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.get_edge().

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Returns:
            Dictionary with edge properties or None if not found
        """
        edge = self._repository.backend.read_edge(source_id, target_id)

        if not edge:
            return None

        return {
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "edge_type": edge.edge_type,
            "metadata": edge.metadata,
        }

    def delete_edge(self, source_id: str, target_id: str) -> None:
        """Delete an edge from the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.delete_edge().

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Raises:
            ValueError: If edge not found
        """
        edge = self._repository.backend.read_edge(source_id, target_id)

        if not edge:
            raise ValueError(f"Edge not found: {source_id} -> {target_id}")

        self._repository.delete_edge(source_id, target_id)
        logger.debug(f"Deleted edge: {source_id} -> {target_id}")

    def get_all_edges(self) -> list[dict[str, Any]]:
        """Get all edges from the repository (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.get_all_edges().

        Returns:
            List of edge dictionaries
        """
        edges = self._repository.query_edges({})

        return [
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "edge_type": edge.edge_type,
                "metadata": edge.metadata,
            }
            for edge in edges
        ]

    # ========================================================================
    # Query Operations (v1.0 API)
    # ========================================================================

    def get_lineage(self, node_id: str) -> list[dict[str, Any]]:
        """Get lineage for a node (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.get_lineage().

        Args:
            node_id: The node ID to get lineage for

        Returns:
            List of upstream node dictionaries
        """
        nodes = self._repository.find_lineage(node_id)

        return [
            {
                "id": node.id,
                "type": node.type,
                "name": node.name,
                "metadata": node.metadata,
            }
            for node in nodes
        ]

    def get_dependents(self, node_id: str) -> list[dict[str, Any]]:
        """Get dependents for a node (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.get_dependents().

        Args:
            node_id: The node ID to get dependents for

        Returns:
            List of downstream node dictionaries
        """
        nodes = self._repository.find_dependents(node_id)

        return [
            {
                "id": node.id,
                "type": node.type,
                "name": node.name,
                "metadata": node.metadata,
            }
            for node in nodes
        ]

    def find_path(self, source_id: str, target_id: str) -> list[dict[str, Any]] | None:
        """Find path between two nodes (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.find_path().

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Returns:
            List of node dictionaries representing the path, or None if no path exists
        """
        path = self._repository.find_path(source_id, target_id)

        if not path:
            return None

        return [
            {
                "id": node.id,
                "type": node.type,
                "name": node.name,
                "metadata": node.metadata,
            }
            for node in path
        ]

    def find_cycles(self) -> list[list[dict[str, Any]]]:
        """Find cycles in the graph (v1.0 API).

        This method provides backward compatibility with v1.0 Repository.find_cycles().

        Returns:
            List of cycles, where each cycle is a list of node dictionaries
        """
        cycles = self._repository.find_cycles()

        return [
            [
                {
                    "id": node.id,
                    "type": node.type,
                    "name": node.name,
                    "metadata": node.metadata,
                }
                for node in cycle
            ]
            for cycle in cycles
        ]

    # ========================================================================
    # Deprecated Methods (v1.0 API with warnings)
    # ========================================================================

    def query(self, query_str: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query (v1.0 API - DEPRECATED).

        This method is deprecated. Use find_lineage, find_dependents, or find_path instead.

        Args:
            query_str: Query string
            params: Query parameters

        Returns:
            List of result dictionaries
        """
        warnings.warn(
            "query() is deprecated. Use find_lineage(), find_dependents(), or find_path() instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        logger.warning("Deprecated method called: query()")

        results = self._repository.backend.query(query_str, params or {})
        return results

    def get_node_count(self) -> int:
        """Get total number of nodes (v1.0 API - DEPRECATED).

        This method is deprecated. Use get_all_nodes() and check length instead.

        Returns:
            Total number of nodes
        """
        warnings.warn(
            "get_node_count() is deprecated. Use len(get_all_nodes()) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        logger.warning("Deprecated method called: get_node_count()")

        nodes = self._repository.query_nodes({})
        return len(nodes)

    def get_edge_count(self) -> int:
        """Get total number of edges (v1.0 API - DEPRECATED).

        This method is deprecated. Use get_all_edges() and check length instead.

        Returns:
            Total number of edges
        """
        warnings.warn(
            "get_edge_count() is deprecated. Use len(get_all_edges()) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        logger.warning("Deprecated method called: get_edge_count()")

        edges = self._repository.query_edges({})
        return len(edges)

    # ========================================================================
    # Backend Information
    # ========================================================================

    def get_backend_info(self) -> dict[str, Any]:
        """Get information about the underlying backend.

        Args:

        Returns:
            Dictionary with backend information
        """
        return self._repository.get_backend_info()

    def get_cache_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Args:

        Returns:
            Dictionary with cache metrics
        """
        return self._repository.get_cache_metrics()

    def get_transaction_metrics(self) -> dict[str, Any]:
        """Get transaction metrics.

        Args:

        Returns:
            Dictionary with transaction metrics
        """
        return self._repository.get_transaction_metrics()

    # ========================================================================
    # Transaction Support (v2.0 API)
    # ========================================================================

    def begin_transaction(self) -> None:
        """Begin a transaction.

        Args:

        Raises:
            StorageException: If transaction cannot be started
        """
        self._repository.begin_transaction()

    def commit_transaction(self) -> None:
        """Commit the current transaction.

        Args:

        Raises:
            StorageException: If commit fails
        """
        self._repository.commit_transaction()

    def rollback_transaction(self) -> None:
        """Rollback the current transaction.

        Args:

        Raises:
            StorageException: If rollback fails
        """
        self._repository.rollback_transaction()

    def transaction(self, isolation_level: str = "read_committed"):
        """Context manager for transactions.

        Args:
            isolation_level: Transaction isolation level

        Returns:
            Context manager
        """
        # Map string to IsolationLevel enum
        level_map = {
            "read_uncommitted": IsolationLevel.READ_UNCOMMITTED,
            "read_committed": IsolationLevel.READ_COMMITTED,
            "repeatable_read": IsolationLevel.REPEATABLE_READ,
            "serializable": IsolationLevel.SERIALIZABLE,
        }

        level = level_map.get(isolation_level, IsolationLevel.READ_COMMITTED)
        return self._repository.transaction(level)
