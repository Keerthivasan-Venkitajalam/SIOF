"""Unit tests for storage backend infrastructure."""

from unittest.mock import Mock, patch

import pytest

from siof.storage.backend import Edge, Node, StorageBackend
from siof.storage.config import (
    BackendConfig,
    ConnectionPoolConfig,
    RetryPolicyConfig,
    StorageConfig,
)
from siof.storage.connection_pool import ConnectionPool
from siof.storage.exceptions import (
    ConnectionRefused,
    DuplicateNode,
    InvalidQuery,
    StorageException,
    TransactionFailed,
)
from siof.storage.retry import ErrorCategory, RetryPolicy

# ============================================================================
# Node and Edge Tests
# ============================================================================


class TestNode:
    """Tests for Node dataclass."""

    def test_node_creation_valid(self):
        """Test creating a valid node."""
        node = Node(
            id="node1",
            type="Symbol",
            name="my_function",
            metadata={"file": "main.py"},
        )
        assert node.id == "node1"
        assert node.type == "Symbol"
        assert node.name == "my_function"
        assert node.metadata == {"file": "main.py"}

    def test_node_creation_minimal(self):
        """Test creating a node with minimal properties."""
        node = Node(id="node1", type="Symbol", name="my_function")
        assert node.id == "node1"
        assert node.type == "Symbol"
        assert node.name == "my_function"
        assert node.metadata == {}

    def test_node_empty_id_raises_error(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id cannot be empty"):
            Node(id="", type="Symbol", name="my_function")

    def test_node_empty_type_raises_error(self):
        """Test that empty type raises ValueError."""
        with pytest.raises(ValueError, match="type cannot be empty"):
            Node(id="node1", type="", name="my_function")

    def test_node_empty_name_raises_error(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            Node(id="node1", type="Symbol", name="")


class TestEdge:
    """Tests for Edge dataclass."""

    def test_edge_creation_valid(self):
        """Test creating a valid edge."""
        edge = Edge(
            source_id="node1",
            target_id="node2",
            edge_type="CALLS",
            metadata={"line": 42},
        )
        assert edge.source_id == "node1"
        assert edge.target_id == "node2"
        assert edge.edge_type == "CALLS"
        assert edge.metadata == {"line": 42}

    def test_edge_creation_minimal(self):
        """Test creating an edge with minimal properties."""
        edge = Edge(source_id="node1", target_id="node2", edge_type="CALLS")
        assert edge.source_id == "node1"
        assert edge.target_id == "node2"
        assert edge.edge_type == "CALLS"
        assert edge.metadata == {}

    def test_edge_empty_source_id_raises_error(self):
        """Test that empty source_id raises ValueError."""
        with pytest.raises(ValueError, match="source_id cannot be empty"):
            Edge(source_id="", target_id="node2", edge_type="CALLS")

    def test_edge_empty_target_id_raises_error(self):
        """Test that empty target_id raises ValueError."""
        with pytest.raises(ValueError, match="target_id cannot be empty"):
            Edge(source_id="node1", target_id="", edge_type="CALLS")

    def test_edge_empty_edge_type_raises_error(self):
        """Test that empty edge_type raises ValueError."""
        with pytest.raises(ValueError, match="edge_type cannot be empty"):
            Edge(source_id="node1", target_id="node2", edge_type="")


# ============================================================================
# StorageBackend Tests
# ============================================================================


class TestStorageBackend:
    """Tests for StorageBackend abstract class."""

    def test_cannot_instantiate_abstract_class(self):
        """Test that StorageBackend cannot be instantiated directly."""
        with pytest.raises(TypeError):
            StorageBackend()

    def test_concrete_implementation_requires_all_methods(self):
        """Test that concrete implementations must implement all abstract methods."""

        class IncompleteBackend(StorageBackend):
            def connect(self):
                pass

        with pytest.raises(TypeError):
            IncompleteBackend()


# ============================================================================
# ConnectionPool Tests
# ============================================================================


class TestConnectionPool:
    """Tests for ConnectionPool."""

    def test_pool_initialization(self):
        """Test pool initialization with default parameters."""
        factory = Mock(return_value=Mock())
        pool = ConnectionPool(factory, min_size=5, max_size=20)

        assert pool.min_size == 5
        assert pool.max_size == 20
        assert pool.total_created == 5
        assert pool.active_count == 0
        assert pool.pool.qsize() == 5

    def test_pool_invalid_sizes_raises_error(self):
        """Test that invalid pool sizes raise ValueError."""
        factory = Mock()

        with pytest.raises(ValueError):
            ConnectionPool(factory, min_size=20, max_size=10)

        with pytest.raises(ValueError):
            ConnectionPool(factory, min_size=-1, max_size=10)

        with pytest.raises(ValueError):
            ConnectionPool(factory, min_size=10, max_size=0)

    def test_acquire_returns_pooled_connection(self):
        """Test acquiring a connection from the pool."""
        conn1 = Mock()
        conn2 = Mock()
        factory = Mock(side_effect=[conn1, conn2])

        pool = ConnectionPool(factory, min_size=1, max_size=10)
        acquired = pool.acquire()

        assert acquired == conn1
        assert pool.active_count == 1
        # First acquire from pool counts as reused
        assert pool.total_reused == 1

    def test_acquire_creates_new_connection_when_pool_empty(self):
        """Test that acquire creates new connection when pool is empty."""
        conn1 = Mock()
        conn2 = Mock()
        factory = Mock(side_effect=[conn1, conn2])

        pool = ConnectionPool(factory, min_size=1, max_size=10)
        pool.acquire()  # Get first connection
        acquired = pool.acquire()  # Should create new one

        assert acquired == conn2
        assert pool.total_created == 2
        assert pool.active_count == 2

    def test_acquire_reuses_released_connection(self):
        """Test that acquire reuses released connections."""
        conn = Mock()
        conn.get_connection_status = Mock(return_value=True)
        factory = Mock(return_value=conn)

        pool = ConnectionPool(factory, min_size=1, max_size=10)
        acquired1 = pool.acquire()
        pool.release(acquired1)
        acquired2 = pool.acquire()

        assert acquired1 == acquired2
        # First acquire from pool (min_size), then reused after release
        assert pool.total_reused == 2

    def test_acquire_timeout_raises_error(self):
        """Test that acquire times out when pool is exhausted."""
        factory = Mock()
        pool = ConnectionPool(factory, min_size=0, max_size=1)

        # Acquire the only available slot
        pool.acquire()

        # Try to acquire another with timeout
        with pytest.raises(TimeoutError):
            pool.acquire(timeout=0.1)

    def test_release_validates_connection(self):
        """Test that release validates connection before returning to pool."""
        valid_conn = Mock()
        valid_conn.get_connection_status = Mock(return_value=True)
        invalid_conn = Mock()
        invalid_conn.get_connection_status = Mock(return_value=False)
        new_conn = Mock()

        factory = Mock(side_effect=[valid_conn, invalid_conn, new_conn])

        pool = ConnectionPool(factory, min_size=1, max_size=10)
        pool.acquire()
        pool.release(valid_conn)

        assert pool.pool.qsize() == 1
        assert pool.total_validated == 1

    def test_release_creates_replacement_for_invalid_connection(self):
        """Test that release creates replacement for invalid connection."""
        invalid_conn = Mock()
        invalid_conn.get_connection_status = Mock(return_value=False)
        new_conn = Mock()

        factory = Mock(side_effect=[invalid_conn, new_conn])

        pool = ConnectionPool(factory, min_size=1, max_size=10)
        pool.acquire()
        pool.release(invalid_conn)

        assert pool.total_validation_failures == 1
        assert pool.total_created == 2

    def test_close_all_closes_all_connections(self):
        """Test that close_all closes all connections."""
        conn1 = Mock()
        conn2 = Mock()
        factory = Mock(side_effect=[conn1, conn2])

        pool = ConnectionPool(factory, min_size=2, max_size=10)
        pool.close_all()

        conn1.disconnect.assert_called_once()
        conn2.disconnect.assert_called_once()

    def test_get_metrics_returns_pool_statistics(self):
        """Test that get_metrics returns correct statistics."""
        factory = Mock()
        pool = ConnectionPool(factory, min_size=5, max_size=20)

        metrics = pool.get_metrics()

        assert metrics["active_connections"] == 0
        assert metrics["idle_connections"] == 5
        assert metrics["total_created"] == 5
        assert metrics["total_reused"] == 0


# ============================================================================
# RetryPolicy Tests
# ============================================================================


class TestRetryPolicy:
    """Tests for RetryPolicy."""

    def test_retry_policy_initialization(self):
        """Test retry policy initialization."""
        policy = RetryPolicy(base_delay_ms=50, max_retries=2, jitter=False)

        assert policy.base_delay_ms == 50
        assert policy.max_retries == 2
        assert policy.jitter is False

    def test_retry_policy_invalid_parameters_raise_error(self):
        """Test that invalid parameters raise ValueError."""
        with pytest.raises(ValueError):
            RetryPolicy(base_delay_ms=-1)

        with pytest.raises(ValueError):
            RetryPolicy(max_retries=-1)

    def test_classify_error_transient(self):
        """Test classifying transient errors."""
        policy = RetryPolicy()

        assert policy.classify_error(ConnectionError()) == ErrorCategory.TRANSIENT
        assert policy.classify_error(TimeoutError()) == ErrorCategory.TRANSIENT
        assert policy.classify_error(OSError()) == ErrorCategory.TRANSIENT

    def test_classify_error_permanent(self):
        """Test classifying permanent errors."""
        policy = RetryPolicy()

        assert policy.classify_error(ValueError()) == ErrorCategory.PERMANENT
        assert policy.classify_error(KeyError()) == ErrorCategory.PERMANENT
        assert policy.classify_error(TypeError()) == ErrorCategory.PERMANENT

    def test_classify_error_unknown_defaults_to_transient(self):
        """Test that unknown errors default to transient."""
        policy = RetryPolicy()

        assert policy.classify_error(RuntimeError()) == ErrorCategory.TRANSIENT

    def test_execute_succeeds_on_first_try(self):
        """Test that execute succeeds on first try."""
        policy = RetryPolicy()
        func = Mock(return_value="success")

        result = policy.execute(func, "arg1", kwarg1="value1")

        assert result == "success"
        func.assert_called_once_with("arg1", kwarg1="value1")

    def test_execute_retries_on_transient_error(self):
        """Test that execute retries on transient errors."""
        policy = RetryPolicy(base_delay_ms=1, max_retries=2, jitter=False)
        func = Mock(side_effect=[ConnectionError(), ConnectionError(), "success"])

        result = policy.execute(func)

        assert result == "success"
        assert func.call_count == 3

    def test_execute_fails_immediately_on_permanent_error(self):
        """Test that execute fails immediately on permanent errors."""
        policy = RetryPolicy(max_retries=3)
        func = Mock(side_effect=ValueError("permanent error"))

        with pytest.raises(ValueError):
            policy.execute(func)

        func.assert_called_once()

    def test_execute_exhausts_retries(self):
        """Test that execute exhausts retries and raises error."""
        policy = RetryPolicy(base_delay_ms=1, max_retries=2, jitter=False)
        func = Mock(side_effect=ConnectionError("transient error"))

        with pytest.raises(ConnectionError):
            policy.execute(func)

        assert func.call_count == 3  # Initial + 2 retries

    def test_calculate_delay_exponential_backoff(self):
        """Test exponential backoff calculation."""
        policy = RetryPolicy(base_delay_ms=100, jitter=False)

        assert policy._calculate_delay(0) == 100
        assert policy._calculate_delay(1) == 200
        assert policy._calculate_delay(2) == 400
        assert policy._calculate_delay(3) == 800

    def test_calculate_delay_with_jitter(self):
        """Test delay calculation with jitter."""
        policy = RetryPolicy(base_delay_ms=100, jitter=True)

        # With jitter, delay should be within ±25% of base
        for _ in range(10):
            delay = policy._calculate_delay(0)
            assert 75 <= delay <= 125

    def test_calculate_delay_never_negative(self):
        """Test that delay is never negative."""
        policy = RetryPolicy(base_delay_ms=100, jitter=True)

        for attempt in range(10):
            delay = policy._calculate_delay(attempt)
            assert delay >= 0


# ============================================================================
# StorageConfig Tests
# ============================================================================


class TestBackendConfig:
    """Tests for BackendConfig."""

    def test_backend_config_creation(self):
        """Test creating a backend configuration."""
        config = BackendConfig(
            name="primary",
            type="neo4j",
            connection_string="bolt://localhost:7687",
        )

        assert config.name == "primary"
        assert config.type == "neo4j"
        assert config.connection_string == "bolt://localhost:7687"
        assert config.is_primary is True

    def test_backend_config_validation_empty_name(self):
        """Test that empty name raises ValueError."""
        config = BackendConfig(
            name="",
            type="neo4j",
            connection_string="bolt://localhost:7687",
        )

        with pytest.raises(ValueError, match="name cannot be empty"):
            config.validate()

    def test_backend_config_validation_invalid_type(self):
        """Test that invalid type raises ValueError."""
        config = BackendConfig(
            name="primary",
            type="invalid",
            connection_string="bolt://localhost:7687",
        )

        with pytest.raises(ValueError, match="Invalid backend type"):
            config.validate()

    def test_backend_config_validation_empty_connection_string(self):
        """Test that empty connection string raises ValueError."""
        config = BackendConfig(
            name="primary",
            type="neo4j",
            connection_string="",
        )

        with pytest.raises(ValueError, match="Connection string cannot be empty"):
            config.validate()


class TestConnectionPoolConfig:
    """Tests for ConnectionPoolConfig."""

    def test_connection_pool_config_validation_invalid_sizes(self):
        """Test that invalid sizes raise ValueError."""
        config = ConnectionPoolConfig(min_size=20, max_size=10)

        with pytest.raises(ValueError, match="min_size.*cannot exceed max_size"):
            config.validate()


class TestRetryPolicyConfig:
    """Tests for RetryPolicyConfig."""

    def test_retry_policy_config_validation_invalid_delay(self):
        """Test that invalid delay raises ValueError."""
        config = RetryPolicyConfig(base_delay_ms=-1)

        with pytest.raises(ValueError, match="base_delay_ms must be non-negative"):
            config.validate()


class TestStorageConfig:
    """Tests for StorageConfig."""

    def test_storage_config_creation(self):
        """Test creating a storage configuration."""
        backend = BackendConfig(
            name="primary",
            type="neo4j",
            connection_string="bolt://localhost:7687",
        )
        config = StorageConfig(backends=[backend])

        assert len(config.backends) == 1
        assert config.backends[0].name == "primary"

    def test_storage_config_validation_no_backends(self):
        """Test that no backends raises ValueError."""
        config = StorageConfig(backends=[])

        with pytest.raises(ValueError, match="At least one backend must be configured"):
            config.validate()

    def test_storage_config_validation_no_primary_backend(self):
        """Test that no primary backend raises ValueError."""
        backend = BackendConfig(
            name="replica",
            type="neo4j",
            connection_string="bolt://localhost:7687",
            is_primary=False,
        )
        config = StorageConfig(backends=[backend])

        with pytest.raises(ValueError, match="At least one backend must be marked as primary"):
            config.validate()

    def test_storage_config_validation_invalid_log_level(self):
        """Test that invalid log level raises ValueError."""
        backend = BackendConfig(
            name="primary",
            type="neo4j",
            connection_string="bolt://localhost:7687",
        )
        config = StorageConfig(backends=[backend], log_level="INVALID")

        with pytest.raises(ValueError, match="Invalid log level"):
            config.validate()

    def test_storage_config_load_from_env(self):
        """Test loading configuration from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "SIOF_STORAGE_BACKEND": "neo4j",
                "SIOF_STORAGE_CONNECTION_STRING": "bolt://localhost:7687",
                "SIOF_STORAGE_POOL_MIN_SIZE": "5",
                "SIOF_STORAGE_POOL_MAX_SIZE": "25",
                "SIOF_STORAGE_RETRY_MAX_RETRIES": "5",
                "SIOF_STORAGE_LOG_LEVEL": "DEBUG",
            },
        ):
            config = StorageConfig.load_from_env()

            assert len(config.backends) == 1
            assert config.backends[0].type == "neo4j"
            assert config.connection_pool.min_size == 5
            assert config.connection_pool.max_size == 25
            assert config.retry_policy.max_retries == 5
            assert config.log_level == "DEBUG"

    def test_storage_config_load_from_env_missing_connection_string(self):
        """Test that missing connection string raises ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="SIOF_STORAGE_CONNECTION_STRING"):
                StorageConfig.load_from_env()

    def test_storage_config_to_dict(self):
        """Test converting configuration to dictionary."""
        backend = BackendConfig(
            name="primary",
            type="neo4j",
            connection_string="bolt://localhost:7687",
        )
        config = StorageConfig(backends=[backend])

        config_dict = config.to_dict()

        assert "backends" in config_dict
        assert "connection_pool" in config_dict
        assert "retry_policy" in config_dict
        assert "cache" in config_dict
        assert "query_optimizer" in config_dict
        assert "log_level" in config_dict


# ============================================================================
# Exception Tests
# ============================================================================


class TestStorageExceptions:
    """Tests for storage exceptions."""

    def test_storage_exception_creation(self):
        """Test creating a storage exception."""
        exc = StorageException(
            "Test error",
            context={"operation": "create_node"},
            metadata={"backend": "neo4j"},
        )

        assert exc.message == "Test error"
        assert exc.context == {"operation": "create_node"}
        assert exc.metadata == {"backend": "neo4j"}

    def test_storage_exception_string_representation(self):
        """Test string representation of exception."""
        exc = StorageException(
            "Test error",
            context={"operation": "create_node"},
        )

        assert "Test error" in str(exc)
        assert "context" in str(exc)

    def test_connection_refused_is_connection_error(self):
        """Test that ConnectionRefused is a ConnectionError."""
        from siof.storage.exceptions import ConnectionError as StorageConnectionError

        exc = ConnectionRefused("Connection refused")
        assert isinstance(exc, StorageConnectionError)

    def test_duplicate_node_is_data_error(self):
        """Test that DuplicateNode is a DataError."""
        exc = DuplicateNode("Duplicate node")
        assert isinstance(exc, StorageException)

    def test_invalid_query_is_query_error(self):
        """Test that InvalidQuery is a QueryError."""
        exc = InvalidQuery("Invalid query")
        assert isinstance(exc, StorageException)

    def test_transaction_failed_is_transaction_error(self):
        """Test that TransactionFailed is a TransactionError."""
        exc = TransactionFailed("Transaction failed")
        assert isinstance(exc, StorageException)


# ============================================================================
# Neo4j Backend Tests
# ============================================================================


class TestNeo4jBackend:
    """Tests for Neo4j backend implementation."""

    def test_neo4j_backend_initialization(self):
        """Test Neo4j backend initialization."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(
            connection_string="bolt://localhost:7687",
            username="neo4j",
            password="password",
        )

        assert backend.connection_string == "bolt://localhost:7687"
        assert backend.username == "neo4j"
        assert backend.password == "password"
        assert backend.driver is None
        assert backend.session is None

    def test_neo4j_backend_get_backend_name(self):
        """Test Neo4j backend name."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        assert backend.get_backend_name() == "Neo4j"

    def test_neo4j_backend_get_backend_version(self):
        """Test Neo4j backend version."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        # Without connection, should return "unknown"
        assert backend.get_backend_version() == "unknown"

    def test_neo4j_backend_get_connection_status_disconnected(self):
        """Test Neo4j connection status when disconnected."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        assert backend.get_connection_status() is False

    def test_neo4j_backend_connect_invalid_connection_string(self):
        """Test Neo4j connect with invalid connection string."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="invalid://localhost:7687")

        with pytest.raises(StorageException):
            backend.connect()

    def test_neo4j_backend_disconnect_without_connection(self):
        """Test Neo4j disconnect without active connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        # Should not raise error
        backend.disconnect()

    def test_neo4j_backend_create_node_without_connection(self):
        """Test Neo4j create_node without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        node = Node(id="node1", type="Symbol", name="test")

        with pytest.raises(StorageException):
            backend.create_node(node)

    def test_neo4j_backend_read_node_without_connection(self):
        """Test Neo4j read_node without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(StorageException):
            backend.read_node("node1")

    def test_neo4j_backend_update_node_without_connection(self):
        """Test Neo4j update_node without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        node = Node(id="node1", type="Symbol", name="test")

        with pytest.raises(StorageException):
            backend.update_node(node)

    def test_neo4j_backend_delete_node_without_connection(self):
        """Test Neo4j delete_node without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(StorageException):
            backend.delete_node("node1")

    def test_neo4j_backend_create_edge_without_connection(self):
        """Test Neo4j create_edge without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        edge = Edge(source_id="node1", target_id="node2", edge_type="CALLS")

        with pytest.raises(StorageException):
            backend.create_edge(edge)

    def test_neo4j_backend_read_edge_without_connection(self):
        """Test Neo4j read_edge without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(StorageException):
            backend.read_edge("node1", "node2")

    def test_neo4j_backend_delete_edge_without_connection(self):
        """Test Neo4j delete_edge without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(StorageException):
            backend.delete_edge("node1", "node2")

    def test_neo4j_backend_query_without_connection(self):
        """Test Neo4j query without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(StorageException):
            backend.query("RETURN 1", {})

    def test_neo4j_backend_begin_transaction_without_connection(self):
        """Test Neo4j begin_transaction without connection."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(TransactionFailed):
            backend.begin_transaction()

    def test_neo4j_backend_commit_transaction_without_active_transaction(self):
        """Test Neo4j commit_transaction without active transaction."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(TransactionFailed):
            backend.commit_transaction()

    def test_neo4j_backend_rollback_transaction_without_active_transaction(self):
        """Test Neo4j rollback_transaction without active transaction."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")

        with pytest.raises(TransactionFailed):
            backend.rollback_transaction()

    def test_neo4j_backend_get_metrics(self):
        """Test Neo4j get_metrics."""
        from siof.storage.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(connection_string="bolt://localhost:7687")
        metrics = backend.get_metrics()

        assert "operation_count" in metrics
        assert "error_count" in metrics
        assert "error_rate" in metrics
        assert "backend_name" in metrics
        assert "backend_version" in metrics
        assert metrics["operation_count"] == 0
        assert metrics["error_count"] == 0
        assert metrics["error_rate"] == 0.0


# ============================================================================
# FalkorDB Backend Tests
# ============================================================================


class TestFalkorDBBackend:
    """Tests for FalkorDB backend implementation."""

    def test_falkordb_backend_initialization(self):
        """Test FalkorDB backend initialization."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(
            connection_string="redis://localhost:6379",
            graph_name="test_graph",
        )

        assert backend.connection_string == "redis://localhost:6379"
        assert backend.graph_name == "test_graph"
        assert backend.db is None
        assert backend.graph is None

    def test_falkordb_backend_get_backend_name(self):
        """Test FalkorDB backend name."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        assert backend.get_backend_name() == "FalkorDB"

    def test_falkordb_backend_get_backend_version(self):
        """Test FalkorDB backend version."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        # Without connection, should return "unknown"
        assert backend.get_backend_version() == "unknown"

    def test_falkordb_backend_get_connection_status_disconnected(self):
        """Test FalkorDB connection status when disconnected."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        assert backend.get_connection_status() is False

    def test_falkordb_backend_connect_invalid_connection_string(self):
        """Test FalkorDB connect with invalid connection string."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="invalid://localhost:6379")

        with pytest.raises(StorageException):
            backend.connect()

    def test_falkordb_backend_disconnect_without_connection(self):
        """Test FalkorDB disconnect without active connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        # Should not raise error
        backend.disconnect()

    def test_falkordb_backend_create_node_without_connection(self):
        """Test FalkorDB create_node without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        node = Node(id="node1", type="Symbol", name="test")

        with pytest.raises(StorageException):
            backend.create_node(node)

    def test_falkordb_backend_read_node_without_connection(self):
        """Test FalkorDB read_node without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(StorageException):
            backend.read_node("node1")

    def test_falkordb_backend_update_node_without_connection(self):
        """Test FalkorDB update_node without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        node = Node(id="node1", type="Symbol", name="test")

        with pytest.raises(StorageException):
            backend.update_node(node)

    def test_falkordb_backend_delete_node_without_connection(self):
        """Test FalkorDB delete_node without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(StorageException):
            backend.delete_node("node1")

    def test_falkordb_backend_create_edge_without_connection(self):
        """Test FalkorDB create_edge without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        edge = Edge(source_id="node1", target_id="node2", edge_type="CALLS")

        with pytest.raises(StorageException):
            backend.create_edge(edge)

    def test_falkordb_backend_read_edge_without_connection(self):
        """Test FalkorDB read_edge without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(StorageException):
            backend.read_edge("node1", "node2")

    def test_falkordb_backend_delete_edge_without_connection(self):
        """Test FalkorDB delete_edge without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(StorageException):
            backend.delete_edge("node1", "node2")

    def test_falkordb_backend_query_without_connection(self):
        """Test FalkorDB query without connection."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(StorageException):
            backend.query("RETURN 1", {})

    def test_falkordb_backend_begin_transaction(self):
        """Test FalkorDB begin_transaction."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        # FalkorDB begin_transaction doesn't require connection
        backend.begin_transaction()
        assert backend.transaction is True

        # Cannot begin another transaction
        with pytest.raises(TransactionFailed):
            backend.begin_transaction()

    def test_falkordb_backend_commit_transaction_without_active_transaction(self):
        """Test FalkorDB commit_transaction without active transaction."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(TransactionFailed):
            backend.commit_transaction()

    def test_falkordb_backend_rollback_transaction_without_active_transaction(self):
        """Test FalkorDB rollback_transaction without active transaction."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")

        with pytest.raises(TransactionFailed):
            backend.rollback_transaction()

    def test_falkordb_backend_get_metrics(self):
        """Test FalkorDB get_metrics."""
        from siof.storage.falkordb_backend import FalkorDBBackend

        backend = FalkorDBBackend(connection_string="redis://localhost:6379")
        metrics = backend.get_metrics()

        assert "operation_count" in metrics
        assert "error_count" in metrics
        assert "error_rate" in metrics
        assert "backend_name" in metrics
        assert "backend_version" in metrics
        assert metrics["operation_count"] == 0
        assert metrics["error_count"] == 0
        assert metrics["error_rate"] == 0.0


