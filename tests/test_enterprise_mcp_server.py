"""Comprehensive tests for Enterprise MCP Server implementation."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from siof.enterprise import (
    APIKeyManager,
    AuditLogger,
    EnterpriseConfigManager,
    EnterpriseError,
    EnterpriseMCPServer,
    PermissionEngine,
    RateLimiter,
    RoleManager,
    SecretRotationManager,
    SessionManager,
)


class TestSessionManager:
    def test_create_get_and_invalidate_session(self) -> None:
        manager = SessionManager(session_ttl_seconds=30)
        session_id = manager.create_session(
            user_id="user-1",
            org_id="org-1",
            roles=["analyst"],
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

        session = manager.get_session(session_id)
        assert session is not None
        assert session["user_id"] == "user-1"

        assert manager.invalidate_session(session_id)
        assert manager.get_session(session_id) is None

    def test_concurrent_session_limit_terminates_oldest(self) -> None:
        manager = SessionManager(concurrent_session_limit=2)
        first = manager.create_session(user_id="user-1", org_id="org-1", roles=["viewer"])
        manager.create_session(user_id="user-1", org_id="org-1", roles=["viewer"])
        manager.create_session(user_id="user-1", org_id="org-1", roles=["viewer"])

        active = manager.list_active_sessions(user_id="user-1")
        active_ids = {session["session_id"] for session in active}

        assert len(active) == 2
        assert first not in active_ids

    def test_activity_tracking_and_history(self) -> None:
        manager = SessionManager(session_ttl_seconds=30)
        session_id = manager.create_session(user_id="user-1", org_id="org-1", roles=["viewer"])

        assert manager.update_activity(session_id, metadata={"path": "/api/tool"})
        history = manager.get_activity_history(session_id)

        assert len(history) >= 2
        assert any(event["event"] == "activity" for event in history)


class TestRateLimiter:
    def test_token_bucket_rejects_when_exhausted(self) -> None:
        limiter = RateLimiter(org_limit_per_minute=2, user_limit_per_minute=2, burst_allowance=0.0)

        assert limiter.check_org_limit("org-1").allowed
        assert limiter.check_org_limit("org-1").allowed

        denied = limiter.check_org_limit("org-1")
        assert not denied.allowed
        assert denied.retry_after_seconds >= 1

    def test_role_multiplier_applies_to_user_limit(self) -> None:
        limiter = RateLimiter(user_limit_per_minute=2, burst_allowance=0.0)

        # viewer has 0.5x multiplier -> effective limit of 1 request/minute
        assert limiter.check_user_limit("user-1", role="viewer").allowed
        denied = limiter.check_user_limit("user-1", role="viewer")

        assert not denied.allowed

    def test_combined_limit_returns_most_restrictive(self) -> None:
        limiter = RateLimiter(org_limit_per_minute=1, user_limit_per_minute=10, burst_allowance=0.0)

        first = limiter.check_combined_limit(org_id="org-1", user_id="user-1", role="analyst")
        assert first["allowed"]

        second = limiter.check_combined_limit(org_id="org-1", user_id="user-1", role="analyst")
        assert not second["allowed"]
        assert second["retry_after_seconds"] >= 1


class TestRBACPermissionEngine:
    def test_default_roles_and_custom_role(self) -> None:
        role_manager = RoleManager()
        assert role_manager.get_role("viewer") is not None
        assert role_manager.get_role("admin") is not None

        role_manager.create_or_update_role(
            name="security_auditor",
            permissions={"read:analysis", "read:audit"},
            description="Security review role",
        )
        custom = role_manager.get_role("security_auditor")
        assert custom is not None
        assert "read:audit" in custom.permissions

    def test_permission_checks_and_cross_org_isolation(self) -> None:
        role_manager = RoleManager()
        engine = PermissionEngine(role_manager, cache_ttl_seconds=300, cache_enabled=True)

        assert engine.check_permission(
            user_id="u1",
            org_id="org-1",
            roles=["analyst"],
            action="read",
            resource_type="analysis",
            resource_org_id="org-1",
        )

        assert not engine.check_permission(
            user_id="u1",
            org_id="org-1",
            roles=["analyst"],
            action="read",
            resource_type="analysis",
            resource_org_id="org-2",
        )

        metrics = engine.get_cache_metrics()
        assert metrics["entries"] >= 1


class TestAuditLogger:
    def test_mutation_query_and_exports(self) -> None:
        audit = AuditLogger(retention_days=365)
        audit.log_mutation(
            user_id="u1",
            org_id="org-1",
            action="create",
            resource_type="user",
            resource_id="user-1",
            old_value=None,
            new_value={"email": "a@example.com"},
        )
        audit.log_access(
            access_type="login",
            status="success",
            user_id="u1",
            org_id="org-1",
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

        result = audit.query_logs(filters={"org_id": "org-1"}, page=1, page_size=10)
        assert result["total"] == 2

        exported_json = audit.export_logs(format_name="json", filters={"org_id": "org-1"})
        exported_csv = audit.export_logs(format_name="csv", filters={"org_id": "org-1"})

        assert "create" in exported_json
        assert "correlation_id" in exported_csv

    def test_detect_suspicious_failed_logins(self) -> None:
        audit = AuditLogger()
        for _ in range(6):
            audit.log_access(
                access_type="login",
                status="denied",
                user_id="u1",
                org_id="org-1",
                reason="invalid_credentials",
            )

        suspects = audit.detect_suspicious_failed_logins(window_seconds=300, threshold=5)
        assert "u1" in suspects


class TestApiKeyManager:
    def test_create_validate_rotate_and_revoke_key(self) -> None:
        manager = APIKeyManager(default_expiry_days=365)

        created = manager.create_api_key(
            org_id="org-1",
            service_account_id="svc-1",
            name="primary",
            roles=["service"],
        )
        raw_key = created["api_key"]

        validated = manager.validate_api_key(raw_key)
        assert validated is not None
        assert validated["org_id"] == "org-1"

        rotated = manager.rotate_api_key(created["api_key_id"], grace_days=7)
        assert manager.validate_api_key(raw_key) is not None

        assert manager.revoke_api_key(rotated["api_key_id"], reason="compromised")
        assert manager.validate_api_key(rotated["api_key"]) is None


class TestEnterpriseServer:
    @pytest.fixture
    def enterprise_server(self) -> EnterpriseMCPServer:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "enterprise.db"
            server = EnterpriseMCPServer(db_path=db_path)
            try:
                yield server
            finally:
                server.close()

    def test_auth_flow_login_refresh_logout(self, enterprise_server: EnterpriseMCPServer) -> None:
        org = enterprise_server.create_organization(name="Acme", description="Org")
        user = enterprise_server.create_user(
            email="admin@acme.com",
            name="Admin",
            password="StrongPass123!",
            roles=["admin"],
            org_id=org["org_id"],
        )

        login_result = enterprise_server.login(
            identifier=user["email"],
            password="StrongPass123!",
            ip_address="127.0.0.1",
            user_agent="pytest",
            is_https_request=True,
        )

        assert login_result["access_token"]
        assert login_result["refresh_token"]
        assert login_result["session_id"]

        refreshed = enterprise_server.refresh_access_token(
            refresh_token=login_result["refresh_token"],
            is_https_request=True,
        )
        assert refreshed["access_token"]
        assert refreshed["refresh_token"]

        logout_result = enterprise_server.logout(
            access_token=login_result["access_token"],
            all_sessions=False,
            graceful=True,
        )
        assert logout_result["invalidated_sessions"] == 1

    def test_login_failure_returns_generic_auth_error(
        self, enterprise_server: EnterpriseMCPServer
    ) -> None:
        org = enterprise_server.create_organization(name="OrgX", description="Org")
        enterprise_server.create_user(
            email="user@orgx.com",
            name="User",
            password="StrongPass123!",
            roles=["viewer"],
            org_id=org["org_id"],
        )

        with pytest.raises(EnterpriseError) as exc_info:
            enterprise_server.login(
                identifier="user@orgx.com",
                password="WrongPassword123!",
                is_https_request=True,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.safe_message == "Authentication failed"

    def test_password_reset_flow(self, enterprise_server: EnterpriseMCPServer) -> None:
        org = enterprise_server.create_organization(name="ResetOrg")
        user = enterprise_server.create_user(
            email="reset@org.com",
            name="Reset User",
            password="StrongPass123!",
            roles=["analyst"],
            org_id=org["org_id"],
        )

        token = enterprise_server.create_password_reset_token(user["user_id"], ttl_seconds=60)
        assert (
            enterprise_server.reset_password(
                reset_token=token,
                new_password="NewStrong123!@",
            )
            is True
        )

        # Old password should fail, new one should work
        with pytest.raises(EnterpriseError):
            enterprise_server.login(
                identifier=user["email"],
                password="StrongPass123!",
                is_https_request=True,
            )

        login_result = enterprise_server.login(
            identifier=user["email"],
            password="NewStrong123!@",
            is_https_request=True,
        )
        assert login_result["access_token"]

    def test_service_account_api_key_auth(self, enterprise_server: EnterpriseMCPServer) -> None:
        org = enterprise_server.create_organization(name="SvcOrg")
        service = enterprise_server.create_service_account(
            org_id=org["org_id"],
            name="build-bot",
            description="CI bot",
            roles=["service"],
        )

        created = enterprise_server.service_account_manager.create_api_key_for_service_account(
            service_account_id=service["service_account_id"],
            api_key_manager=enterprise_server.api_key_manager,
            name="ci-key",
        )

        principal = enterprise_server.authenticate_api_key(created["api_key"])
        assert principal["service_account_id"] == service["service_account_id"]
        assert principal["org_id"] == org["org_id"]

    def test_rate_limit_and_permission_on_tool_execution(
        self, enterprise_server: EnterpriseMCPServer
    ) -> None:
        org = enterprise_server.create_organization(name="ToolOrg")
        user = enterprise_server.create_user(
            email="analyst@tool.org",
            name="Analyst",
            password="StrongPass123!",
            roles=["analyst"],
            org_id=org["org_id"],
        )
        login_result = enterprise_server.login(
            identifier=user["email"],
            password="StrongPass123!",
            is_https_request=True,
        )

        enterprise_server.rate_limiter.set_org_limit(
            org["org_id"], requests_per_minute=1, burst_allowance=0.0
        )

        first = enterprise_server.execute_tool(
            tool="find_data_lineage",
            args={"node_or_symbol": "x"},
            access_token=login_result["access_token"],
        )
        assert "ok" in first

        with pytest.raises(EnterpriseError) as exc_info:
            enterprise_server.execute_tool(
                tool="find_data_lineage",
                args={"node_or_symbol": "x"},
                access_token=login_result["access_token"],
            )

        assert exc_info.value.status_code == 429

    def test_health_and_metrics_endpoints(self, enterprise_server: EnterpriseMCPServer) -> None:
        health_status, health_payload = enterprise_server.get_health()
        ready_status, ready_payload = enterprise_server.get_readiness()
        live_status, live_payload = enterprise_server.get_liveness()

        assert health_status in {200, 503}
        assert ready_status in {200, 503}
        assert live_status == 200
        assert "status" in health_payload
        assert "status" in ready_payload
        assert live_payload["status"] == "alive"

        metrics = enterprise_server.get_prometheus_metrics()
        assert "active_sessions" in metrics

    def test_secret_rotation_states(self, enterprise_server: EnterpriseMCPServer) -> None:
        rotated = enterprise_server.rotate_jwt_signing_key()
        assert rotated["current_key_id"]
        assert rotated["active_public_keys"]

        redis_rotation = enterprise_server.rotate_redis_credentials()
        assert redis_rotation["current_secret_id"]


class TestConfigManager:
    def test_yaml_env_load_and_hot_reload(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "enterprise.yaml"
        config_file.write_text(
            """
