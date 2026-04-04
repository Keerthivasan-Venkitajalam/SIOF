"""Organization, user, and service-account management for enterprise MCP."""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from siof.auth.password_manager import PasswordManager

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(slots=True)
class OrganizationRecord:
    org_id: str
    name: str
    description: str
    enabled: bool
    config: dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    archived_at: int | None = None


@dataclass(slots=True)
class UserRecord:
    user_id: str
    org_id: str
    email: str
    name: str
    password_hash: str
    roles: list[str]
    enabled: bool = True
    require_password_change: bool = True
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    deleted_at: int | None = None


@dataclass(slots=True)
class ServiceAccountRecord:
    service_account_id: str
    org_id: str
    name: str
    description: str
    roles: list[str]
    enabled: bool = True
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    deleted_at: int | None = None


class OrganizationManager:
    """Manage organization lifecycle and configuration."""

    def __init__(self, audit_logger: Any | None = None):
        self.audit_logger = audit_logger
        self._organizations: dict[str, OrganizationRecord] = {}

    def create_organization(self, *, name: str, description: str = "", config: dict[str, Any] | None = None) -> OrganizationRecord:
        org_id = str(uuid.uuid4())
        org = OrganizationRecord(
            org_id=org_id,
            name=name,
            description=description,
            enabled=True,
            config=config or {},
        )
        self._organizations[org_id] = org

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=org_id,
                action="create",
                resource_type="organization",
                resource_id=org_id,
                old_value=None,
                new_value=asdict(org),
            )

        return org

    def get_organization(self, org_id: str) -> OrganizationRecord | None:
        return self._organizations.get(org_id)

    def update_organization(self, org_id: str, **updates: Any) -> OrganizationRecord:
        org = self._organizations.get(org_id)
        if org is None:
            raise ValueError("Organization not found")

        old_value = asdict(org)
        for key in ["name", "description", "enabled", "config"]:
            if key in updates and updates[key] is not None:
                setattr(org, key, updates[key])
        org.updated_at = int(time.time())

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=org_id,
                action="update",
                resource_type="organization",
                resource_id=org_id,
                old_value=old_value,
                new_value=asdict(org),
            )

        return org

    def delete_organization(self, org_id: str) -> bool:
        org = self._organizations.get(org_id)
        if org is None:
            return False

        old_value = asdict(org)
        org.enabled = False
        org.archived_at = int(time.time())
        org.updated_at = int(time.time())

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=org_id,
                action="delete",
                resource_type="organization",
                resource_id=org_id,
                old_value=old_value,
                new_value=asdict(org),
            )

        return True

    def list_organizations(self) -> list[OrganizationRecord]:
        return list(self._organizations.values())

    def get_metadata_and_statistics(
        self,
        org_id: str,
        *,
        users: list[UserRecord] | None = None,
        service_accounts: list[ServiceAccountRecord] | None = None,
    ) -> dict[str, Any]:
        org = self.get_organization(org_id)
        if org is None:
            raise ValueError("Organization not found")

        users = users or []
        service_accounts = service_accounts or []

        return {
            "organization": asdict(org),
            "stats": {
                "user_count": len([user for user in users if user.org_id == org_id and user.deleted_at is None]),
                "service_account_count": len(
                    [
                        svc
                        for svc in service_accounts
                        if svc.org_id == org_id and svc.deleted_at is None
                    ]
                ),
            },
        }


