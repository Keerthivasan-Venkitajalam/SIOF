"""Security utilities: TLS enforcement and secret rotation."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TLSSettings:
    """TLS configuration settings."""

    enabled: bool = True
    min_version: str = "1.2"
    cert_path: str | None = None
    key_path: str | None = None
    ca_path: str | None = None
    enforce_https: bool = True
    cert_pinning_enabled: bool = False


@dataclass(slots=True)
class RotationState:
    """Current and previous secret metadata for graceful rotation."""

    secret_type: str
    current_secret_id: str
    previous_secret_id: str | None
    previous_valid_until: int | None
    last_rotated_at: int
    next_rotation_at: int
    grace_period_seconds: int
    interval_days: int


class TLSManager:
    """Validate and enforce TLS settings."""

    def __init__(self, settings: TLSSettings, audit_logger: Any | None = None):
        self.settings = settings
        self.audit_logger = audit_logger

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.settings.enabled:
            if float(self.settings.min_version) < 1.2:
                errors.append("TLS version must be 1.2 or higher")
            if not self.settings.cert_path:
                errors.append("TLS certificate path is required")
            if not self.settings.key_path:
                errors.append("TLS private key path is required")

        return errors

    def assert_https(self, is_https_request: bool) -> None:
        if self.settings.enforce_https and not is_https_request:
            raise ValueError("HTTPS is required")

    def log_handshake_failure(self, reason: str, client_ip: str | None = None) -> None:
        logger.warning("TLS handshake failure: %s", reason)
        if self.audit_logger:
            self.audit_logger.log_event(
                category="security",
                action="tls_handshake_failure",
                resource_type="tls",
                status="denied",
                details={"reason": reason, "client_ip": client_ip},
            )


class SecretRotationManager:
    """Rotate secrets with grace-period compatibility for old versions."""

    def __init__(self, audit_logger: Any | None = None):
        self.audit_logger = audit_logger
        self._states: dict[str, RotationState] = {}
        self._callbacks: dict[str, Callable[[str], None] | None] = {}

    def _now(self) -> int:
        return int(time.time())

    def register_secret(
        self,
        *,
        secret_type: str,
        interval_days: int = 90,
        grace_period_seconds: int = 604800,
        on_rotate: Callable[[str], None] | None = None,
    ) -> RotationState:
        now = self._now()
        state = RotationState(
            secret_type=secret_type,
            current_secret_id=str(uuid.uuid4()),
            previous_secret_id=None,
            previous_valid_until=None,
            last_rotated_at=now,
            next_rotation_at=now + int(interval_days * 86400),
            grace_period_seconds=grace_period_seconds,
            interval_days=interval_days,
        )
        self._states[secret_type] = state
        self._callbacks[secret_type] = on_rotate
        return state

    def rotate_secret(self, secret_type: str, *, reason: str = "manual") -> RotationState:
        state = self._states.get(secret_type)
        if state is None:
            raise ValueError("Unknown secret type")

        now = self._now()
        old_secret = state.current_secret_id
        state.previous_secret_id = old_secret
        state.previous_valid_until = now + state.grace_period_seconds
        state.current_secret_id = str(uuid.uuid4())
        state.last_rotated_at = now
        state.next_rotation_at = now + int(state.interval_days * 86400)

        callback = self._callbacks.get(secret_type)
        if callback:
            callback(state.current_secret_id)

        if self.audit_logger:
            self.audit_logger.log_event(
                category="security",
                action="secret_rotated",
                resource_type="secret",
                resource_id=secret_type,
                status="success",
                details={
                    "reason": reason,
                    "new_secret_id": state.current_secret_id,
                    "previous_secret_id": old_secret,
                    "grace_period_seconds": state.grace_period_seconds,
                },
            )

        return state

    def run_scheduled_rotation(self, *, now: int | None = None) -> list[str]:
        """Rotate secrets that are due and return rotated secret types."""
        now = self._now() if now is None else now
        rotated: list[str] = []

        for secret_type, state in self._states.items():
            if now >= state.next_rotation_at:
                self.rotate_secret(secret_type, reason="scheduled")
                rotated.append(secret_type)

        return rotated

    def accepts_secret(self, secret_type: str, secret_id: str, *, now: int | None = None) -> bool:
        now = self._now() if now is None else now
        state = self._states.get(secret_type)
        if state is None:
            return False

        if secret_id == state.current_secret_id:
            return True

        if (
            state.previous_secret_id
            and secret_id == state.previous_secret_id
            and state.previous_valid_until is not None
            and now < state.previous_valid_until
        ):
            return True

        return False

    def get_status(self, secret_type: str) -> dict[str, Any] | None:
        state = self._states.get(secret_type)
        if state is None:
            return None
        return {
            "secret_type": state.secret_type,
            "current_secret_id": state.current_secret_id,
            "previous_secret_id": state.previous_secret_id,
            "previous_valid_until": state.previous_valid_until,
            "last_rotated_at": state.last_rotated_at,
            "next_rotation_at": state.next_rotation_at,
            "grace_period_seconds": state.grace_period_seconds,
            "interval_days": state.interval_days,
        }
