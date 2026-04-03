"""Configuration management for SIOF v2.0.

Supports multiple configuration sources:
- YAML files
- Environment variables
- Command-line arguments
- Kubernetes ConfigMaps/Secrets
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StorageConfig:
    """Storage backend configuration."""

    backend: str = "sqlite"  # sqlite, neo4j, falkordb
    connection_string: str = ""
    pool_size: int = 10
    timeout_seconds: int = 30
    retry_attempts: int = 3
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class CacheConfig:
    """Cache backend configuration."""

    enabled: bool = False
    backend: str = "memory"  # memory, redis
    connection_string: str = ""
    ttl_seconds: int = 300
    max_size_mb: int = 100
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthConfig:
    """Authentication configuration."""

    enabled: bool = False
    provider: str = "jwt"  # jwt, session, apikey
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    token_expiry_seconds: int = 3600
    refresh_enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class SemanticSearchConfig:
    """Semantic search configuration."""

    enabled: bool = False
    embedder: str = "transformer"  # transformer, openai
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_store: str = "milvus"  # milvus, faiss
    connection_string: str = ""
    dimension: int = 384
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParallelConfig:
    """Parallel processing configuration."""

    enabled: bool = True
    executor: str = "thread"  # thread, process
    max_workers: int = 0  # 0 = auto-detect
    queue_size: int = 1000
    batch_size: int = 100
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ObservabilityConfig:
    """Observability configuration."""

    metrics_enabled: bool = False
    metrics_port: int = 9090
    tracing_enabled: bool = False
    tracing_endpoint: str = ""
    logging_level: str = "INFO"
    export_interval_seconds: int = 60
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeploymentConfig:
    """Deployment configuration."""

    mode: str = "standalone"  # standalone, distributed, edge
    region: str = "us-east-1"
    replicas: int = 1
    health_check_port: int = 8080
    graceful_shutdown_seconds: int = 30
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class SIOFv2Config:
    """Complete SIOF v2.0 configuration."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    semantic_search: SemanticSearchConfig = field(default_factory=SemanticSearchConfig)
    parallel: ParallelConfig = field(default_factory=ParallelConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)

    @classmethod
    def from_env(cls) -> SIOFv2Config:
        """Load configuration from environment variables.

        Environment variables follow the pattern:
        SIOF_<SECTION>_<KEY>=value

        Example:
            SIOF_STORAGE_BACKEND=neo4j
            SIOF_CACHE_ENABLED=true
            SIOF_AUTH_JWT_SECRET=mysecret
        """
        config = cls()

        # Storage
        if backend := os.getenv("SIOF_STORAGE_BACKEND"):
            config.storage.backend = backend
        if conn := os.getenv("SIOF_STORAGE_CONNECTION_STRING"):
            config.storage.connection_string = conn

        # Cache
        if enabled := os.getenv("SIOF_CACHE_ENABLED"):
            config.cache.enabled = enabled.lower() == "true"
        if backend := os.getenv("SIOF_CACHE_BACKEND"):
            config.cache.backend = backend

        # Auth
        if enabled := os.getenv("SIOF_AUTH_ENABLED"):
            config.auth.enabled = enabled.lower() == "true"
        if secret := os.getenv("SIOF_AUTH_JWT_SECRET"):
            config.auth.jwt_secret = secret

        # Semantic Search
        if enabled := os.getenv("SIOF_SEMANTIC_ENABLED"):
            config.semantic_search.enabled = enabled.lower() == "true"

        # Observability
        if enabled := os.getenv("SIOF_METRICS_ENABLED"):
            config.observability.metrics_enabled = enabled.lower() == "true"
        if enabled := os.getenv("SIOF_TRACING_ENABLED"):
            config.observability.tracing_enabled = enabled.lower() == "true"

        return config

    @classmethod
    def from_yaml(cls, path: Path | str) -> SIOFv2Config:
        """Load configuration from YAML file.

        Example YAML:
            storage:
              backend: neo4j
              connection_string: bolt://localhost:7687

            cache:
              enabled: true
              backend: redis
              connection_string: redis://localhost:6379

            auth:
              enabled: true
              provider: jwt
              jwt_secret: ${JWT_SECRET}
        """
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)

        config = cls()

        # Parse storage
        if "storage" in data:
            for key, value in data["storage"].items():
                if hasattr(config.storage, key):
                    setattr(config.storage, key, value)

        # Parse cache
        if "cache" in data:
            for key, value in data["cache"].items():
                if hasattr(config.cache, key):
                    setattr(config.cache, key, value)

        # Parse auth
        if "auth" in data:
            for key, value in data["auth"].items():
                if hasattr(config.auth, key):
                    setattr(config.auth, key, value)

        # Parse semantic search
        if "semantic_search" in data:
            for key, value in data["semantic_search"].items():
                if hasattr(config.semantic_search, key):
                    setattr(config.semantic_search, key, value)

        # Parse parallel
        if "parallel" in data:
            for key, value in data["parallel"].items():
                if hasattr(config.parallel, key):
                    setattr(config.parallel, key, value)

        # Parse observability
        if "observability" in data:
            for key, value in data["observability"].items():
                if hasattr(config.observability, key):
                    setattr(config.observability, key, value)

        # Parse deployment
        if "deployment" in data:
            for key, value in data["deployment"].items():
                if hasattr(config.deployment, key):
                    setattr(config.deployment, key, value)

        return config

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "storage": {
                "backend": self.storage.backend,
                "connection_string": self.storage.connection_string,
                "pool_size": self.storage.pool_size,
                "timeout_seconds": self.storage.timeout_seconds,
                "retry_attempts": self.storage.retry_attempts,
                "options": self.storage.options,
            },
            "cache": {
                "enabled": self.cache.enabled,
                "backend": self.cache.backend,
                "connection_string": self.cache.connection_string,
                "ttl_seconds": self.cache.ttl_seconds,
                "max_size_mb": self.cache.max_size_mb,
                "options": self.cache.options,
            },
            "auth": {
                "enabled": self.auth.enabled,
                "provider": self.auth.provider,
                "jwt_algorithm": self.auth.jwt_algorithm,
                "token_expiry_seconds": self.auth.token_expiry_seconds,
                "refresh_enabled": self.auth.refresh_enabled,
                "options": self.auth.options,
            },
            "semantic_search": {
                "enabled": self.semantic_search.enabled,
                "embedder": self.semantic_search.embedder,
                "model_name": self.semantic_search.model_name,
                "vector_store": self.semantic_search.vector_store,
                "connection_string": self.semantic_search.connection_string,
                "dimension": self.semantic_search.dimension,
                "options": self.semantic_search.options,
            },
            "parallel": {
                "enabled": self.parallel.enabled,
                "executor": self.parallel.executor,
                "max_workers": self.parallel.max_workers,
                "queue_size": self.parallel.queue_size,
                "batch_size": self.parallel.batch_size,
                "options": self.parallel.options,
            },
            "observability": {
                "metrics_enabled": self.observability.metrics_enabled,
                "metrics_port": self.observability.metrics_port,
                "tracing_enabled": self.observability.tracing_enabled,
                "tracing_endpoint": self.observability.tracing_endpoint,
                "logging_level": self.observability.logging_level,
                "export_interval_seconds": self.observability.export_interval_seconds,
                "options": self.observability.options,
            },
            "deployment": {
                "mode": self.deployment.mode,
                "region": self.deployment.region,
                "replicas": self.deployment.replicas,
                "health_check_port": self.deployment.health_check_port,
                "graceful_shutdown_seconds": self.deployment.graceful_shutdown_seconds,
                "options": self.deployment.options,
            },
        }

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        # Validate storage
        if self.storage.backend not in ["sqlite", "neo4j", "falkordb"]:
            errors.append(f"Invalid storage backend: {self.storage.backend}")

        # Validate cache
        if self.cache.enabled and self.cache.backend not in ["memory", "redis"]:
            errors.append(f"Invalid cache backend: {self.cache.backend}")

        # Validate auth
        if self.auth.enabled:
            if self.auth.provider not in ["jwt", "session", "apikey"]:
                errors.append(f"Invalid auth provider: {self.auth.provider}")
            if self.auth.provider == "jwt" and not self.auth.jwt_secret:
                errors.append("JWT secret is required when JWT auth is enabled")

        # Validate semantic search
        if self.semantic_search.enabled:
            if self.semantic_search.embedder not in ["transformer", "openai"]:
                errors.append(f"Invalid embedder: {self.semantic_search.embedder}")
            if self.semantic_search.vector_store not in ["milvus", "faiss"]:
                errors.append(f"Invalid vector store: {self.semantic_search.vector_store}")

        # Validate parallel
        if self.parallel.executor not in ["thread", "process"]:
            errors.append(f"Invalid executor: {self.parallel.executor}")

        # Validate deployment
        if self.deployment.mode not in ["standalone", "distributed", "edge"]:
            errors.append(f"Invalid deployment mode: {self.deployment.mode}")

        return errors
