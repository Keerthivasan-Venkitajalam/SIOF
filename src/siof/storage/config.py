"""Configuration schema and loader for storage backends."""

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConnectionPoolConfig:
    """Configuration for connection pool.
    
    Attributes:
        min_size: Minimum idle connections to maintain
        max_size: Maximum total connections
        validation_interval_seconds: How often to validate idle connections
    """

    min_size: int = 10
    max_size: int = 50
    validation_interval_seconds: int = 30

    def validate(self) -> None:
        """Validate configuration parameters.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if self.min_size < 0:
            raise ValueError(f"min_size must be non-negative, got {self.min_size}")
        if self.max_size < 1:
            raise ValueError(f"max_size must be at least 1, got {self.max_size}")
        if self.min_size > self.max_size:
            raise ValueError(
                f"min_size ({self.min_size}) cannot exceed max_size ({self.max_size})"
            )
        if self.validation_interval_seconds < 0:
            raise ValueError(
                f"validation_interval_seconds must be non-negative, "
                f"got {self.validation_interval_seconds}"
            )


@dataclass
class RetryPolicyConfig:
    """Configuration for retry policy.
    
    Attributes:
        base_delay_ms: Base delay in milliseconds for first retry
        max_retries: Maximum number of retry attempts
        jitter: Whether to add random jitter to delays
    """

    base_delay_ms: int = 100
    max_retries: int = 3
    jitter: bool = True

    def validate(self) -> None:
        """Validate configuration parameters.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if self.base_delay_ms < 0:
            raise ValueError(
                f"base_delay_ms must be non-negative, got {self.base_delay_ms}"
            )
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {self.max_retries}")


@dataclass
class CacheConfig:
    """Configuration for caching layer.
    
    Attributes:
        enabled: Whether caching is enabled
        max_size: Maximum number of cached items
        ttl_seconds: Time-to-live for cached items
    """

    enabled: bool = True
    max_size: int = 1000
    ttl_seconds: int = 600

    def validate(self) -> None:
        """Validate configuration parameters.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if self.max_size < 1:
            raise ValueError(f"max_size must be at least 1, got {self.max_size}")
        if self.ttl_seconds < 0:
            raise ValueError(
                f"ttl_seconds must be non-negative, got {self.ttl_seconds}"
            )


@dataclass
class QueryOptimizerConfig:
    """Configuration for query optimizer.
    
    Attributes:
        enabled: Whether query optimization is enabled
        plan_cache_size: Maximum number of cached query plans
    """

    enabled: bool = True
    plan_cache_size: int = 100

    def validate(self) -> None:
        """Validate configuration parameters.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if self.plan_cache_size < 1:
            raise ValueError(
                f"plan_cache_size must be at least 1, got {self.plan_cache_size}"
            )


