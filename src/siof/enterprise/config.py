"""Enterprise MCP configuration loading, validation, and hot-reload."""

from __future__ import annotations

import copy
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EnterpriseConfig:
    """Configuration contract for enterprise server features."""

    jwt: dict[str, Any] = field(
        default_factory=lambda: {
            "issuer": "siof-enterprise",
            "audience": "siof-api",
            "access_token_expiry_seconds": 1800,
            "refresh_token_expiry_seconds": 604800,
            "rotation_grace_seconds": 604800,
        }
    )
    redis: dict[str, Any] = field(
        default_factory=lambda: {
            "url": "redis://localhost:6379/0",
            "session_ttl_seconds": 3600,
            "ssl": False,
        }
    )
    rate_limiting: dict[str, Any] = field(
        default_factory=lambda: {
            "org_limit_per_minute": 1000,
            "user_limit_per_minute": 100,
            "burst_allowance": 0.2,
        }
    )
    tls: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": False,
            "min_version": "1.2",
            "cert_path": None,
            "key_path": None,
            "enforce_https": True,
        }
    )
    security: dict[str, Any] = field(
        default_factory=lambda: {
            "bcrypt_cost": 12,
            "password_min_length": 12,
            "max_failed_logins": 5,
            "lockout_duration_seconds": 900,
        }
    )


class EnterpriseConfigManager:
    """Load config from YAML and environment with validation and reload support."""

    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        env_prefix: str = "SIOF_ENTERPRISE_",
    ):
        self.config_path = Path(config_path) if config_path else None
        self.env_prefix = env_prefix
        self._config = EnterpriseConfig()
        self._version = 0
        self._last_mtime: float | None = None
        self._history: list[dict[str, Any]] = []

    def _deep_merge(self, base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _load_yaml(self) -> dict[str, Any]:
        if not self.config_path:
            return {}

        if not self.config_path.exists():
            raise ValueError(f"Config file not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        if not isinstance(data, dict):
            raise ValueError("Config root must be a mapping")

        self._last_mtime = self.config_path.stat().st_mtime
        return data

    def _parse_env_value(self, raw: str) -> Any:
        lowered = raw.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw

    def _load_env(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, raw_value in os.environ.items():
            if not key.startswith(self.env_prefix):
                continue

            path = key[len(self.env_prefix) :].lower().split("__")
            node = result
            for segment in path[:-1]:
                node = node.setdefault(segment, {})
            node[path[-1]] = self._parse_env_value(raw_value)

        return result

    def _validate(self, candidate: EnterpriseConfig) -> list[str]:
        errors: list[str] = []

        jwt = candidate.jwt
        if int(jwt.get("access_token_expiry_seconds", 0)) <= 0:
            errors.append("jwt.access_token_expiry_seconds must be > 0")
        if int(jwt.get("refresh_token_expiry_seconds", 0)) <= 0:
            errors.append("jwt.refresh_token_expiry_seconds must be > 0")
        if not jwt.get("issuer"):
            errors.append("jwt.issuer is required")
        if not jwt.get("audience"):
            errors.append("jwt.audience is required")

        redis = candidate.redis
        if not redis.get("url"):
            errors.append("redis.url is required")

        rate_limiting = candidate.rate_limiting
        if int(rate_limiting.get("org_limit_per_minute", 0)) <= 0:
            errors.append("rate_limiting.org_limit_per_minute must be > 0")
        if int(rate_limiting.get("user_limit_per_minute", 0)) <= 0:
            errors.append("rate_limiting.user_limit_per_minute must be > 0")

        tls = candidate.tls
        if tls.get("enabled"):
            if float(tls.get("min_version", "0")) < 1.2:
                errors.append("tls.min_version must be at least 1.2")
            if not tls.get("cert_path"):
                errors.append("tls.cert_path is required when tls.enabled=true")
            if not tls.get("key_path"):
                errors.append("tls.key_path is required when tls.enabled=true")

        security = candidate.security
        if int(security.get("bcrypt_cost", 0)) < 10:
            errors.append("security.bcrypt_cost should be >= 10")

        return errors

    def load(self) -> EnterpriseConfig:
        """Load and validate configuration from all sources."""
        merged = asdict(EnterpriseConfig())
        merged = self._deep_merge(merged, self._load_yaml())
        merged = self._deep_merge(merged, self._load_env())

        candidate = EnterpriseConfig(**merged)
        errors = self._validate(candidate)
        if errors:
            raise ValueError("Invalid enterprise configuration: " + "; ".join(errors))

        self._version += 1
        self._history.append(
            {
                "version": self._version,
                "timestamp": int(time.time()),
                "config": asdict(candidate),
            }
        )
        self._config = candidate
        return candidate

    def hot_reload_if_changed(self) -> bool:
        """Reload YAML configuration when file modification time changes."""
        if not self.config_path or not self.config_path.exists():
            return False

        mtime = self.config_path.stat().st_mtime
        if self._last_mtime is None:
            self._last_mtime = mtime
            return False

        if mtime <= self._last_mtime:
            return False

        logger.info("Configuration file changed, reloading")
        self.load()
        self._last_mtime = mtime
        return True

    def get_config(self) -> EnterpriseConfig:
        return self._config

    def get_version(self) -> int:
        return self._version

    def get_audit_history(self) -> list[dict[str, Any]]:
        return list(self._history)
