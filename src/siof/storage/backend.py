"""Abstract storage backend interface for distributed graph storage."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    """Represents a vertex in the distributed graph.
    
    Attributes:
        id: Unique identifier for the node
        type: Node type/label (e.g., 'Symbol', 'File', 'Module')
        name: Human-readable name of the node
        metadata: Additional properties stored as key-value pairs
    """

    id: str
    type: str
    name: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate node properties."""
        if not self.id:
            raise ValueError("Node id cannot be empty")
        if not self.type:
            raise ValueError("Node type cannot be empty")
        if not self.name:
            raise ValueError("Node name cannot be empty")


@dataclass
class Edge:
    """Represents a directed edge in the distributed graph.
    
    Attributes:
        source_id: ID of the source node
        target_id: ID of the target node
        edge_type: Type/label of the edge (e.g., 'DEPENDS_ON', 'CALLS')
        metadata: Additional properties stored as key-value pairs
    """

    source_id: str
    target_id: str
    edge_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate edge properties."""
        if not self.source_id:
            raise ValueError("Edge source_id cannot be empty")
        if not self.target_id:
            raise ValueError("Edge target_id cannot be empty")
        if not self.edge_type:
            raise ValueError("Edge edge_type cannot be empty")


class StorageBackend(ABC):
    """Abstract base class for all storage backends.
    
    This interface defines the contract that all storage backend implementations
    must follow. Implementations can target different graph databases (Neo4j,
    FalkorDB, etc.) while maintaining a consistent API.
    
    All methods should raise appropriate StorageException subclasses on error.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the backend storage system.
        
        This method should initialize the connection and verify connectivity.
        It may be called multiple times; implementations should handle
        reconnection gracefully.
        
        Raises:
            ConnectionRefused: If the backend refuses the connection
            ConnectionTimeout: If connection attempt times out
            StorageException: For other connection-related errors
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the backend storage system.
        
        This method should gracefully close all connections and release
        resources. It should be idempotent and safe to call multiple times.
        
        Raises:
            StorageException: If disconnection fails
        """
        pass

    @abstractmethod
    def create_node(self, node: Node) -> None:
        """Create a new node in the graph.
        
        Args:
            node: Node object containing id, type, name, and metadata
            
        Raises:
            DuplicateNode: If a node with the same id already exists
            StorageException: For other creation errors
        """
        pass

    @abstractmethod
    def read_node(self, node_id: str) -> Optional[Node]:
        """Read a node by its ID.
        
        Args:
            node_id: The unique identifier of the node to read
            
        Returns:
            Node object if found, None if not found
            
        Raises:
            StorageException: For read errors
        """
        pass

    @abstractmethod
    def update_node(self, node: Node) -> None:
        """Update an existing node.
        
        Args:
            node: Node object with updated properties
            
        Raises:
            StorageException: If node not found or update fails
        """
        pass

    @abstractmethod
    def delete_node(self, node_id: str) -> None:
        """Delete a node by its ID.
        
        This operation should fail if the node has incoming or outgoing edges
        (referential integrity constraint).
        
        Args:
            node_id: The unique identifier of the node to delete
            
        Raises:
            ReferentialIntegrityError: If node has edges
            StorageException: For deletion errors
        """
        pass

    @abstractmethod
    def create_edge(self, edge: Edge) -> None:
        """Create a new edge between two nodes.
        
        Args:
            edge: Edge object containing source_id, target_id, edge_type, metadata
            
        Raises:
            ReferentialIntegrityError: If source or target node doesn't exist
            StorageException: For creation errors
        """
        pass

    @abstractmethod
    def read_edge(self, source_id: str, target_id: str) -> Optional[Edge]:
        """Read an edge between two nodes.
        
        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            
        Returns:
            Edge object if found, None if not found
            
        Raises:
            StorageException: For read errors
        """
        pass

    @abstractmethod
    def delete_edge(self, source_id: str, target_id: str) -> None:
        """Delete an edge between two nodes.
        
        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            
        Raises:
            StorageException: For deletion errors
        """
        pass

    @abstractmethod
    def query(self, query_str: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a query against the backend.
        
        The query language depends on the backend (Cypher for Neo4j, etc.).
        Results are returned as a list of dictionaries.
        
        Args:
            query_str: Query string in backend-specific language
            params: Query parameters as key-value pairs
            
        Returns:
            List of result dictionaries
            
        Raises:
            InvalidQuery: If query syntax is invalid
            QueryTimeout: If query execution times out
            QueryFailed: For other query execution errors
        """
        pass

    @abstractmethod
    def begin_transaction(self) -> None:
        """Begin a new transaction.
        
        All subsequent operations will be part of this transaction until
        commit_transaction() or rollback_transaction() is called.
        
        Raises:
            TransactionFailed: If transaction cannot be started
        """
        pass

    @abstractmethod
    def commit_transaction(self) -> None:
        """Commit the current transaction.
        
        All changes made since begin_transaction() will be persisted.
        
        Raises:
            TransactionFailed: If commit fails
            TransactionTimeout: If commit times out
        """
        pass

    @abstractmethod
    def rollback_transaction(self) -> None:
        """Rollback the current transaction.
        
        All changes made since begin_transaction() will be discarded.
        
        Raises:
            TransactionFailed: If rollback fails
        """
        pass

    @abstractmethod
    def get_backend_name(self) -> str:
        """Get the name of the backend implementation.
        
        Returns:
            Backend name (e.g., 'Neo4j', 'FalkorDB', 'SQLite')
        """
        pass

    @abstractmethod
    def get_backend_version(self) -> str:
        """Get the version of the backend implementation.
        
        Returns:
            Version string (e.g., '5.0.0', '1.0.0')
        """
        pass

    @abstractmethod
    def get_connection_status(self) -> bool:
        """Check if the backend is currently connected and healthy.
        
        This method should perform a lightweight health check (e.g., ping query).
        
        Returns:
            True if connected and healthy, False otherwise
        """
        pass

    @abstractmethod
    def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics from the backend.
        
        Returns a dictionary containing metrics such as:
        - operation_count: Total operations performed
        - operation_latency_ms: Average operation latency
        - error_count: Total errors encountered
        - error_rate: Error rate as percentage
        - active_connections: Current active connections
        - idle_connections: Current idle connections
        
        Returns:
            Dictionary of metrics
        """
        pass
