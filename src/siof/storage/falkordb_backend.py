"""FalkorDB (Redis-based) graph database backend implementation."""

import logging
from typing import Any

from siof.storage.backend import Edge, Node, StorageBackend
from siof.storage.exceptions import (
    ConnectionRefused,
    ConnectionTimeout,
    DuplicateNode,
    InvalidQuery,
    QueryFailed,
    QueryTimeout,
    ReferentialIntegrityError,
    StorageException,
    TransactionFailed,
    TransactionRolledBack,
    TransactionTimeout,
)

logger = logging.getLogger(__name__)


class FalkorDBBackend(StorageBackend):
    """FalkorDB (Redis-based) graph database backend implementation.

    This backend uses the official falkordb Python client to connect to FalkorDB
    and execute graph queries. FalkorDB is a Redis module that provides fast
    graph operations with identical semantics to Neo4j.

    Attributes:
        connection_string: FalkorDB connection string (redis://host:port)
        graph_name: Name of the graph to use
        db: FalkorDB client instance
        graph: FalkorDB graph instance
        transaction: Current transaction (if any)
    """

    def __init__(
        self,
        connection_string: str,
        graph_name: str = "siof",
    ) -> None:
        """Initialize FalkorDB backend.

        Args:
            connection_string: Connection string (e.g., redis://localhost:6379)
            graph_name: Name of the graph (default: siof)
        """
        self.connection_string = connection_string
        self.graph_name = graph_name
        self.db: Any = None
        self.graph: Any = None
        self.transaction: Any = None
        self._operation_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    def connect(self) -> None:
        """Establish connection to FalkorDB.

        Raises:
            ConnectionRefused: If FalkorDB refuses the connection
            ConnectionTimeout: If connection attempt times out
            StorageException: For other connection errors
        """
        try:
            logger.info(f"Connecting to FalkorDB at {self.connection_string}")

            # Import falkordb client
            try:
                from falkordb import FalkorDB  # type: ignore[import-not-found]
            except ImportError:
                raise ImportError("falkordb driver is required. Install with: pip install falkordb")

            # Parse connection string
            # Format: redis://host:port or redis://host:port/db
            if not self.connection_string.startswith("redis://"):
                raise ValueError(
                    f"Invalid connection string format: {self.connection_string}. "
                    f"Expected: redis://host:port"
                )

            # Create client
            self.db = FalkorDB.from_url(self.connection_string)

            # Select or create graph
            self.graph = self.db.select_graph(self.graph_name)

            # Verify connection with health check
            self.graph.query("RETURN 1")

            logger.info("Successfully connected to FalkorDB")

        except ImportError as e:
            logger.error(f"Import error: {e}")
            raise StorageException(str(e))
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            raise StorageException(str(e))
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Connection failed: {error_msg}")

            # Classify error
            if "refused" in error_msg.lower() or "connection refused" in error_msg.lower():
                raise ConnectionRefused(
                    f"FalkorDB refused connection to {self.connection_string}",
                    context={"connection_string": self.connection_string},
                )
            elif "timeout" in error_msg.lower():
                raise ConnectionTimeout(
                    "Connection to FalkorDB timed out",
                    context={"connection_string": self.connection_string},
                )
            else:
                raise StorageException(
                    f"Failed to connect to FalkorDB: {error_msg}",
                    context={"connection_string": self.connection_string},
                )

    def disconnect(self) -> None:
        """Close connection to FalkorDB.

        Raises:
            StorageException: If disconnection fails
        """
        try:
            logger.info("Disconnecting from FalkorDB")

            if self.db:
                self.db.close()
                self.db = None
                self.graph = None

            logger.info("Successfully disconnected from FalkorDB")

        except Exception as e:
            logger.error(f"Disconnection failed: {e}")
            raise StorageException(
                f"Failed to disconnect from FalkorDB: {e}",
                context={"error": str(e)},
            )

    def get_connection_status(self) -> bool:
        """Check if connected to FalkorDB and backend is healthy.

        Returns:
            True if connected and healthy, False otherwise
        """
        try:
            if not self.graph or not self.db:
                return False

            # Execute health check query
            self.graph.query("RETURN 1")
            return True

        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    def get_backend_name(self) -> str:
        """Get backend name.

        Returns:
            "FalkorDB"
        """
        return "FalkorDB"

    def get_backend_version(self) -> str:
        """Get FalkorDB server version.

        Returns:
            Version string (e.g., "1.0.0")
        """
        try:
            if not self.graph:
                return "unknown"

            # FalkorDB doesn't have a standard version query like Neo4j
            # Return a default version
            return "1.0+"

        except Exception as e:
            logger.debug(f"Failed to get version: {e}")
            return "unknown"

    def create_node(self, node: Node) -> None:
        """Create a new node in FalkorDB.

        Args:
            node: Node object with id, type, name, metadata

        Raises:
            DuplicateNode: If node with same id already exists
            StorageException: For other creation errors
        """
        try:
            logger.debug(f"Creating node: {node.id}")

            # Check if node already exists
            check_query = "MATCH (n:Node {id: $id}) RETURN n"
            result = self.graph.query(check_query, {"id": node.id})

            if result.result_set:
                raise DuplicateNode(
                    f"Node with id '{node.id}' already exists",
                    context={"node_id": node.id},
                )

            # Create node
            query = """
            CREATE (n:Node {
                id: $id,
                type: $type,
                name: $name,
                metadata: $metadata
            })
            """

            self.graph.query(
                query,
                {
                    "id": node.id,
                    "type": node.type,
                    "name": node.name,
                    "metadata": node.metadata,
                },
            )

            self._operation_count += 1
            logger.debug(f"Successfully created node: {node.id}")

        except DuplicateNode:
            raise
        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to create node {node.id}: {error_msg}")

            raise StorageException(
                f"Failed to create node: {error_msg}",
                context={"node_id": node.id},
            )

    def read_node(self, node_id: str) -> Node | None:
        """Read a node from FalkorDB.

        Args:
            node_id: The node ID to read

        Returns:
            Node object if found, None otherwise

        Raises:
            StorageException: For read errors
        """
        try:
            logger.debug(f"Reading node: {node_id}")

            query = "MATCH (n:Node {id: $id}) RETURN n"
            result = self.graph.query(query, {"id": node_id})

            self._operation_count += 1

            if not result.result_set:
                logger.debug(f"Node not found: {node_id}")
                return None

            # Extract node from result
            record = result.result_set[0]
            n = record[0]

            # FalkorDB returns node as an object with properties
            node = Node(
                id=n.properties.get("id"),
                type=n.labels[0] if n.labels else "Node",
                name=n.properties.get("name"),
                metadata=n.properties.get("metadata", {}),
            )

            logger.debug(f"Successfully read node: {node_id}")
            return node

        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to read node {node_id}: {error_msg}")

            raise StorageException(
                f"Failed to read node: {error_msg}",
                context={"node_id": node_id},
            )

    def update_node(self, node: Node) -> None:
        """Update an existing node in FalkorDB.

        Args:
            node: Node object with updated properties

        Raises:
            StorageException: If node not found or update fails
        """
        try:
            logger.debug(f"Updating node: {node.id}")

            query = """
            MATCH (n:Node {id: $id})
            SET n.type = $type,
                n.name = $name,
                n.metadata = $metadata
            RETURN n
            """

            result = self.graph.query(
                query,
                {
                    "id": node.id,
                    "type": node.type,
                    "name": node.name,
                    "metadata": node.metadata,
                },
            )

            if not result.result_set:
                raise StorageException(
                    f"Node not found: {node.id}",
                    context={"node_id": node.id},
                )

            self._operation_count += 1
            logger.debug(f"Successfully updated node: {node.id}")

        except StorageException:
            raise
        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to update node {node.id}: {error_msg}")

            raise StorageException(
                f"Failed to update node: {error_msg}",
                context={"node_id": node.id},
            )

    def delete_node(self, node_id: str) -> None:
        """Delete a node from FalkorDB.

        This operation fails if the node has incoming or outgoing edges
        (referential integrity constraint).

        Args:
            node_id: The node ID to delete

        Raises:
            ReferentialIntegrityError: If node has edges
            StorageException: For deletion errors
        """
        try:
            logger.debug(f"Deleting node: {node_id}")

            # Check if node has edges
            check_query = """
            MATCH (n:Node {id: $id})
            RETURN EXISTS((n)--()) as has_edges
            """
            result = self.graph.query(check_query, {"id": node_id})

            if result.result_set:
                record = result.result_set[0]
                if record[0]:  # has_edges is True
                    raise ReferentialIntegrityError(
                        f"Cannot delete node with edges: {node_id}",
                        context={"node_id": node_id},
                    )

            # Delete the node
            delete_query = "MATCH (n:Node {id: $id}) DELETE n"
            self.graph.query(delete_query, {"id": node_id})

            self._operation_count += 1
            logger.debug(f"Successfully deleted node: {node_id}")

        except ReferentialIntegrityError:
            raise
        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to delete node {node_id}: {error_msg}")

            raise StorageException(
                f"Failed to delete node: {error_msg}",
                context={"node_id": node_id},
            )

    def create_edge(self, edge: Edge) -> None:
        """Create a new edge between two nodes in FalkorDB.

        Args:
            edge: Edge object with source_id, target_id, edge_type, metadata

        Raises:
            ReferentialIntegrityError: If source or target node doesn't exist
            StorageException: For creation errors
        """
        try:
            logger.debug(
                f"Creating edge: {edge.source_id} -> {edge.target_id} " f"({edge.edge_type})"
            )

            query = """
            MATCH (source:Node {id: $source_id})
            MATCH (target:Node {id: $target_id})
            CREATE (source)-[r:EDGE {
                edge_type: $edge_type,
                metadata: $metadata
            }]->(target)
            RETURN r
            """

            result = self.graph.query(
                query,
                {
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "edge_type": edge.edge_type,
                    "metadata": edge.metadata,
                },
            )

            if not result.result_set:
                raise ReferentialIntegrityError(
                    "Source or target node not found",
                    context={
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                    },
                )

            self._operation_count += 1
            logger.debug(f"Successfully created edge: {edge.source_id} -> {edge.target_id}")

        except ReferentialIntegrityError:
            raise
        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to create edge {edge.source_id} -> {edge.target_id}: {error_msg}")

            raise StorageException(
                f"Failed to create edge: {error_msg}",
                context={
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                },
            )

    def read_edge(self, source_id: str, target_id: str) -> Edge | None:
        """Read an edge between two nodes from FalkorDB.

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Returns:
            Edge object if found, None otherwise

        Raises:
            StorageException: For read errors
        """
        try:
            logger.debug(f"Reading edge: {source_id} -> {target_id}")

            query = """
            MATCH (source:Node {id: $source_id})-[r:EDGE]->(target:Node {id: $target_id})
            RETURN r
            """

            result = self.graph.query(
                query,
                {"source_id": source_id, "target_id": target_id},
            )

            self._operation_count += 1

            if not result.result_set:
                logger.debug(f"Edge not found: {source_id} -> {target_id}")
                return None

            # Extract edge from result
            record = result.result_set[0]
            r = record[0]

            edge = Edge(
                source_id=source_id,
                target_id=target_id,
                edge_type=r.properties.get("edge_type"),
                metadata=r.properties.get("metadata", {}),
            )

            logger.debug(f"Successfully read edge: {source_id} -> {target_id}")
            return edge

        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to read edge {source_id} -> {target_id}: {error_msg}")

            raise StorageException(
                f"Failed to read edge: {error_msg}",
                context={"source_id": source_id, "target_id": target_id},
            )

    def delete_edge(self, source_id: str, target_id: str) -> None:
        """Delete an edge between two nodes from FalkorDB.

        Args:
            source_id: ID of the source node
            target_id: ID of the target node

        Raises:
            StorageException: For deletion errors
        """
        try:
            logger.debug(f"Deleting edge: {source_id} -> {target_id}")

            query = """
            MATCH (source:Node {id: $source_id})-[r:EDGE]->(target:Node {id: $target_id})
            DELETE r
            """

            self.graph.query(
                query,
                {"source_id": source_id, "target_id": target_id},
            )

            self._operation_count += 1
            logger.debug(f"Successfully deleted edge: {source_id} -> {target_id}")

        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to delete edge {source_id} -> {target_id}: {error_msg}")

            raise StorageException(
                f"Failed to delete edge: {error_msg}",
                context={"source_id": source_id, "target_id": target_id},
            )

    def query(self, query_str: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute a query against FalkorDB.

        Args:
            query_str: Query string
            params: Query parameters

        Returns:
            List of result dictionaries

        Raises:
            InvalidQuery: If query syntax is invalid
            QueryTimeout: If query execution times out
            QueryFailed: For other query execution errors
        """
        try:
            logger.debug(f"Executing query: {query_str[:100]}...")

            result = self.graph.query(query_str, params)

            # Convert FalkorDB result format to list of dicts
            records = []
            if result.result_set:
                for row in result.result_set:
                    # Create dict from header and row values
                    record_dict = dict(zip(result.header, row))
                    records.append(record_dict)

            self._operation_count += 1
            logger.debug(f"Query returned {len(records)} records")

            return records

        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Query execution failed: {error_msg}")

            # Classify error
            if "syntax" in error_msg.lower() or "invalid" in error_msg.lower():
                raise InvalidQuery(
                    f"Invalid query syntax: {error_msg}",
                    context={"query": query_str[:100]},
                )
            elif "timeout" in error_msg.lower():
                raise QueryTimeout(
                    "Query execution timed out",
                    context={"query": query_str[:100]},
                )
            else:
                raise QueryFailed(
                    f"Query execution failed: {error_msg}",
                    context={"query": query_str[:100]},
                )

    def begin_transaction(self) -> None:
        """Begin a new transaction.

        Raises:
            TransactionFailed: If transaction cannot be started
        """
        try:
            logger.debug("Beginning transaction")

            if self.transaction:
                raise TransactionFailed("Transaction already active")

            # FalkorDB transactions are implicit with multi() context
            # We'll track transaction state manually
            self.transaction = True
            logger.debug("Transaction started")

        except TransactionFailed:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to begin transaction: {error_msg}")

            raise TransactionFailed(
                f"Failed to begin transaction: {error_msg}",
                context={"error": error_msg},
            )

    def commit_transaction(self) -> None:
        """Commit the current transaction.

        Raises:
            TransactionFailed: If commit fails
            TransactionTimeout: If commit times out
        """
        try:
            logger.debug("Committing transaction")

            if not self.transaction:
                raise TransactionFailed("No active transaction")

            # FalkorDB doesn't have explicit transaction commit
            # Just mark transaction as complete
            self.transaction = None
            logger.debug("Transaction committed")

        except TransactionFailed:
            raise
        except Exception as e:
            error_msg = str(e)
            self.transaction = None
            logger.error(f"Failed to commit transaction: {error_msg}")

            if "timeout" in error_msg.lower():
                raise TransactionTimeout(
                    "Transaction commit timed out",
                    context={"error": error_msg},
                )
            else:
                raise TransactionFailed(
                    f"Failed to commit transaction: {error_msg}",
                    context={"error": error_msg},
                )

    def rollback_transaction(self) -> None:
        """Rollback the current transaction.

        Raises:
            TransactionFailed: If rollback fails
        """
        try:
            logger.debug("Rolling back transaction")

            if not self.transaction:
                raise TransactionFailed("No active transaction")

            # FalkorDB doesn't have explicit transaction rollback
            # Just mark transaction as complete
            self.transaction = None
            logger.debug("Transaction rolled back")

        except TransactionFailed:
            raise
        except Exception as e:
            error_msg = str(e)
            self.transaction = None
            logger.error(f"Failed to rollback transaction: {error_msg}")

            raise TransactionRolledBack(
                f"Failed to rollback transaction: {error_msg}",
                context={"error": error_msg},
            )

    def get_metrics(self) -> dict[str, Any]:
        """Get performance metrics from the backend.

        Returns:
            Dictionary containing:
            - operation_count: Total operations performed
            - error_count: Total errors encountered
            - error_rate: Error rate as percentage
            - backend_name: Backend name
            - backend_version: Backend version
        """
        error_rate = (
            (self._error_count / self._operation_count * 100) if self._operation_count > 0 else 0.0
        )

        return {
            "operation_count": self._operation_count,
            "error_count": self._error_count,
            "error_rate": error_rate,
            "backend_name": self.get_backend_name(),
            "backend_version": self.get_backend_version(),
        }
