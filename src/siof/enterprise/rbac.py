"""Role and permission management for enterprise access control."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RoleDefinition:
    """Role definition with named permissions."""

    name: str
    permissions: set[str]
    description: str
    is_system: bool = False


class RoleManager:
    """Role registry with predefined and custom roles."""

    def __init__(self):
        self._roles: dict[str, RoleDefinition] = {
            "viewer": RoleDefinition(
                name="viewer",
                permissions={"read:analysis", "read:results"},
                description="Read-only access to analysis artifacts",
                is_system=True,
            ),
            "analyst": RoleDefinition(
                name="analyst",
                permissions={"read:analysis", "read:results", "write:analysis", "create:analysis"},
                description="Can run and manage analyses",
                is_system=True,
            ),
            "admin": RoleDefinition(
                name="admin",
                permissions={"*"},
                description="Full system access",
                is_system=True,
            ),
            "service": RoleDefinition(
                name="service",
                permissions={"read:analysis", "write:results", "read:results"},
                description="Service-to-service API operations",
                is_system=True,
            ),
        }

        self._cache: dict[str, RoleDefinition] = dict(self._roles)

    def create_or_update_role(
        self,
        *,
        name: str,
        permissions: set[str],
        description: str,
        is_system: bool = False,
    ) -> None:
        role = RoleDefinition(
            name=name,
            permissions=set(permissions),
            description=description,
            is_system=is_system,
        )
        self._roles[name] = role
        self._cache[name] = role
        logger.info("Role upserted: %s", name)

    def delete_role(self, name: str) -> bool:
        role = self._roles.get(name)
        if role is None:
            return False
        if role.is_system:
            raise ValueError("System roles cannot be deleted")
        del self._roles[name]
        self._cache.pop(name, None)
        logger.info("Role deleted: %s", name)
        return True

    def get_role(self, name: str) -> RoleDefinition | None:
        return self._cache.get(name)

    def get_permissions_for_roles(self, roles: list[str]) -> set[str]:
        permissions: set[str] = set()
        for role_name in roles:
            role = self._cache.get(role_name)
            if role:
                permissions.update(role.permissions)
        return permissions

    def list_roles(self) -> list[RoleDefinition]:
        return list(self._roles.values())

    def warm_cache(self) -> None:
        self._cache = dict(self._roles)


class PermissionEngine:
    """Permission checker with optional cache for repeated decisions."""

    def __init__(
        self,
        role_manager: RoleManager,
        *,
        cache_ttl_seconds: int = 300,
        cache_enabled: bool = True,
        audit_logger: Any | None = None,
    ):
        self.role_manager = role_manager
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_enabled = cache_enabled
        self.audit_logger = audit_logger

        self._permission_cache: dict[str, tuple[set[str], int]] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    def _cache_key(self, user_id: str, org_id: str) -> str:
        return f"{org_id}:{user_id}"

    def _load_permissions(self, *, user_id: str, org_id: str, roles: list[str]) -> set[str]:
        key = self._cache_key(user_id, org_id)
        now = int(time.time())

        if self.cache_enabled and key in self._permission_cache:
            permissions, expires_at = self._permission_cache[key]
            if now < expires_at:
                self._cache_hits += 1
                return set(permissions)

        self._cache_misses += 1
        permissions = self.role_manager.get_permissions_for_roles(roles)
        if self.cache_enabled:
            self._permission_cache[key] = (set(permissions), now + self.cache_ttl_seconds)
        return permissions

    def invalidate_user_cache(self, *, user_id: str, org_id: str) -> None:
        self._permission_cache.pop(self._cache_key(user_id, org_id), None)

    def invalidate_all(self) -> None:
        self._permission_cache.clear()

    @staticmethod
    def _permission_matches(granted: str, requested: str) -> bool:
        if granted == "*":
            return True
        if granted == requested:
            return True

        requested_action, _, requested_resource = requested.partition(":")
        granted_action, _, granted_resource = granted.partition(":")

        if granted_action == requested_action and granted_resource == "*":
            return True

        return False

    def check_permission(
        self,
        *,
        user_id: str,
        org_id: str,
        roles: list[str],
        action: str,
        resource_type: str,
        resource_org_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Evaluate whether principal can perform requested action."""
        if resource_org_id and resource_org_id != org_id:
            logger.warning("Cross-organization access denied for user %s", user_id)
            if self.audit_logger:
                self.audit_logger.log_event(
                    category="authorization",
                    action="permission_check",
                    resource_type=resource_type,
                    resource_id=None,
                    user_id=user_id,
                    org_id=org_id,
                    status="denied",
                    correlation_id=correlation_id,
                    details={
                        "reason": "cross_org_access",
                        "resource_org_id": resource_org_id,
                        "requested_action": action,
                    },
                )
            return False

        requested = f"{action}:{resource_type}"
        permissions = self._load_permissions(user_id=user_id, org_id=org_id, roles=roles)

        allowed = any(self._permission_matches(granted, requested) for granted in permissions)

        if self.audit_logger:
            self.audit_logger.log_event(
                category="authorization",
                action="permission_check",
                resource_type=resource_type,
                resource_id=None,
                user_id=user_id,
                org_id=org_id,
                status="success" if allowed else "denied",
                correlation_id=correlation_id,
                details={"requested_permission": requested, "roles": roles},
            )

        return allowed

    def get_cache_metrics(self) -> dict[str, int | float]:
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total) if total else 0.0
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "entries": len(self._permission_cache),
            "hit_rate": hit_rate,
        }