@dataclass
class BackendConfig:
    """Configuration for a single backend instance.
    
    Attributes:
        name: Unique name for this backend
        type: Backend type (neo4j, falkordb, sqlite)
        connection_string: Connection string for the backend
        options: Backend-specific options
        is_primary: Whether this is the primary backend
    """

    name: str
    type: str
    connection_string: str
    options: dict[str, Any] = field(default_factory=dict)
    is_primary: bool = True

    def validate(self) -> None:
        """Validate configuration parameters.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if not self.name:
            raise ValueError("Backend name cannot be empty")
        if not self.type:
            raise ValueError("Backend type cannot be empty")
        if self.type not in ("neo4j", "falkordb", "sqlite"):
            raise ValueError(
                f"Invalid backend type: {self.type}. "
                f"Must be one of: neo4j, falkordb, sqlite"
            )
        if not self.connection_string:
            raise ValueError("Connection string cannot be empty")


@dataclass
class StorageConfig:
    """Complete storage configuration.
    
    Attributes:
        backends: List of backend configurations
        connection_pool: Connection pool configuration
        retry_policy: Retry policy configuration
        cache: Cache configuration
        query_optimizer: Query optimizer configuration
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """

    backends: list[BackendConfig] = field(default_factory=list)
    connection_pool: ConnectionPoolConfig = field(default_factory=ConnectionPoolConfig)
    retry_policy: RetryPolicyConfig = field(default_factory=RetryPolicyConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    query_optimizer: QueryOptimizerConfig = field(default_factory=QueryOptimizerConfig)
    log_level: str = "INFO"

    def validate(self) -> None:
        """Validate all configuration parameters.
        
        Raises:
            ValueError: If any configuration is invalid
        """
        if not self.backends:
            raise ValueError("At least one backend must be configured")

        # Validate all backends
        for backend in self.backends:
            backend.validate()

        # Ensure at least one primary backend
        primary_backends = [b for b in self.backends if b.is_primary]
        if not primary_backends:
            raise ValueError("At least one backend must be marked as primary")

        # Validate sub-configurations
        self.connection_pool.validate()
        self.retry_policy.validate()
        self.cache.validate()
        self.query_optimizer.validate()

        # Validate log level
        valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        if self.log_level not in valid_levels:
            raise ValueError(
                f"Invalid log level: {self.log_level}. "
                f"Must be one of: {', '.join(valid_levels)}"
            )

    @classmethod
    def load_from_yaml(cls, yaml_file: str) -> "StorageConfig":
        """Load configuration from YAML file.
        
        Args:
            yaml_file: Path to YAML configuration file
            
        Returns:
            StorageConfig instance
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If configuration is invalid
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required to load YAML configuration. "
                "Install with: pip install pyyaml"
            )

        if not os.path.exists(yaml_file):
            raise FileNotFoundError(f"Configuration file not found: {yaml_file}")

        logger.info(f"Loading configuration from {yaml_file}")

        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Configuration file is empty: {yaml_file}")

        return cls._from_dict(data)

    @classmethod
    def load_from_env(cls) -> "StorageConfig":
        """Load configuration from environment variables.
        
        Environment variables:
        - SIOF_STORAGE_BACKEND: Backend type (neo4j, falkordb, sqlite)
        - SIOF_STORAGE_CONNECTION_STRING: Connection string
        - SIOF_STORAGE_POOL_MIN_SIZE: Connection pool min size
        - SIOF_STORAGE_POOL_MAX_SIZE: Connection pool max size
        - SIOF_STORAGE_RETRY_MAX_RETRIES: Max retry attempts
        - SIOF_STORAGE_LOG_LEVEL: Logging level
        
        Returns:
            StorageConfig instance
            
        Raises:
            ValueError: If required environment variables are missing
        """
        logger.info("Loading configuration from environment variables")

        backend_type = os.getenv("SIOF_STORAGE_BACKEND", "neo4j")
        connection_string = os.getenv("SIOF_STORAGE_CONNECTION_STRING")

        if not connection_string:
            raise ValueError(
                "SIOF_STORAGE_CONNECTION_STRING environment variable is required"
            )

        pool_min_size = int(os.getenv("SIOF_STORAGE_POOL_MIN_SIZE", "10"))
        pool_max_size = int(os.getenv("SIOF_STORAGE_POOL_MAX_SIZE", "50"))
        retry_max_retries = int(os.getenv("SIOF_STORAGE_RETRY_MAX_RETRIES", "3"))
        log_level = os.getenv("SIOF_STORAGE_LOG_LEVEL", "INFO")

        config = cls(
            backends=[
                BackendConfig(
                    name="primary",
                    type=backend_type,
                    connection_string=connection_string,
                    is_primary=True,
                )
            ],
            connection_pool=ConnectionPoolConfig(
                min_size=pool_min_size,
                max_size=pool_max_size,
            ),
            retry_policy=RetryPolicyConfig(max_retries=retry_max_retries),
            log_level=log_level,
        )

        config.validate()
        return config

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "StorageConfig":
        """Create StorageConfig from dictionary.
        
        Args:
            data: Configuration dictionary
            
        Returns:
            StorageConfig instance
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Parse backends
        backends_data = data.get("backends", [])
        if not backends_data:
            backends_data = [data.get("storage", {})]

        backends = []
        for backend_data in backends_data:
            backend = BackendConfig(
                name=backend_data.get("name", "primary"),
                type=backend_data.get("type", "neo4j"),
                connection_string=backend_data.get("connection_string", ""),
                options=backend_data.get("options", {}),
                is_primary=backend_data.get("is_primary", True),
            )
            backends.append(backend)

        # Parse connection pool config
        pool_data = data.get("connection_pool", {})
        connection_pool = ConnectionPoolConfig(
            min_size=pool_data.get("min_size", 10),
            max_size=pool_data.get("max_size", 50),
            validation_interval_seconds=pool_data.get("validation_interval_seconds", 30),
        )

        # Parse retry policy config
        retry_data = data.get("retry_policy", {})
        retry_policy = RetryPolicyConfig(
            base_delay_ms=retry_data.get("base_delay_ms", 100),
            max_retries=retry_data.get("max_retries", 3),
            jitter=retry_data.get("jitter", True),
        )

        # Parse cache config
        cache_data = data.get("cache", {})
        cache = CacheConfig(
            enabled=cache_data.get("enabled", True),
            max_size=cache_data.get("max_size", 1000),
            ttl_seconds=cache_data.get("ttl_seconds", 600),
        )

        # Parse query optimizer config
        optimizer_data = data.get("query_optimizer", {})
        query_optimizer = QueryOptimizerConfig(
            enabled=optimizer_data.get("enabled", True),
            plan_cache_size=optimizer_data.get("plan_cache_size", 100),
        )

        # Create config
        config = cls(
            backends=backends,
            connection_pool=connection_pool,
            retry_policy=retry_policy,
            cache=cache,
            query_optimizer=query_optimizer,
            log_level=data.get("log_level", "INFO"),
        )

        config.validate()
        return config

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration
        """
        return {
            "backends": [asdict(b) for b in self.backends],
            "connection_pool": asdict(self.connection_pool),
            "retry_policy": asdict(self.retry_policy),
            "cache": asdict(self.cache),
            "query_optimizer": asdict(self.query_optimizer),
            "log_level": self.log_level,
        }
