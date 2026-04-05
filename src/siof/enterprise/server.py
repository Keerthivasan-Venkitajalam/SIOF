"""Enterprise MCP server facade combining auth, RBAC, sessions, and monitoring."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from siof.auth.auth_provider import AuthProvider
from siof.auth.key_manager import KeyManager
from siof.auth.login_handler import LoginHandler
from siof.auth.password_manager import PasswordManager
from siof.auth.token_manager import TokenManager
from siof.mcp_server import MCPGraphServer, MCPRequest

from .api_keys import APIKeyManager
from .audit import AuditLogger
from .config import EnterpriseConfigManager
from .errors import (
    EnterpriseError,
    auth_error,
    forbidden_error,
    to_error_response,
)
from .identity import OrganizationManager, ServiceAccountManager, UserManager
from .monitoring import HealthChecker, MetricsCollector
from .rate_limit import RateLimiter
from .rbac import PermissionEngine, RoleManager
from .security import SecretRotationManager, TLSManager, TLSSettings
from .session import SessionManager

logger = logging.getLogger(__name__)


class EnterpriseMCPServer:
    """Production-grade enterprise wrapper for MCP graph server operations."""

    def __init__(
        self,
        *,
        db_path: Path | str | None = None,
        config_path: Path | str | None = None,
    ):
        self.config_manager = EnterpriseConfigManager(config_path=config_path)
        self.config = self.config_manager.load()

        self.audit_logger = AuditLogger()

        self.key_manager = KeyManager(
            key_rotation_grace_period_seconds=int(self.config.jwt["rotation_grace_seconds"]),
        )
        private_key, public_key = self.key_manager.generate_key_pair()
        key_id = self.key_manager.register_key_pair(private_key, public_key)

        self.auth_provider = AuthProvider(
            private_key_pem=private_key,
            issuer=self.config.jwt["issuer"],
            audience=self.config.jwt["audience"],
            access_token_expiry_seconds=int(self.config.jwt["access_token_expiry_seconds"]),
            refresh_token_expiry_seconds=int(self.config.jwt["refresh_token_expiry_seconds"]),
        )
        self.auth_provider.register_public_key(key_id, public_key)

        self.password_manager = PasswordManager(
            min_length=int(self.config.security["password_min_length"]),
            bcrypt_cost=int(self.config.security["bcrypt_cost"]),
        )

        self.token_manager = TokenManager()
        self.login_handler = LoginHandler(
            max_failed_attempts=int(self.config.security["max_failed_logins"]),
            lockout_duration_seconds=int(self.config.security["lockout_duration_seconds"]),
        )

        self.session_manager = SessionManager(
            session_ttl_seconds=int(self.config.redis["session_ttl_seconds"]),
            concurrent_session_limit=5,
            audit_logger=self.audit_logger,
        )

        self.rate_limiter = RateLimiter(
            org_limit_per_minute=int(self.config.rate_limiting["org_limit_per_minute"]),
            user_limit_per_minute=int(self.config.rate_limiting["user_limit_per_minute"]),
            burst_allowance=float(self.config.rate_limiting["burst_allowance"]),
            audit_logger=self.audit_logger,
        )

        self.role_manager = RoleManager()
        self.permission_engine = PermissionEngine(
            self.role_manager,
            cache_ttl_seconds=300,
            cache_enabled=True,
            audit_logger=self.audit_logger,
        )

        self.organization_manager = OrganizationManager(audit_logger=self.audit_logger)
        self.user_manager = UserManager(
            password_manager=self.password_manager,
            audit_logger=self.audit_logger,
            session_manager=self.session_manager,
        )
        self.service_account_manager = ServiceAccountManager(audit_logger=self.audit_logger)
        self.api_key_manager = APIKeyManager(audit_logger=self.audit_logger)

        tls_settings = TLSSettings(
            enabled=bool(self.config.tls["enabled"]),
            min_version=str(self.config.tls["min_version"]),
            cert_path=self.config.tls.get("cert_path"),
            key_path=self.config.tls.get("key_path"),
            enforce_https=bool(self.config.tls.get("enforce_https", True)),
        )
        self.tls_manager = TLSManager(tls_settings, audit_logger=self.audit_logger)

        self.secret_rotation_manager = SecretRotationManager(audit_logger=self.audit_logger)
        self.secret_rotation_manager.register_secret(secret_type="jwt_signing_key")
        self.secret_rotation_manager.register_secret(secret_type="redis_credentials")

        self.metrics = MetricsCollector()
        self.health = HealthChecker()
        self.health.register_check(
            "config", lambda: {"healthy": bool(not self.tls_manager.validate())}
        )
        self.health.register_check("secrets", self._health_secrets)

        self._reset_tokens: dict[str, tuple[str, int]] = {}
        self._access_jti_to_session_id: dict[str, str] = {}

        self.mcp_server = MCPGraphServer(db_path) if db_path else None

    def _health_secrets(self) -> dict[str, Any]:
        jwt_state = self.secret_rotation_manager.get_status("jwt_signing_key")
        redis_state = self.secret_rotation_manager.get_status("redis_credentials")
        return {
            "healthy": jwt_state is not None and redis_state is not None,
            "jwt": jwt_state,
            "redis": redis_state,
        }

    def close(self) -> None:
        if self.mcp_server:
            self.mcp_server.close()

    def create_organization(self, *, name: str, description: str = "") -> dict[str, Any]:
        org = self.organization_manager.create_organization(name=name, description=description)
        return {
            "org_id": org.org_id,
            "name": org.name,
            "description": org.description,
        }

    def create_user(
        self,
        *,
        email: str,
        name: str,
        password: str,
        roles: list[str],
        org_id: str,
    ) -> dict[str, Any]:
        user = self.user_manager.create_user(
            email=email,
            name=name,
            password=password,
            roles=roles,
            org_id=org_id,
        )
        return self.user_manager.to_public_dict(user)

    def create_service_account(
        self,
        *,
        org_id: str,
        name: str,
        description: str,
        roles: list[str],
    ) -> dict[str, Any]:
        record = self.service_account_manager.create_service_account(
            org_id=org_id,
            name=name,
            description=description,
            roles=roles,
        )
        return {
            "service_account_id": record.service_account_id,
            "org_id": record.org_id,
            "name": record.name,
            "roles": list(record.roles),
        }

    def _store_refresh_token(self, token: str) -> None:
        payload = self.auth_provider.verify_token(token)
        if payload is None:
            raise auth_error()
        self.token_manager.store_refresh_token(
            payload.jti,
            payload.sub,
            payload.org_id,
            payload.exp,
        )

    def _record_access_metric(
        self, *, status_code: int, start_ts: float, auth_failure: bool = False
    ) -> None:
        latency_ms = (time.time() - start_ts) * 1000
        self.metrics.record_request(
            latency_ms=latency_ms,
            status_code=status_code,
            auth_failure=auth_failure,
        )

    def login(
        self,
        *,
        identifier: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        is_https_request: bool = True,
    ) -> dict[str, Any]:
        """Authenticate user credentials and return token pair + session."""
        start = time.time()
        try:
            self.tls_manager.assert_https(is_https_request)

            user = self.user_manager.get_user_by_email(
                identifier
            ) or self.user_manager.get_user_by_id(identifier)
            lockout_key = user.user_id if user else identifier

            is_locked, _ = self.login_handler.check_account_lockout(lockout_key)
            if is_locked:
                self.audit_logger.log_access(
                    access_type="login",
                    status="denied",
                    user_id=user.user_id if user else None,
                    org_id=user.org_id if user else None,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    reason="account_locked",
                )
                raise auth_error()

            if user is None or user.deleted_at is not None or not user.enabled:
                self.login_handler.record_failed_attempt(lockout_key)
                self.audit_logger.log_access(
                    access_type="login",
                    status="denied",
                    user_id=user.user_id if user else None,
                    org_id=user.org_id if user else None,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    reason="invalid_credentials",
                )
                raise auth_error()

            if not self.password_manager.verify_password(password, user.password_hash):
                self.login_handler.record_failed_attempt(user.user_id)
                self.audit_logger.log_access(
                    access_type="login",
                    status="denied",
                    user_id=user.user_id,
                    org_id=user.org_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    reason="invalid_credentials",
                )
                raise auth_error()

            self.login_handler.record_successful_login(user.user_id)

            token_pair = self.auth_provider.generate_tokens(user.user_id, user.org_id, user.roles)
            self._store_refresh_token(token_pair.refresh_token)
            access_payload = self.auth_provider.verify_token(token_pair.access_token)
            if access_payload is None:
                raise auth_error()

            session_id = self.session_manager.create_session(
                user_id=user.user_id,
                org_id=user.org_id,
                roles=user.roles,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self._access_jti_to_session_id[access_payload.jti] = session_id

            self.audit_logger.log_access(
                access_type="login",
                status="success",
                user_id=user.user_id,
                org_id=user.org_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"session_id": session_id},
            )

            self._record_access_metric(status_code=200, start_ts=start)
            return {
                "access_token": token_pair.access_token,
                "refresh_token": token_pair.refresh_token,
                "access_token_expires_in": token_pair.access_token_expires_in,
                "refresh_token_expires_in": token_pair.refresh_token_expires_in,
                "session_id": session_id,
                "require_password_change": user.require_password_change,
            }

        except EnterpriseError:
            self._record_access_metric(status_code=401, start_ts=start, auth_failure=True)
            raise
        except Exception:
            self._record_access_metric(status_code=401, start_ts=start, auth_failure=True)
            raise auth_error()

    def refresh_access_token(
        self,
        *,
        refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        is_https_request: bool = True,
    ) -> dict[str, Any]:
        """Exchange one-time refresh token for new access + refresh tokens."""
        start = time.time()
        try:
            self.tls_manager.assert_https(is_https_request)

            payload = self.auth_provider.verify_token(refresh_token)
            if payload is None:
                raise auth_error()

            token_data = self.token_manager.validate_refresh_token(payload.jti)
            if token_data is None:
                raise auth_error()

            if not self.token_manager.mark_token_used(payload.jti):
                raise auth_error()

            user = self.user_manager.get_user_by_id(payload.sub)
            if user is None or user.deleted_at is not None or not user.enabled:
                raise auth_error()

            token_pair = self.auth_provider.generate_tokens(user.user_id, user.org_id, user.roles)
            self._store_refresh_token(token_pair.refresh_token)

            old_jti = payload.jti
            new_payload = self.auth_provider.verify_token(token_pair.refresh_token)
            new_jti = new_payload.jti if new_payload else ""

            self.audit_logger.log_access(
                access_type="token_refresh",
                status="success",
                user_id=user.user_id,
                org_id=user.org_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"old_token_id": old_jti, "new_token_id": new_jti},
            )

            self._record_access_metric(status_code=200, start_ts=start)
            return {
                "access_token": token_pair.access_token,
                "refresh_token": token_pair.refresh_token,
                "access_token_expires_in": token_pair.access_token_expires_in,
                "refresh_token_expires_in": token_pair.refresh_token_expires_in,
            }
        except EnterpriseError:
            self._record_access_metric(status_code=401, start_ts=start, auth_failure=True)
            raise
        except Exception:
            self._record_access_metric(status_code=401, start_ts=start, auth_failure=True)
            raise auth_error()

    def logout(
        self,
        *,
        access_token: str,
        all_sessions: bool = False,
        reason: str = "user_logout",
        graceful: bool = False,
    ) -> dict[str, Any]:
        """Invalidate current or all sessions for the authenticated user."""
        payload = self.auth_provider.verify_token(access_token)
        if payload is None:
            raise auth_error()

        if all_sessions:
            count = self.session_manager.invalidate_user_sessions(payload.sub, reason=reason)
        else:
            session_id = self._access_jti_to_session_id.get(payload.jti)
            count = 0
            if session_id and self.session_manager.invalidate_session(
                session_id,
                reason=reason,
                graceful=graceful,
            ):
                count = 1

        self.audit_logger.log_access(
            access_type="logout",
            status="success",
            user_id=payload.sub,
            org_id=payload.org_id,
            reason=reason,
            details={"all_sessions": all_sessions, "count": count},
        )

        return {"invalidated_sessions": count}

    def revoke_all_refresh_tokens(self, user_id: str) -> int:
        return self.token_manager.revoke_user_tokens(user_id)

    def create_password_reset_token(self, user_id: str, *, ttl_seconds: int = 3600) -> str:
        user = self.user_manager.get_user_by_id(user_id)
        if user is None:
            raise ValueError("User not found")

        token = f"reset_{user_id}_{int(time.time())}"
        self._reset_tokens[token] = (user_id, int(time.time()) + ttl_seconds)
        return token

    def reset_password(self, *, reset_token: str, new_password: str) -> bool:
        token_data = self._reset_tokens.get(reset_token)
        if token_data is None:
            return False

        user_id, expires_at = token_data
        if int(time.time()) > expires_at:
            del self._reset_tokens[reset_token]
            return False

        user = self.user_manager.get_user_by_id(user_id)
        if user is None:
            return False

        user.password_hash = self.password_manager.hash_password(new_password)
        user.require_password_change = False
        user.updated_at = int(time.time())
        del self._reset_tokens[reset_token]

        self.audit_logger.log_event(
            category="security",
            action="password_change",
            resource_type="user",
            resource_id=user.user_id,
            user_id=user.user_id,
            org_id=user.org_id,
            status="success",
        )
        return True

    def authenticate_api_key(self, raw_api_key: str) -> dict[str, Any]:
        """Authenticate API key and return principal context."""
        if not self.api_key_manager.validate_key_format(raw_api_key):
            self.audit_logger.log_access(
                access_type="api_key_auth",
                status="denied",
                user_id=None,
                org_id=None,
                reason="invalid_key_format",
            )
            raise auth_error()

        result = self.api_key_manager.validate_api_key(raw_api_key)
        if result is None:
            self.audit_logger.log_access(
                access_type="api_key_auth",
                status="denied",
                user_id=None,
                org_id=None,
                reason="invalid_or_expired_key",
            )
            raise auth_error()

        self.audit_logger.log_access(
            access_type="api_key_auth",
            status="success",
            user_id=result["service_account_id"],
            org_id=result["org_id"],
            details={"api_key_id": result["api_key_id"]},
        )
        return result

    def rotate_api_key(self, api_key_id: str, *, grace_days: int | None = None) -> dict[str, Any]:
        return self.api_key_manager.rotate_api_key(api_key_id, grace_days=grace_days)

    def revoke_api_key(self, api_key_id: str, *, reason: str) -> bool:
        return self.api_key_manager.revoke_api_key(api_key_id, reason=reason)

    def rotate_jwt_signing_key(self) -> dict[str, Any]:
        """Rotate JWT signing key and keep old verification key during grace period."""
        new_key_id = self.key_manager.rotate_keys()
        private = self.key_manager.get_private_key(new_key_id)
        if private is None:
            raise RuntimeError("Failed to retrieve new private key")

        self.auth_provider.private_key_pem = private

        for key_id, public_key in self.key_manager.get_active_public_keys().items():
            self.auth_provider.register_public_key(key_id, public_key)

        self.secret_rotation_manager.rotate_secret("jwt_signing_key", reason="manual")

        return {
            "current_key_id": self.key_manager.get_current_key_id(),
            "active_public_keys": list(self.key_manager.get_active_public_keys().keys()),
        }

    def rotate_redis_credentials(self) -> dict[str, Any]:
        state = self.secret_rotation_manager.rotate_secret("redis_credentials", reason="manual")
        return {
            "current_secret_id": state.current_secret_id,
            "previous_secret_id": state.previous_secret_id,
            "previous_valid_until": state.previous_valid_until,
        }

    def authorize(
        self,
        *,
        user_id: str,
        org_id: str,
        roles: list[str],
        action: str,
        resource_type: str,
        resource_org_id: str | None = None,
    ) -> None:
        allowed = self.permission_engine.check_permission(
            user_id=user_id,
            org_id=org_id,
            roles=roles,
            action=action,
            resource_type=resource_type,
            resource_org_id=resource_org_id,
        )
        if not allowed:
            raise forbidden_error()

    def enforce_rate_limits(self, *, org_id: str, user_id: str, role: str) -> dict[str, Any]:
        result = self.rate_limiter.check_combined_limit(org_id=org_id, user_id=user_id, role=role)
        return result

    def execute_tool(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        access_token: str | None = None,
        api_key: str | None = None,
        approval_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute MCP tool after enterprise authN/authZ and rate-limit checks."""
        if self.mcp_server is None:
            raise RuntimeError("MCP server is not configured")

        principal: dict[str, Any]
        if api_key:
            principal = self.authenticate_api_key(api_key)
            user_id = principal["service_account_id"]
            org_id = principal["org_id"]
            roles = principal["roles"]
        else:
            if not access_token:
                raise auth_error()
            payload = self.auth_provider.verify_token(access_token)
            if payload is None:
                raise auth_error()
            user_id = payload.sub
            org_id = payload.org_id
            roles = payload.roles

        rate = self.enforce_rate_limits(
            org_id=org_id, user_id=user_id, role=roles[0] if roles else "viewer"
        )
        if not rate["allowed"]:
            raise EnterpriseError(
                code="rate_limit_exceeded",
                status_code=429,
                safe_message="Too Many Requests",
                internal_message="Rate limit exceeded",
                details={"retry_after": rate["retry_after_seconds"]},
            )

        # Basic tool-to-permission mapping.
        action = "read"
        if tool == "apply_patch_to_file":
            action = "write"

        self.authorize(
            user_id=user_id,
            org_id=org_id,
            roles=roles,
            action=action,
            resource_type="analysis",
            resource_org_id=org_id,
        )

        request = MCPRequest(
            tool=tool,
            args=args,
            role=roles[0] if roles else "viewer",
            approval_token=approval_token,
            org=org_id,
            user_id=user_id,
        )
        response = self.mcp_server.handle(request)

        return {
            "ok": response.ok,
            "result": response.result,
            "error": response.error,
            "request_id": response.request_id,
            "trace_id": response.trace_id,
            "latency_ms": response.latency_ms,
        }

    def get_audit_logs(
        self, *, filters: dict[str, Any] | None = None, page: int = 1, page_size: int = 100
    ) -> dict[str, Any]:
        return self.audit_logger.query_logs(filters=filters, page=page, page_size=page_size)

    def export_audit_logs(self, *, format_name: str, filters: dict[str, Any] | None = None) -> str:
        return self.audit_logger.export_logs(format_name=format_name, filters=filters)

    def get_health(self) -> tuple[int, dict[str, Any]]:
        return self.health.health()

    def get_readiness(self) -> tuple[int, dict[str, Any]]:
        return self.health.readiness()

    def get_liveness(self) -> tuple[int, dict[str, Any]]:
        return self.health.liveness()

    def get_prometheus_metrics(self) -> str:
        self.metrics.set_gauge(
            "active_sessions", float(len(self.session_manager.list_active_sessions()))
        )
        self.metrics.set_gauge("api_keys_active", float(len(self.api_key_manager.list_api_keys())))
        for violator in self.rate_limiter.get_repeated_violators():
            self.metrics.increment_counter(
                "rate_limit_violations_total", labels={"bucket": violator}
            )
        return self.metrics.export_prometheus()

    def safe_call(self, fn: Any, *args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        """Call server API and convert exceptions to secure error responses."""
        try:
            result = fn(*args, **kwargs)
            return 200, {"result": result}
        except Exception as exc:
            return to_error_response(exc)
