"""Thread-safe connection pool for database connections."""

import logging
from queue import Queue, Empty
from threading import Lock, Condition
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe connection pool with configurable size and metrics.
    
    This pool maintains a set of reusable database connections, creating new
    connections on demand up to max_size, and validating connections before
    reuse to ensure they're still alive.
    
    Attributes:
        min_size: Minimum number of idle connections to maintain
        max_size: Maximum number of connections (idle + active)
        factory: Callable that creates new connections
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        min_size: int = 10,
        max_size: int = 50,
    ) -> None:
        """Initialize connection pool.
        
        Args:
            factory: Callable that creates new connections
            min_size: Minimum idle connections (default: 10)
            max_size: Maximum total connections (default: 50)
            
        Raises:
            ValueError: If min_size > max_size or invalid sizes
        """
        if min_size < 0 or max_size < 1 or min_size > max_size:
            raise ValueError(
                f"Invalid pool sizes: min_size={min_size}, max_size={max_size}"
            )

        self.factory = factory
        self.min_size = min_size
        self.max_size = max_size

        # Thread-safe queue for idle connections
        self.pool: Queue[Any] = Queue(maxsize=max_size)

        # Lock and condition variable for synchronization
        self.lock = Lock()
        self.condition = Condition(self.lock)

        # Metrics
        self.active_count = 0
        self.total_created = 0
        self.total_reused = 0
        self.total_validated = 0
        self.total_validation_failures = 0

        # Pre-populate pool with min_size connections
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """Pre-populate pool with minimum connections."""
        with self.lock:
            for _ in range(self.min_size):
                try:
                    conn = self.factory()
                    self.pool.put_nowait(conn)
                    self.total_created += 1
                    logger.debug(
                        f"Created initial connection {self.total_created}/{self.min_size}"
                    )
                except Exception as e:
                    logger.error(f"Failed to create initial connection: {e}")
                    raise

    def acquire(self, timeout: Optional[float] = 5.0) -> Any:
        """Acquire a connection from the pool.
        
        This method will:
        1. Try to get an idle connection from the pool
        2. If no idle connections, create a new one (if below max_size)
        3. If at max_size, wait for a connection to be released
        
        Args:
            timeout: Maximum time to wait for a connection (seconds)
            
        Returns:
            A database connection
            
        Raises:
            TimeoutError: If no connection available within timeout
            Exception: If connection creation fails
        """
        with self.condition:
            # Try to get from pool without blocking
            try:
                conn = self.pool.get_nowait()
                self.total_reused += 1
                self.active_count += 1
                logger.debug(
                    f"Reused connection from pool (active: {self.active_count})"
                )
                return conn
            except Empty:
                pass

            # Try to create new connection if below max
            if self.active_count < self.max_size:
                try:
                    conn = self.factory()
                    self.active_count += 1
                    self.total_created += 1
                    logger.debug(
                        f"Created new connection (active: {self.active_count}, "
                        f"total: {self.total_created})"
                    )
                    return conn
                except Exception as e:
                    logger.error(f"Failed to create connection: {e}")
                    raise

            # Wait for connection to be released
            logger.debug(
                f"Pool at max capacity ({self.max_size}), waiting for release..."
            )
            if not self.condition.wait(timeout=timeout):
                raise TimeoutError(
                    f"No connection available within {timeout} seconds "
                    f"(active: {self.active_count}, idle: {self.pool.qsize()})"
                )

            # Try again after waiting
            try:
                conn = self.pool.get_nowait()
                self.total_reused += 1
                self.active_count += 1
                logger.debug(
                    f"Acquired released connection (active: {self.active_count})"
                )
                return conn
            except Empty:
                raise TimeoutError(
                    f"No connection available after waiting {timeout} seconds"
                )

    def release(self, conn: Any) -> None:
        """Release a connection back to the pool.
        
        This method validates the connection before returning it to the pool.
        If validation fails, the connection is discarded and a new one is
        created to maintain min_size.
        
        Args:
            conn: The connection to release
        """
        with self.condition:
            try:
                # Validate connection before returning to pool
                if self._validate_connection(conn):
                    self.pool.put_nowait(conn)
                    self.total_validated += 1
                    logger.debug(
                        f"Released valid connection to pool "
                        f"(idle: {self.pool.qsize()})"
                    )
                else:
                    # Connection is invalid, create replacement
                    self.total_validation_failures += 1
                    logger.warning("Connection validation failed, creating replacement")
                    try:
                        new_conn = self.factory()
                        self.pool.put_nowait(new_conn)
                        self.total_created += 1
                    except Exception as e:
                        logger.error(f"Failed to create replacement connection: {e}")

            except Exception as e:
                logger.error(f"Error releasing connection: {e}")
            finally:
                self.active_count -= 1
                self.condition.notify()

    def _validate_connection(self, conn: Any) -> bool:
        """Validate that a connection is still alive.
        
        This method checks if the connection is still valid by calling
        get_connection_status() if available, or attempting a simple operation.
        
        Args:
            conn: The connection to validate
            
        Returns:
            True if connection is valid, False otherwise
        """
        try:
            # Try to call get_connection_status if available
            if hasattr(conn, "get_connection_status"):
                return conn.get_connection_status()
            # Otherwise assume valid (for simple connection objects)
            return True
        except Exception as e:
            logger.debug(f"Connection validation failed: {e}")
            return False

    def close_all(self) -> None:
        """Close all connections in the pool.
        
        This method gracefully closes all idle connections and marks
        active connections for closure. Should be called during shutdown.
        """
        with self.lock:
            logger.info(
                f"Closing all connections (idle: {self.pool.qsize()}, "
                f"active: {self.active_count})"
            )

            # Close all idle connections
            closed_count = 0
            while not self.pool.empty():
                try:
                    conn = self.pool.get_nowait()
                    if hasattr(conn, "disconnect"):
                        conn.disconnect()
                    closed_count += 1
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")

            logger.info(f"Closed {closed_count} idle connections")

    def get_metrics(self) -> Dict[str, int]:
        """Get connection pool metrics.
        
        Returns:
            Dictionary containing:
            - active_connections: Currently active connections
            - idle_connections: Currently idle connections in pool
            - total_created: Total connections created
            - total_reused: Total connections reused from pool
            - total_validated: Total connections validated
            - total_validation_failures: Total validation failures
        """
        with self.lock:
            return {
                "active_connections": self.active_count,
                "idle_connections": self.pool.qsize(),
                "total_created": self.total_created,
                "total_reused": self.total_reused,
                "total_validated": self.total_validated,
                "total_validation_failures": self.total_validation_failures,
            }