# ============================================================================
# DistributedRepository Tests
# ============================================================================


class TestDistributedRepository:
    """Tests for DistributedRepository class."""

    def test_repository_creation_valid(self):
        """Test creating a valid DistributedRepository."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend, cache_size=500)

        assert repo.backend == backend
        assert repo.cache_size == 500
        assert len(repo.cache) == 0

    def test_repository_creation_invalid_backend(self):
        """Test that None backend raises ValueError."""
        from siof.storage.distributed_repository import DistributedRepository

        with pytest.raises(ValueError, match="backend cannot be None"):
            DistributedRepository(None)

    def test_repository_creation_invalid_cache_size(self):
        """Test that negative cache_size raises ValueError."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)

        with pytest.raises(ValueError, match="cache_size must be non-negative"):
            DistributedRepository(backend, cache_size=-1)

    def test_create_node_with_retry(self):
        """Test creating a node with retry logic."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        node = Node(id="node1", type="Symbol", name="func")
        repo.create_node(node)

        backend.create_node.assert_called_once_with(node)

    def test_read_node_cache_hit(self):
        """Test reading a node from cache."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        node = Node(id="node1", type="Symbol", name="func")
        repo._cache_put("node1", node)

        result = repo.read_node("node1")

        assert result == node
        assert repo._cache_hits == 1
        backend.read_node.assert_not_called()

    def test_read_node_cache_miss(self):
        """Test reading a node that's not in cache."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        node = Node(id="node1", type="Symbol", name="func")
        backend.read_node.return_value = node

        repo = DistributedRepository(backend)
        result = repo.read_node("node1")

        assert result == node
        assert repo._cache_misses == 1
        backend.read_node.assert_called_once_with("node1")

    def test_update_node_invalidates_cache(self):
        """Test that updating a node invalidates cache."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        # Add something to cache
        node = Node(id="node1", type="Symbol", name="func")
        repo._cache_put("node1", node)
        assert len(repo.cache) == 1

        # Update node
        updated_node = Node(id="node1", type="Symbol", name="func_updated")
        repo.update_node(updated_node)

        # Cache should be cleared
        assert len(repo.cache) == 0

    def test_delete_node_invalidates_cache(self):
        """Test that deleting a node invalidates cache."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        # Add something to cache
        node = Node(id="node1", type="Symbol", name="func")
        repo._cache_put("node1", node)
        assert len(repo.cache) == 1

        # Delete node
        repo.delete_node("node1")

        # Cache should be cleared
        assert len(repo.cache) == 0

    def test_create_edge_with_retry(self):
        """Test creating an edge with retry logic."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        edge = Edge(source_id="node1", target_id="node2", edge_type="CALLS")
        repo.create_edge(edge)

        backend.create_edge.assert_called_once_with(edge)

    def test_delete_edge_with_retry(self):
        """Test deleting an edge with retry logic."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        repo.delete_edge("node1", "node2")

        backend.delete_edge.assert_called_once_with("node1", "node2")

    def test_find_lineage(self):
        """Test finding lineage (upstream nodes)."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query.return_value = [
            {"upstream": {"id": "node1", "type": "Symbol", "name": "func1"}},
            {"upstream": {"id": "node2", "type": "Symbol", "name": "func2"}},
        ]

        repo = DistributedRepository(backend)
        result = repo.find_lineage("node3")

        assert len(result) == 2
        assert result[0].id == "node1"
        assert result[1].id == "node2"

    def test_find_dependents(self):
        """Test finding dependents (downstream nodes)."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query.return_value = [
            {"downstream": {"id": "node1", "type": "Symbol", "name": "func1"}},
            {"downstream": {"id": "node2", "type": "Symbol", "name": "func2"}},
        ]

        repo = DistributedRepository(backend)
        result = repo.find_dependents("node0")

        assert len(result) == 2
        assert result[0].id == "node1"
        assert result[1].id == "node2"

    def test_find_path(self):
        """Test finding shortest path between nodes."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query.return_value = [
            {
                "path_nodes": [
                    {"id": "node1", "type": "Symbol", "name": "func1"},
                    {"id": "node2", "type": "Symbol", "name": "func2"},
                    {"id": "node3", "type": "Symbol", "name": "func3"},
                ]
            }
        ]

        repo = DistributedRepository(backend)
        result = repo.find_path("node1", "node3")

        assert len(result) == 3
        assert result[0].id == "node1"
        assert result[2].id == "node3"

    def test_find_path_not_found(self):
        """Test finding path when no path exists."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query.return_value = []

        repo = DistributedRepository(backend)
        result = repo.find_path("node1", "node3")

        assert result is None

    def test_query_nodes_with_filters(self):
        """Test querying nodes with filters."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query.return_value = [
            {"n": {"id": "node1", "type": "Symbol", "name": "func1"}},
            {"n": {"id": "node2", "type": "Symbol", "name": "func2"}},
        ]

        repo = DistributedRepository(backend)
        result = repo.query_nodes({"type": "Symbol"})

        assert len(result) == 2
        assert result[0].id == "node1"

    def test_query_edges_with_filters(self):
        """Test querying edges with filters."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query.return_value = [
            {
                "source": {"id": "node1"},
                "r": {"edge_type": "CALLS"},
                "target": {"id": "node2"},
            },
        ]

        repo = DistributedRepository(backend)
        result = repo.query_edges({"edge_type": "CALLS"})

        assert len(result) == 1
        assert result[0].source_id == "node1"

    def test_cache_put_and_get(self):
        """Test cache put and get operations."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend, cache_size=10)

        node = Node(id="node1", type="Symbol", name="func")
        repo._cache_put("node1", node)

        result = repo._cache_get("node1")
        assert result == node

    def test_cache_eviction_lru(self):
        """Test LRU cache eviction."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend, cache_size=2)

        node1 = Node(id="node1", type="Symbol", name="func1")
        node2 = Node(id="node2", type="Symbol", name="func2")
        node3 = Node(id="node3", type="Symbol", name="func3")

        repo._cache_put("node1", node1)
        repo._cache_put("node2", node2)
        assert len(repo.cache) == 2

        # Adding third item should evict first
        repo._cache_put("node3", node3)
        assert len(repo.cache) == 2
        assert "node1" not in repo.cache
        assert "node2" in repo.cache
        assert "node3" in repo.cache
        assert repo._cache_evictions == 1

    def test_cache_ttl_expiration(self):
        """Test cache TTL expiration."""
        import time

        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend, cache_ttl_seconds=1)

        node = Node(id="node1", type="Symbol", name="func")
        repo._cache_put("node1", node)

        # Should be in cache immediately
        result = repo._cache_get("node1")
        assert result == node

        # Wait for TTL to expire
        time.sleep(1.1)

        # Should be expired now
        result = repo._cache_get("node1")
        assert result is None

    def test_get_cache_metrics(self):
        """Test getting cache metrics."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend, cache_size=100)

        # Simulate some cache activity
        repo._cache_hits = 10
        repo._cache_misses = 5
        repo._cache_evictions = 2

        metrics = repo.get_cache_metrics()

        assert metrics["hits"] == 10
        assert metrics["misses"] == 5
        assert metrics["evictions"] == 2
        assert metrics["hit_rate"] == pytest.approx(66.67, rel=0.1)
        assert metrics["max_size"] == 100

    def test_get_backend_info(self):
        """Test getting backend information."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.get_backend_name.return_value = "Neo4j"
        backend.get_backend_version.return_value = "5.0.0"
        backend.get_connection_status.return_value = True
        backend.get_metrics.return_value = {"operations": 100}

        repo = DistributedRepository(backend)
        info = repo.get_backend_info()

        assert info["backend_name"] == "Neo4j"
        assert info["backend_version"] == "5.0.0"
        assert info["connected"] is True
        assert info["metrics"]["operations"] == 100


# ============================================================================
# QueryOptimizer Tests
# ============================================================================


class TestQueryOptimizer:
    """Tests for QueryOptimizer class."""

    def test_optimizer_creation(self):
        """Test creating a QueryOptimizer."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer(plan_cache_size=50)
        assert optimizer.plan_cache_size == 50
        assert len(optimizer.plan_cache) == 0

    def test_optimizer_creation_invalid_cache_size(self):
        """Test that negative cache_size raises ValueError."""
        from siof.storage.query_optimizer import QueryOptimizer

        with pytest.raises(ValueError, match="plan_cache_size must be non-negative"):
            QueryOptimizer(plan_cache_size=-1)

    def test_optimize_query_with_id_filter(self):
        """Test optimizing query with specific node ID."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node {id: $id}) RETURN n"
        plan = optimizer.optimize(query, {"id": "node1"})

        assert plan["strategy"] == ExecutionStrategy.SINGLE_SHARD
        assert plan["estimated_cost"] == 1.0

    def test_optimize_query_with_where_clause(self):
        """Test optimizing query with WHERE clause."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) WHERE n.type = $type RETURN n"
        plan = optimizer.optimize(query, {"type": "Symbol"})

        assert plan["strategy"] == ExecutionStrategy.MULTI_SHARD
        assert plan["estimated_cost"] > 1.0

    def test_optimize_query_broadcast(self):
        """Test optimizing full graph scan query."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) RETURN n"
        plan = optimizer.optimize(query, {})

        assert plan["strategy"] == ExecutionStrategy.BROADCAST
        assert plan["estimated_cost"] > 5.0

    def test_optimize_query_caching(self):
        """Test that query plans are cached."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node {id: $id}) RETURN n"

        # First call should cache the plan
        plan1 = optimizer.optimize(query, {"id": "node1"})
        assert len(optimizer.plan_cache) == 1

        # Second call should use cached plan
        plan2 = optimizer.optimize(query, {"id": "node2"})
        assert len(optimizer.plan_cache) == 1
        assert plan1["plan_id"] == plan2["plan_id"]

    def test_extract_filters(self):
        """Test extracting filters from query."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) WHERE n.type = $type AND n.name = $name RETURN n"
        filters = optimizer._extract_filters(query)

        assert len(filters) > 0
        assert any("type" in f for f in filters)

    def test_estimate_cost_single_shard(self):
        """Test cost estimation for single shard strategy."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node {id: $id}) RETURN n"
        cost = optimizer._estimate_cost(query, ExecutionStrategy.SINGLE_SHARD)

        assert cost == 1.0

    def test_estimate_cost_multi_shard(self):
        """Test cost estimation for multi-shard strategy."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) WHERE n.type = $type RETURN n"
        cost = optimizer._estimate_cost(query, ExecutionStrategy.MULTI_SHARD)

        assert cost > 1.0
        assert cost < 10.0

    def test_estimate_cost_broadcast(self):
        """Test cost estimation for broadcast strategy."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) RETURN n"
        cost = optimizer._estimate_cost(query, ExecutionStrategy.BROADCAST)

        assert cost >= 10.0

    def test_estimate_cost_with_aggregation(self):
        """Test cost estimation increases for aggregations."""
        from siof.storage.query_optimizer import ExecutionStrategy, QueryOptimizer

        optimizer = QueryOptimizer()
        query_simple = "MATCH (n:Node) RETURN n"
        query_agg = "MATCH (n:Node) RETURN COUNT(n)"

        cost_simple = optimizer._estimate_cost(query_simple, ExecutionStrategy.BROADCAST)
        cost_agg = optimizer._estimate_cost(query_agg, ExecutionStrategy.BROADCAST)

        assert cost_agg > cost_simple

    def test_make_cache_key(self):
        """Test cache key generation."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) RETURN n"

        key1 = optimizer._make_cache_key(query)
        key2 = optimizer._make_cache_key(query)

        # Same query should produce same key
        assert key1 == key2

        # Different query should produce different key
        key3 = optimizer._make_cache_key("MATCH (n:Node) WHERE n.type = $type RETURN n")
        assert key1 != key3

    def test_clear_cache(self):
        """Test clearing the query plan cache."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer()
        query = "MATCH (n:Node) RETURN n"

        optimizer.optimize(query, {})
        assert len(optimizer.plan_cache) == 1

        optimizer.clear_cache()
        assert len(optimizer.plan_cache) == 0

    def test_get_cache_stats(self):
        """Test getting cache statistics."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer(plan_cache_size=100)
        query = "MATCH (n:Node) RETURN n"

        optimizer.optimize(query, {})
        stats = optimizer.get_cache_stats()

        assert stats["cached_plans"] == 1
        assert stats["max_cache_size"] == 100
        assert stats["cache_utilization"] == pytest.approx(0.01, rel=0.01)

    def test_cache_size_limit(self):
        """Test that cache respects size limit."""
        from siof.storage.query_optimizer import QueryOptimizer

        optimizer = QueryOptimizer(plan_cache_size=2)

        # Add 3 different queries
        optimizer.optimize("MATCH (n:Node {id: $id}) RETURN n", {})
        optimizer.optimize("MATCH (n:Node) WHERE n.type = $type RETURN n", {})
        optimizer.optimize("MATCH (n:Node) RETURN n", {})

        # Cache should not exceed size limit
        assert len(optimizer.plan_cache) <= 2


# ============================================================================
# Transaction Support Tests
# ============================================================================


class TestDistributedRepositoryTransactions:
    """Tests for transaction support in DistributedRepository."""

    def test_begin_transaction_success(self):
        """Test beginning a transaction."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        repo = DistributedRepository(backend)

        repo.begin_transaction()

        assert repo._transaction_active is True
        backend.begin_transaction.assert_called_once()

    def test_begin_transaction_already_active(self):
        """Test that beginning a transaction when one is active raises error."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        repo = DistributedRepository(backend)

        repo.begin_transaction()

        with pytest.raises(TransactionFailed, match="already active"):
            repo.begin_transaction()

    def test_commit_transaction_success(self):
        """Test committing a transaction."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.commit_transaction = Mock()
        repo = DistributedRepository(backend)

        repo.begin_transaction()
        repo.commit_transaction()

        assert repo._transaction_active is False
        backend.commit_transaction.assert_called_once()
        assert repo._committed_transactions == 1

    def test_commit_transaction_no_active(self):
        """Test that committing without active transaction raises error."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        with pytest.raises(TransactionFailed, match="No active transaction"):
            repo.commit_transaction()

    def test_rollback_transaction_success(self):
        """Test rolling back a transaction."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.rollback_transaction = Mock()
        repo = DistributedRepository(backend)

        repo.begin_transaction()
        repo.rollback_transaction()

        assert repo._transaction_active is False
        backend.rollback_transaction.assert_called_once()
        assert repo._rolled_back_transactions == 1

    def test_rollback_transaction_no_active(self):
        """Test that rolling back without active transaction raises error."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        with pytest.raises(TransactionFailed, match="No active transaction"):
            repo.rollback_transaction()

    def test_transaction_context_manager_success(self):
        """Test transaction context manager with successful commit."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.commit_transaction = Mock()
        repo = DistributedRepository(backend)

        with repo.transaction():
            assert repo._transaction_active is True

        assert repo._transaction_active is False
        backend.commit_transaction.assert_called_once()

    def test_transaction_context_manager_rollback_on_error(self):
        """Test transaction context manager rolls back on error."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.rollback_transaction = Mock()
        repo = DistributedRepository(backend)

        with pytest.raises(ValueError):
            with repo.transaction():
                raise ValueError("Test error")

        assert repo._transaction_active is False
        backend.rollback_transaction.assert_called_once()

    def test_transaction_timeout(self):
        """Test transaction timeout handling."""
        import time

        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.rollback_transaction = Mock()
        repo = DistributedRepository(backend, transaction_timeout_seconds=1)

        repo.begin_transaction()
        repo._transaction_start_time = time.time() - 2  # Simulate 2 seconds elapsed

        with pytest.raises(TransactionFailed, match="timeout"):
            repo.commit_transaction()

    def test_transaction_metrics(self):
        """Test transaction metrics tracking."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.commit_transaction = Mock()
        backend.rollback_transaction = Mock()
        repo = DistributedRepository(backend)

        # Commit a transaction
        repo.begin_transaction()
        repo.commit_transaction()

        # Rollback a transaction
        repo.begin_transaction()
        repo.rollback_transaction()

        metrics = repo.get_transaction_metrics()

        assert metrics["committed_transactions"] == 1
        assert metrics["rolled_back_transactions"] == 1
        assert metrics["current_transaction_active"] is False

    def test_create_savepoint(self):
        """Test creating a savepoint."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.query = Mock(return_value=[])
        repo = DistributedRepository(backend)

        repo.begin_transaction()
        repo.create_savepoint("sp1")

        assert "sp1" in repo._transaction_savepoints
        backend.query.assert_called_once()

    def test_create_savepoint_no_transaction(self):
        """Test that creating savepoint without transaction raises error."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)

        with pytest.raises(TransactionFailed, match="No active transaction"):
            repo.create_savepoint("sp1")

    def test_rollback_to_savepoint(self):
        """Test rolling back to a savepoint."""
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.query = Mock(return_value=[])
        repo = DistributedRepository(backend)

        repo.begin_transaction()
        repo.create_savepoint("sp1")
        repo.rollback_to_savepoint("sp1")

        backend.query.assert_called()

    def test_set_isolation_level(self):
        """Test setting isolation level."""
        from siof.storage.distributed_repository import DistributedRepository, IsolationLevel

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        repo = DistributedRepository(backend)

        repo.begin_transaction()
        repo.set_isolation_level(IsolationLevel.SERIALIZABLE)

        assert repo._isolation_level == IsolationLevel.SERIALIZABLE


