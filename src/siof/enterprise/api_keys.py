"""API key lifecycle management for enterprise service authentication."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class APIKeyRecord:
    """Stored API key metadata and lifecycle fields."""

    api_key_id: str
    org_id: str
    service_account_id: str
    name: str
    key_hash: str
    salt: str
    roles: list[str]
    owner_email: str | None
    created_at: int
    expires_at: int | None
    revoked_at: int | None = None
    revocation_reason: str | None = None
    deprecated_until: int | None = None
    replaced_by: str | None = None
    last_used: int | None = None
    usage_count: int = 0


class APIKeyManager:
    """Generate, validate, rotate, and revoke API keys."""

    KEY_PREFIX = "siof"

    def __init__(
        self,
        *,
        default_expiry_days: int = 365,
        default_rotation_grace_days: int = 7,
        audit_logger: Any | None = None,
    ):
        self.default_expiry_days = default_expiry_days
        self.default_rotation_grace_days = default_rotation_grace_days
        self.audit_logger = audit_logger

        self._records: dict[str, APIKeyRecord] = {}

    def _now(self) -> int:
        return int(time.time())

    def _hash_key(self, *, raw_key: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()

    @classmethod
    def validate_key_format(cls, raw_key: str) -> bool:
        if not raw_key.startswith(f"{cls.KEY_PREFIX}_"):
            return False

        try:
            _, rest = raw_key.split("_", 1)
            key_id, secret = rest.split(".", 1)
            return bool(key_id) and bool(secret)
        except ValueError:
            return False

    def _extract_key_id(self, raw_key: str) -> str:
        _, rest = raw_key.split("_", 1)
        key_id, _ = rest.split(".", 1)
        return key_id

    def _build_raw_key(self, key_id: str) -> tuple[str, str]:
        secret = secrets.token_urlsafe(32)
        return f"{self.KEY_PREFIX}_{key_id}.{secret}", secret

    def create_api_key(
        self,
        *,
        org_id: str,
        service_account_id: str,
        name: str,
        expiry_days: int | None = None,
        owner_email: str | None = None,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a cryptographically secure API key and return plaintext once."""
        key_id = uuid.uuid4().hex
        raw_key, _ = self._build_raw_key(key_id)
        salt = secrets.token_hex(16)

        now = self._now()
        ttl_days = self.default_expiry_days if expiry_days is None else expiry_days
        expires_at = None if ttl_days <= 0 else now + int(ttl_days * 86400)

        record = APIKeyRecord(
            api_key_id=key_id,
            org_id=org_id,
            service_account_id=service_account_id,
            name=name,
            key_hash=self._hash_key(raw_key=raw_key, salt=salt),
            salt=salt,
            roles=list(roles or ["service"]),
            owner_email=owner_email,
            created_at=now,
            expires_at=expires_at,
        )

        self._records[key_id] = record

        if self.audit_logger:
            self.audit_logger.log_event(
                category="api_key",
                action="create",
                resource_type="api_key",
                resource_id=key_id,
                org_id=org_id,
                status="success",
                details={"service_account_id": service_account_id, "expires_at": expires_at},
            )

        return {
            "api_key": raw_key,
            "api_key_id": key_id,
            "org_id": org_id,
            "service_account_id": service_account_id,
            "expires_at": expires_at,
        }

    def _is_revoked_or_expired(self, record: APIKeyRecord, *, now: int) -> tuple[bool, str | None]:
        if record.revoked_at is not None:
            return True, "revoked"

        if record.expires_at is not None and now > record.expires_at:
            return True, "expired"

        if (
            record.deprecated_until is not None
            and record.replaced_by
            and now > record.deprecated_until
        ):
            return True, "deprecated"

        return False, None

    def validate_api_key(self, raw_key: str) -> dict[str, Any] | None:
        """Validate API key format, hash, expiry, revocation, and rotation grace."""
        if not self.validate_key_format(raw_key):
            return None

        key_id = self._extract_key_id(raw_key)
        record = self._records.get(key_id)
        if record is None:
            return None

        now = self._now()
        blocked, reason = self._is_revoked_or_expired(record, now=now)
        if blocked:
            logger.warning("API key validation rejected for %s: %s", key_id, reason)
            return None

        expected_hash = self._hash_key(raw_key=raw_key, salt=record.salt)
        if not secrets.compare_digest(expected_hash, record.key_hash):
            return None

        record.last_used = now
        record.usage_count += 1

        if self.audit_logger:
            self.audit_logger.log_api_key_usage(
                api_key_id=record.api_key_id,
                org_id=record.org_id,
                action="authenticate",
                resource="mcp",
            )

        return {
            "api_key_id": record.api_key_id,
            "org_id": record.org_id,
            "service_account_id": record.service_account_id,
            "roles": list(record.roles),
            "expires_at": record.expires_at,
        }

    def rotate_api_key(
        self,
        api_key_id: str,
        *,
        grace_days: int | None = None,
    ) -> dict[str, Any]:
        """Rotate key and keep old key active during grace period."""
        old_record = self._records.get(api_key_id)
        if old_record is None:
            raise ValueError("API key not found")
        if old_record.revoked_at is not None:
            raise ValueError("Cannot rotate revoked key")

        new_key = self.create_api_key(
            org_id=old_record.org_id,
            service_account_id=old_record.service_account_id,
            name=f"{old_record.name}-rotated",
            expiry_days=self.default_expiry_days,
            owner_email=old_record.owner_email,
            roles=list(old_record.roles),
        )

        now = self._now()
        days = self.default_rotation_grace_days if grace_days is None else grace_days
        old_record.deprecated_until = now + int(days * 86400)
        old_record.replaced_by = new_key["api_key_id"]

        if self.audit_logger:
            self.audit_logger.log_event(
                category="api_key",
                action="rotate",
                resource_type="api_key",
                resource_id=api_key_id,
                org_id=old_record.org_id,
                status="success",
                details={
                    "new_api_key_id": new_key["api_key_id"],
                    "deprecated_until": old_record.deprecated_until,
                },
            )

        return new_key

    def revoke_api_key(
        self,
        api_key_id: str,
        *,
        reason: str,
        notify_callback: Callable[[str, str], None] | None = None,
    ) -> bool:
        record = self._records.get(api_key_id)
        if record is None:
            return False
        if record.revoked_at is not None:
            return True

        record.revoked_at = self._now()
        record.revocation_reason = reason

        if notify_callback and record.owner_email:
            notify_callback(record.owner_email, reason)

        if self.audit_logger:
            self.audit_logger.log_event(
                category="api_key",
                action="revoke",
                resource_type="api_key",
                resource_id=api_key_id,
                org_id=record.org_id,
                status="success",
                details={"reason": reason},
            )

        return True

    def revoke_service_account_keys(
        self,
        service_account_id: str,
        *,
        reason: str,
        notify_callback: Callable[[str, str], None] | None = None,
    ) -> int:
        revoked = 0
        for record in self._records.values():
            if record.service_account_id != service_account_id:
                continue
            if self.revoke_api_key(
                record.api_key_id, reason=reason, notify_callback=notify_callback
            ):
                revoked += 1
        return revoked

    def get_api_key_status(self, api_key_id: str) -> dict[str, Any] | None:
        record = self._records.get(api_key_id)
        if record is None:
            return None

        now = self._now()
        blocked, reason = self._is_revoked_or_expired(record, now=now)

        data = asdict(record)
        data.update(
            {
                "is_active": not blocked,
                "blocked_reason": reason,
            }
        )
        return data

    def list_api_keys(
        self,
        *,
        org_id: str | None = None,
        service_account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        keys = []
        for record in self._records.values():
            if org_id is not None and record.org_id != org_id:
                continue
            if service_account_id is not None and record.service_account_id != service_account_id:
                continue
            keys.append(self.get_api_key_status(record.api_key_id))
        return [key for key in keys if key is not None]