jwt:
  issuer: custom-issuer
  audience: custom-audience
rate_limiting:
  org_limit_per_minute: 20
  user_limit_per_minute: 5
redis:
  url: redis://localhost:6379/0
tls:
  enabled: false
""".strip(),
            encoding="utf-8",
        )

        manager = EnterpriseConfigManager(config_path=config_file)
        loaded = manager.load()
        assert loaded.jwt["issuer"] == "custom-issuer"
        assert loaded.rate_limiting["user_limit_per_minute"] == 5

        monkeypatch.setenv("SIOF_ENTERPRISE_RATE_LIMITING__ORG_LIMIT_PER_MINUTE", "99")
        loaded2 = manager.load()
        assert loaded2.rate_limiting["org_limit_per_minute"] == 99

        time.sleep(1.1)
        config_file.write_text(
            """
jwt:
  issuer: changed-issuer
  audience: custom-audience
redis:
  url: redis://localhost:6379/0
rate_limiting:
  org_limit_per_minute: 10
  user_limit_per_minute: 2
tls:
  enabled: false
""".strip(),
            encoding="utf-8",
        )

        assert manager.hot_reload_if_changed()
        assert manager.get_config().jwt["issuer"] == "changed-issuer"


class TestSecretRotationManager:
    def test_rotation_accepts_old_and_new_during_grace(self) -> None:
        manager = SecretRotationManager()
        state = manager.register_secret(secret_type="jwt", interval_days=90, grace_period_seconds=2)
        old_secret = state.current_secret_id

        rotated = manager.rotate_secret("jwt", reason="manual")
        new_secret = rotated.current_secret_id

        assert manager.accepts_secret("jwt", new_secret)
        assert manager.accepts_secret("jwt", old_secret)

        time.sleep(2.1)
        assert not manager.accepts_secret("jwt", old_secret)