class UserManager:
    """Manage user lifecycle and password-safe credentials."""

    def __init__(
        self,
        *,
        password_manager: PasswordManager | None = None,
        audit_logger: Any | None = None,
        session_manager: Any | None = None,
    ):
        self.password_manager = password_manager or PasswordManager()
        self.audit_logger = audit_logger
        self.session_manager = session_manager

        self._users: dict[str, UserRecord] = {}
        self._email_index: dict[str, str] = {}

    @staticmethod
    def _validate_email(email: str) -> None:
        if not EMAIL_PATTERN.match(email):
            raise ValueError("Invalid email format")

    def create_user(
        self,
        *,
        email: str,
        name: str,
        password: str,
        roles: list[str],
        org_id: str,
        require_password_change: bool = True,
    ) -> UserRecord:
        normalized_email = email.strip().lower()
        self._validate_email(normalized_email)

        if normalized_email in self._email_index:
            raise ValueError("Email already exists")

        password_hash = self.password_manager.hash_password(password)
        user_id = str(uuid.uuid4())

        user = UserRecord(
            user_id=user_id,
            org_id=org_id,
            email=normalized_email,
            name=name,
            password_hash=password_hash,
            roles=list(roles),
            require_password_change=require_password_change,
        )

        self._users[user_id] = user
        self._email_index[normalized_email] = user_id

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id=user_id,
                org_id=org_id,
                action="create",
                resource_type="user",
                resource_id=user_id,
                old_value=None,
                new_value=self.to_public_dict(user),
            )

        return user

    def bulk_create(self, payloads: list[dict[str, Any]]) -> list[UserRecord]:
        users = []
        for payload in payloads:
            users.append(
                self.create_user(
                    email=payload["email"],
                    name=payload.get("name", ""),
                    password=payload["password"],
                    roles=payload.get("roles", ["viewer"]),
                    org_id=payload["org_id"],
                    require_password_change=payload.get("require_password_change", True),
                )
            )
        return users

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        user_id = self._email_index.get(email.strip().lower())
        if not user_id:
            return None
        return self._users.get(user_id)

    def update_user(self, user_id: str, *, name: str | None = None, email: str | None = None, roles: list[str] | None = None) -> UserRecord:
        user = self._users.get(user_id)
        if user is None:
            raise ValueError("User not found")

        old_value = self.to_public_dict(user)

        if email is not None:
            normalized_email = email.strip().lower()
            self._validate_email(normalized_email)
            existing = self._email_index.get(normalized_email)
            if existing and existing != user_id:
                raise ValueError("Email already exists")
            self._email_index.pop(user.email, None)
            self._email_index[normalized_email] = user_id
            user.email = normalized_email

        if name is not None:
            user.name = name
        if roles is not None:
            user.roles = list(roles)

        user.updated_at = int(time.time())

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id=user.user_id,
                org_id=user.org_id,
                action="update",
                resource_type="user",
                resource_id=user.user_id,
                old_value=old_value,
                new_value=self.to_public_dict(user),
            )

        return user

    def set_user_enabled(self, user_id: str, *, enabled: bool) -> UserRecord:
        user = self._users.get(user_id)
        if user is None:
            raise ValueError("User not found")

        old_value = self.to_public_dict(user)
        user.enabled = enabled
        user.updated_at = int(time.time())

        if not enabled and self.session_manager:
            self.session_manager.invalidate_user_sessions(user_id, reason="user_disabled")

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id=user.user_id,
                org_id=user.org_id,
                action="disable" if not enabled else "enable",
                resource_type="user",
                resource_id=user.user_id,
                old_value=old_value,
                new_value=self.to_public_dict(user),
            )

        return user

    def delete_user(self, user_id: str) -> bool:
        user = self._users.get(user_id)
        if user is None:
            return False

        old_value = self.to_public_dict(user)
        user.deleted_at = int(time.time())
        user.enabled = False
        user.updated_at = int(time.time())

        if self.session_manager:
            self.session_manager.invalidate_user_sessions(user_id, reason="user_deleted")

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id=user.user_id,
                org_id=user.org_id,
                action="delete",
                resource_type="user",
                resource_id=user.user_id,
                old_value=old_value,
                new_value=self.to_public_dict(user),
            )

        return True

    def verify_credentials(self, identifier: str, password: str) -> UserRecord | None:
        user = self.get_user_by_email(identifier) or self.get_user_by_id(identifier)
        if user is None or not user.enabled or user.deleted_at is not None:
            return None

        if not self.password_manager.verify_password(password, user.password_hash):
            return None

        return user

    def list_users(self, *, org_id: str | None = None) -> list[UserRecord]:
        users = list(self._users.values())
        if org_id is not None:
            users = [user for user in users if user.org_id == org_id]
        return users

    @staticmethod
    def to_public_dict(user: UserRecord) -> dict[str, Any]:
        data = asdict(user)
        data.pop("password_hash", None)
        return data


