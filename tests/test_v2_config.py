"""Tests for SIOF v2.0 configuration system."""

import os
from pathlib import Path

import pytest

from siof.v2.config import SIOFv2Config


class TestConfigDefaults:
    """Test default configuration values."""

    def test_default_storage(self):
        config = SIOFv2Config()
        assert config.storage.backend == "sqlite"
        assert config.storage.pool_size == 10

    def test_default_cache(self):
        config = SIOFv2Config()
        assert config.cache.enabled is False
        assert config.cache.backend == "memory"

    def test_default_auth(self):
        config = SIOFv2Config()
        assert config.auth.enabled is False
        assert config.auth.provider == "jwt"

    def test_default_semantic_search(self):
        config = SIOFv2Config()
        assert config.semantic_search.enabled is False
        assert config.semantic_search.dimension == 384

    def test_default_parallel(self):
        config = SIOFv2Config()
        assert config.parallel.enabled is True
        assert config.parallel.executor == "thread"

    def test_default_observability(self):
        config = SIOFv2Config()
        assert config.observability.metrics_enabled is False
        assert config.observability.logging_level == "INFO"

    def test_default_deployment(self):
        config = SIOFv2Config()
        assert config.deployment.mode == "standalone"
        assert config.deployment.replicas == 1


class TestConfigFromEnv:
    """Test loading configuration from environment variables."""

    def test_storage_from_env(self, monkeypatch):
        monkeypatch.setenv("SIOF_STORAGE_BACKEND", "neo4j")
        monkeypatch.setenv("SIOF_STORAGE_CONNECTION_STRING", "bolt://localhost:7687")

        config = SIOFv2Config.from_env()

        assert config.storage.backend == "neo4j"
        assert config.storage.connection_string == "bolt://localhost:7687"

    def test_cache_from_env(self, monkeypatch):
        monkeypatch.setenv("SIOF_CACHE_ENABLED", "true")
        monkeypatch.setenv("SIOF_CACHE_BACKEND", "redis")

        config = SIOFv2Config.from_env()

        assert config.cache.enabled is True
        assert config.cache.backend == "redis"

    def test_auth_from_env(self, monkeypatch):
        monkeypatch.setenv("SIOF_AUTH_ENABLED", "true")
        monkeypatch.setenv("SIOF_AUTH_JWT_SECRET", "my-secret")

        config = SIOFv2Config.from_env()

        assert config.auth.enabled is True
        assert config.auth.jwt_secret == "my-secret"

    def test_observability_from_env(self, monkeypatch):
        monkeypatch.setenv("SIOF_METRICS_ENABLED", "true")
        monkeypatch.setenv("SIOF_TRACING_ENABLED", "true")

        config = SIOFv2Config.from_env()

        assert config.observability.metrics_enabled is True
        assert config.observability.tracing_enabled is True


class TestConfigFromYAML:
    """Test loading configuration from YAML files."""

    def test_load_development_config(self):
        config_path = Path("deploy/config/siof-v2-development.yaml")
        if not config_path.exists():
            pytest.skip("Development config not found")

        config = SIOFv2Config.from_yaml(config_path)

        assert config.storage.backend == "sqlite"
        assert config.cache.enabled is True
        assert config.auth.enabled is False
        assert config.deployment.mode == "standalone"

    def test_load_production_config(self):
        config_path = Path("deploy/config/siof-v2-production.yaml")
        if not config_path.exists():
            pytest.skip("Production config not found")

        config = SIOFv2Config.from_yaml(config_path)

        assert config.storage.backend == "neo4j"
        assert config.cache.enabled is True
        assert config.cache.backend == "redis"
        assert config.auth.enabled is True
        assert config.semantic_search.enabled is True
        assert config.observability.metrics_enabled is True
        assert config.deployment.mode == "distributed"


class TestConfigValidation:
    """Test configuration validation."""

    def test_valid_config(self):
        config = SIOFv2Config()
        errors = config.validate()
        assert len(errors) == 0

    def test_invalid_storage_backend(self):
        config = SIOFv2Config()
        config.storage.backend = "invalid"

        errors = config.validate()
        assert len(errors) > 0
        assert any("storage backend" in e.lower() for e in errors)

    def test_invalid_cache_backend(self):
        config = SIOFv2Config()
        config.cache.enabled = True
        config.cache.backend = "invalid"

        errors = config.validate()
        assert len(errors) > 0
        assert any("cache backend" in e.lower() for e in errors)

    def test_jwt_without_secret(self):
        config = SIOFv2Config()
        config.auth.enabled = True
        config.auth.provider = "jwt"
        config.auth.jwt_secret = ""

        errors = config.validate()
        assert len(errors) > 0
        assert any("jwt secret" in e.lower() for e in errors)

    def test_invalid_auth_provider(self):
        config = SIOFv2Config()
        config.auth.enabled = True
        config.auth.provider = "invalid"

        errors = config.validate()
        assert len(errors) > 0
        assert any("auth provider" in e.lower() for e in errors)

    def test_invalid_embedder(self):
        config = SIOFv2Config()
        config.semantic_search.enabled = True
        config.semantic_search.embedder = "invalid"

        errors = config.validate()
        assert len(errors) > 0
        assert any("embedder" in e.lower() for e in errors)

    def test_invalid_executor(self):
        config = SIOFv2Config()
        config.parallel.executor = "invalid"

        errors = config.validate()
        assert len(errors) > 0
        assert any("executor" in e.lower() for e in errors)

    def test_invalid_deployment_mode(self):
        config = SIOFv2Config()
        config.deployment.mode = "invalid"

        errors = config.validate()
        assert len(errors) > 0
        assert any("deployment mode" in e.lower() for e in errors)


class TestConfigSerialization:
    """Test configuration serialization."""

    def test_to_dict(self):
        config = SIOFv2Config()
        config.storage.backend = "neo4j"
        config.cache.enabled = True

        data = config.to_dict()

        assert data["storage"]["backend"] == "neo4j"
        assert data["cache"]["enabled"] is True

    def test_round_trip(self, tmp_path):
        import yaml

        # Create config
        config1 = SIOFv2Config()
        config1.storage.backend = "neo4j"
        config1.cache.enabled = True
        config1.auth.enabled = True
        config1.auth.jwt_secret = "test-secret"

        # Save to YAML
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config1.to_dict(), f)

        # Load from YAML
        config2 = SIOFv2Config.from_yaml(config_file)

        # Verify
        assert config2.storage.backend == "neo4j"
        assert config2.cache.enabled is True
        assert config2.auth.enabled is True