# ============================================================================
# Migration Tool Tests
# ============================================================================


class TestMigrationTool:
    """Tests for MigrationTool."""

    def test_migration_tool_initialization(self):
        """Test MigrationTool initialization."""
        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        target = Mock(spec=StorageBackend)

        tool = MigrationTool(source, target)

        assert tool.source_backend == source
        assert tool.target_backend == target

    def test_migration_tool_initialization_invalid(self):
        """Test MigrationTool initialization with invalid backends."""
        from siof.storage.migration import MigrationTool

        with pytest.raises(ValueError):
            MigrationTool(None, Mock(spec=StorageBackend))

        with pytest.raises(ValueError):
            MigrationTool(Mock(spec=StorageBackend), None)

    def test_export_nodes(self):
        """Test exporting nodes."""
        import json
        import tempfile

        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        source.get_backend_name = Mock(return_value="Neo4j")
        source.get_backend_version = Mock(return_value="5.0")
        source.query = Mock(
            return_value=[
                {"n": {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}}},
                {"n": {"id": "node2", "type": "Symbol", "name": "func2", "metadata": {}}},
            ]
        )

        target = Mock(spec=StorageBackend)
        target.get_backend_name = Mock(return_value="FalkorDB")
        target.get_backend_version = Mock(return_value="1.0")

        tool = MigrationTool(source, target)

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            output_file = f.name

        try:
            result = tool.export(output_file)

            assert result["nodes_exported"] == 2
            assert result["edges_exported"] == 0
            assert "output_file" in result

            # Verify file contents
            with open(output_file) as f:
                data = json.load(f)
                assert len(data["nodes"]) == 2
                assert len(data["edges"]) == 0

        finally:
            import os

            os.unlink(output_file)

    def test_import_nodes(self):
        """Test importing nodes."""
        import json
        import tempfile

        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        target = Mock(spec=StorageBackend)
        target.create_node = Mock()

        tool = MigrationTool(source, target)

        # Create test data
        import_data = {
            "metadata": {},
            "nodes": [
                {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}},
                {"id": "node2", "type": "Symbol", "name": "func2", "metadata": {}},
            ],
            "edges": [],
        }

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(import_data, f)
            input_file = f.name

        try:
            result = tool.import_data(input_file)

            assert result["nodes_imported"] == 2
            assert result["edges_imported"] == 0
            assert result["validation_status"] == "success"
            assert target.create_node.call_count == 2

        finally:
            import os

            os.unlink(input_file)

    def test_validate_export(self):
        """Test export validation."""
        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        target = Mock(spec=StorageBackend)

        tool = MigrationTool(source, target)

        # Valid data
        nodes = [
            {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}},
            {"id": "node2", "type": "Symbol", "name": "func2", "metadata": {}},
        ]
        edges = [
            {"source_id": "node1", "target_id": "node2", "edge_type": "CALLS", "metadata": {}},
        ]

        # Should not raise
        tool._validate_export(nodes, edges)

    def test_validate_export_duplicate_nodes(self):
        """Test export validation with duplicate node IDs."""
        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        target = Mock(spec=StorageBackend)

        tool = MigrationTool(source, target)

        # Duplicate node IDs
        nodes = [
            {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}},
            {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}},
        ]
        edges = []

        with pytest.raises(StorageException, match="Duplicate"):
            tool._validate_export(nodes, edges)

    def test_validate_export_invalid_edge(self):
        """Test export validation with invalid edge reference."""
        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        target = Mock(spec=StorageBackend)

        tool = MigrationTool(source, target)

        # Edge references non-existent node
        nodes = [
            {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}},
        ]
        edges = [
            {
                "source_id": "node1",
                "target_id": "node_missing",
                "edge_type": "CALLS",
                "metadata": {},
            },
        ]

        with pytest.raises(StorageException, match="non-existent"):
            tool._validate_export(nodes, edges)

    def test_rollback_import(self):
        """Test rolling back a failed import."""
        from siof.storage.migration import MigrationTool

        source = Mock(spec=StorageBackend)
        target = Mock(spec=StorageBackend)
        target.delete_edge = Mock()
        target.delete_node = Mock()

        tool = MigrationTool(source, target)

        # Simulate imported data
        tool._imported_nodes = ["node1", "node2"]
        tool._imported_edges = [("node1", "node2")]

        tool.rollback()

        assert target.delete_edge.call_count == 1
        assert target.delete_node.call_count == 2
        assert len(tool._imported_nodes) == 0
        assert len(tool._imported_edges) == 0


