"""Neo4j graph database backend implementation."""

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


class Neo4jBackend(StorageBackend):
    """Neo4j graph database backend implementation.
    
    This backend uses the official neo4j Python driver to connect to Neo4j
    and execute Cypher queries. It supports ACID transactions and provides
    comprehensive error handling with conversion to StorageException types.
    
    Attributes:
        connection_string: Neo4j connection string (bolt://host:port)
        username: Authentication username
        password: Authentication password
        driver: Neo4j driver instance
        session: Neo4j session instance
        transaction: Current transaction (if any)
    """

    def __init__(
        self,
        connection_string: str,
        username: str = "neo4j",
        password: str = "",
    ) -> None:
        """Initialize Neo4j backend.
        
        Args:
            connection_string: Connection string (e.g., bolt://localhost:7687)
            username: Authentication username (default: neo4j)
            password: Authentication password (default: empty)
        """
        self.connection_string = connection_string
        self.username = username
        self.password = password
        self.driver = None
        self.session = None
        self.transaction = None
        self._operation_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    def connect(self) -> None:
        """Establish connection to Neo4j.
        
        Raises:
            ConnectionRefused: If Neo4j refuses the connection
            ConnectionTimeout: If connection attempt times out
            StorageException: For other connection errors
        """
        try:
            logger.info(f"Connecting to Neo4j at {self.connection_string}")

            # Import neo4j driver
            try:
                from neo4j import GraphDatabase
            except ImportError:
                raise ImportError(
                    "neo4j driver is required. Install with: pip install neo4j"
                )

            # Create driver
            self.driver = GraphDatabase.driver(
                self.connection_string,
                auth=(self.username, self.password),
                connection_timeout=30.0,
            )

            # Create session
            self.session = self.driver.session()

            # Verify connection with health check
            self.session.run("RETURN 1")

            logger.info("Successfully connected to Neo4j")

        except ImportError as e:
            logger.error(f"Import error: {e}")
            raise StorageException(str(e))
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Connection failed: {error_msg}")

            # Classify error
            if "refused" in error_msg.lower() or "connection refused" in error_msg.lower():
                raise ConnectionRefused(
                    f"Neo4j refused connection to {self.connection_string}",
                    context={"connection_string": self.connection_string},
                )
            elif "timeout" in error_msg.lower():
                raise ConnectionTimeout(
                    "Connection to Neo4j timed out",
                    context={"connection_string": self.connection_string},
                )
            else:
                raise StorageException(
                    f"Failed to connect to Neo4j: {error_msg}",
                    context={"connection_string": self.connection_string},
                )

    def disconnect(self) -> None:
        """Close connection to Neo4j.
        
        Raises:
            StorageException: If disconnection fails
        """
        try:
            logger.info("Disconnecting from Neo4j")

            if self.session:
                self.session.close()
                self.session = None

            if self.driver:
                self.driver.close()
                self.driver = None

            logger.info("Successfully disconnected from Neo4j")

        except Exception as e:
            logger.error(f"Disconnection failed: {e}")
            raise StorageException(
                f"Failed to disconnect from Neo4j: {e}",
                context={"error": str(e)},
            )

    def get_connection_status(self) -> bool:
        """Check if connected to Neo4j and backend is healthy.
        
        Returns:
            True if connected and healthy, False otherwise
        """
        try:
            if not self.session or not self.driver:
                return False

            # Execute health check query
            result = self.session.run("RETURN 1")
            result.consume()
            return True

        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    def get_backend_name(self) -> str:
        """Get backend name.
        
        Returns:
            "Neo4j"
        """
        return "Neo4j"

    def get_backend_version(self) -> str:
        """Get Neo4j server version.
        
        Returns:
            Version string (e.g., "5.0.0")
        """
        try:
            if not self.session:
                return "unknown"

            result = self.session.run("CALL dbms.components() YIELD versions RETURN versions[0]")
            record = result.single()
            if record:
                return str(record[0])
            return "unknown"

        except Exception as e:
            logger.debug(f"Failed to get version: {e}")
            return "unknown"

    def create_node(self, node: Node) -> None:
        """Create a new node in Neo4j.
        
        Args:
            node: Node object with id, type, name, metadata
            
        Raises:
            DuplicateNode: If node with same id already exists
            StorageException: For other creation errors
        """
        try:
            logger.debug(f"Creating node: {node.id}")

            query = """
            CREATE (n:Node {
                id: $id,
                type: $type,
                name: $name,
                metadata: $metadata
            })
            """

            self.session.run(
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

        except Exception as e:
            error_msg = str(e)
            self._error_count += 1
            logger.error(f"Failed to create node {node.id}: {error_msg}")

            # Check for duplicate node error
            if "already exists" in error_msg.lower() or "unique" in error_msg.lower():
                raise DuplicateNode(
                    f"Node with id '{node.id}' already exists",
                    context={"node_id": node.id},
                )

            raise StorageException(
                f"Failed to create node: {error_msg}",
                context={"node_id": node.id},
            )

    def read_node(self, node_id: str) -> Node | None:
        """Read a node from Neo4j.
        
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
            result = self.session.run(query, {"id": node_id})
            record = result.single()

            self._operation_count += 1

            if not record:
                logger.debug(f"Node not found: {node_id}")
                return None

            n = record["n"]
            node = Node(
                id=n["id"],
                type=n["type"],
                name=n["name"],
                metadata=dict(n.get("metadata", {})),
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
        """Update an existing node in Neo4j.
        
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
            """

            result = self.session.run(
                query,
                {
                    "id": node.id,
                    "type": node.type,
                    "name": node.name,
                    "metadata": node.metadata,
                },
            )

            # Check if node was found
            summary = result.consume()
            if summary.counters.nodes_created == 0 and summary.counters.properties_set == 0:
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
        """Delete a node from Neo4j.
        
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
            result = self.session.run(check_query, {"id": node_id})
            record = result.single()

            if record and record["has_edges"]:
                raise ReferentialIntegrityError(
                    f"Cannot delete node with edges: {node_id}",
                    context={"node_id": node_id},
                )

            # Delete the node
            delete_query = "MATCH (n:Node {id: $id}) DELETE n"
            self.session.run(delete_query, {"id": node_id})

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
        """Create a new edge between two nodes in Neo4j.
        
        Args:
            edge: Edge object with source_id, target_id, edge_type, metadata
            
        Raises:
            ReferentialIntegrityError: If source or target node doesn't exist
            StorageException: For creation errors
        """
        try:
            logger.debug(
                f"Creating edge: {edge.source_id} -> {edge.target_id} "
                f"({edge.edge_type})"
            )

            query = """
            MATCH (source:Node {id: $source_id})
            MATCH (target:Node {id: $target_id})
            CREATE (source)-[r:EDGE {
                edge_type: $edge_type,
                metadata: $metadata
            }]->(target)
            """

            result = self.session.run(
                query,
                {
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "edge_type": edge.edge_type,
                    "metadata": edge.metadata,
                },
            )

            summary = result.consume()
            if summary.counters.relationships_created == 0:
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
            logger.error(
                f"Failed to create edge {edge.source_id} -> {edge.target_id}: {error_msg}"
            )

            raise StorageException(
                f"Failed to create edge: {error_msg}",
                context={
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                },
            )

    def read_edge(self, source_id: str, target_id: str) -> Edge | None:
        """Read an edge between two nodes from Neo4j.
        
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

            result = self.session.run(
                query,
                {"source_id": source_id, "target_id": target_id},
            )
            record = result.single()

            self._operation_count += 1

            if not record:
                logger.debug(f"Edge not found: {source_id} -> {target_id}")
                return None

            r = record["r"]
            edge = Edge(
                source_id=source_id,
                target_id=target_id,
                edge_type=r["edge_type"],
                metadata=dict(r.get("metadata", {})),
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
        """Delete an edge between two nodes from Neo4j.
        
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

            self.session.run(
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
        """Execute a Cypher query against Neo4j.
        
        Args:
            query_str: Cypher query string
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

            result = self.session.run(query_str, params)
            records = [dict(record) for record in result]

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

            self.transaction = self.session.begin_transaction()
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

            self.transaction.commit()
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

            self.transaction.rollback()
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
            (self._error_count / self._operation_count * 100)
            if self._operation_count > 0
            else 0.0
        )

        return {
            "operation_count": self._operation_count,
            "error_count": self._error_count,
            "error_rate": error_rate,
            "backend_name": self.get_backend_name(),
            "backend_version": self.get_backend_version(),
        }