class ServiceAccountManager:
    """Manage service accounts and integration with API key management."""

    def __init__(self, *, audit_logger: Any | None = None):
        self.audit_logger = audit_logger
        self._service_accounts: dict[str, ServiceAccountRecord] = {}

    def create_service_account(
        self,
        *,
        org_id: str,
        name: str,
        description: str,
        roles: list[str],
    ) -> ServiceAccountRecord:
        service_account_id = str(uuid.uuid4())
        record = ServiceAccountRecord(
            service_account_id=service_account_id,
            org_id=org_id,
            name=name,
            description=description,
            roles=list(roles),
        )

        self._service_accounts[service_account_id] = record

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=org_id,
                action="create",
                resource_type="service_account",
                resource_id=service_account_id,
                old_value=None,
                new_value=asdict(record),
            )

        return record

    def get_service_account(self, service_account_id: str) -> ServiceAccountRecord | None:
        return self._service_accounts.get(service_account_id)

    def update_service_account(
        self,
        service_account_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        roles: list[str] | None = None,
    ) -> ServiceAccountRecord:
        record = self._service_accounts.get(service_account_id)
        if record is None:
            raise ValueError("Service account not found")

        old_value = asdict(record)

        if name is not None:
            record.name = name
        if description is not None:
            record.description = description
        if roles is not None:
            record.roles = list(roles)

        record.updated_at = int(time.time())

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=record.org_id,
                action="update",
                resource_type="service_account",
                resource_id=service_account_id,
                old_value=old_value,
                new_value=asdict(record),
            )

        return record

    def set_service_account_enabled(self, service_account_id: str, *, enabled: bool) -> ServiceAccountRecord:
        record = self._service_accounts.get(service_account_id)
        if record is None:
            raise ValueError("Service account not found")

        old_value = asdict(record)
        record.enabled = enabled
        record.updated_at = int(time.time())

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=record.org_id,
                action="enable" if enabled else "disable",
                resource_type="service_account",
                resource_id=service_account_id,
                old_value=old_value,
                new_value=asdict(record),
            )

        return record

    def delete_service_account(self, service_account_id: str) -> bool:
        record = self._service_accounts.get(service_account_id)
        if record is None:
            return False

        old_value = asdict(record)
        record.enabled = False
        record.deleted_at = int(time.time())
        record.updated_at = int(time.time())

        if self.audit_logger:
            self.audit_logger.log_mutation(
                user_id="system",
                org_id=record.org_id,
                action="delete",
                resource_type="service_account",
                resource_id=service_account_id,
                old_value=old_value,
                new_value=asdict(record),
            )

        return True

    def list_service_accounts(self, *, org_id: str | None = None) -> list[ServiceAccountRecord]:
        records = list(self._service_accounts.values())
        if org_id is not None:
            records = [record for record in records if record.org_id == org_id]
        return records

    def create_api_key_for_service_account(
        self,
        *,
        service_account_id: str,
        api_key_manager: Any,
        name: str,
        expiry_days: int = 365,
        owner_email: str | None = None,
    ) -> dict[str, Any]:
        record = self._service_accounts.get(service_account_id)
        if record is None:
            raise ValueError("Service account not found")
        if not record.enabled:
            raise ValueError("Service account disabled")

        return api_key_manager.create_api_key(
            org_id=record.org_id,
            service_account_id=record.service_account_id,
            name=name,
            expiry_days=expiry_days,
            owner_email=owner_email,
            roles=record.roles,
        )