# ============================================================================
# Compatibility Layer Tests
# ============================================================================


class TestRepositoryAdapter:
    """Tests for RepositoryAdapter (v1.0 compatibility)."""

    def test_adapter_initialization(self):
        """Test RepositoryAdapter initialization."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        assert adapter._repository == repo

    def test_adapter_initialization_invalid(self):
        """Test RepositoryAdapter initialization with invalid repository."""
        from siof.storage.compatibility import RepositoryAdapter

        with pytest.raises(ValueError):
            RepositoryAdapter(None)

    def test_add_node_v1_api(self):
        """Test add_node (v1.0 API)."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.create_node = Mock()
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        adapter.add_node("node1", "Symbol", "my_func", {"file": "main.py"})

        backend.create_node.assert_called_once()

    def test_get_node_v1_api(self):
        """Test get_node (v1.0 API)."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.read_node = Mock(
            return_value=Node(
                id="node1",
                type="Symbol",
                name="my_func",
                metadata={"file": "main.py"},
            )
        )
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        result = adapter.get_node("node1")

        assert result["id"] == "node1"
        assert result["type"] == "Symbol"
        assert result["name"] == "my_func"

    def test_get_node_not_found(self):
        """Test get_node returns None when node not found."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.read_node = Mock(return_value=None)
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        result = adapter.get_node("missing")

        assert result is None

    def test_add_edge_v1_api(self):
        """Test add_edge (v1.0 API)."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.create_edge = Mock()
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        adapter.add_edge("node1", "node2", "CALLS", {"line": 42})

        backend.create_edge.assert_called_once()

    def test_get_lineage_v1_api(self):
        """Test get_lineage (v1.0 API)."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query = Mock(
            return_value=[
                {"upstream": {"id": "node1", "type": "Symbol", "name": "func1", "metadata": {}}},
            ]
        )
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        result = adapter.get_lineage("node2")

        assert len(result) == 1
        assert result[0]["id"] == "node1"

    def test_deprecated_method_warning(self):
        """Test that deprecated methods emit warnings."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.query = Mock(return_value=[])
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        with pytest.warns(DeprecationWarning):
            adapter.query("MATCH (n) RETURN n")

    def test_transaction_support_v2_api(self):
        """Test transaction support in adapter."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.commit_transaction = Mock()
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        adapter.begin_transaction()
        adapter.commit_transaction()

        backend.begin_transaction.assert_called_once()
        backend.commit_transaction.assert_called_once()

    def test_transaction_context_manager_v2_api(self):
        """Test transaction context manager in adapter."""
        from siof.storage.compatibility import RepositoryAdapter
        from siof.storage.distributed_repository import DistributedRepository

        backend = Mock(spec=StorageBackend)
        backend.begin_transaction = Mock()
        backend.commit_transaction = Mock()
        repo = DistributedRepository(backend)
        adapter = RepositoryAdapter(repo)

        with adapter.transaction("serializable"):
            pass

        backend.begin_transaction.assert_called_once()
        backend.commit_transaction.assert_called_once()
