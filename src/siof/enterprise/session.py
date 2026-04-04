"""Session lifecycle management for enterprise MCP deployments."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionRecord:
    """Session data stored for authenticated principals."""

    session_id: str
    user_id: str
    org_id: str
    roles: list[str]
    login_time: int
    last_activity: int
    expires_at: int
    ip_address: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    graceful_logout_at: int | None = None


class SessionManager:
    """Redis-compatible session manager with in-memory fallback."""

    def __init__(
        self,
        *,
        session_ttl_seconds: int = 3600,
        inactivity_timeout_seconds: int | None = None,
        concurrent_session_limit: int = 5,
        backend: Any | None = None,
        audit_logger: Any | None = None,
    ):
        self.session_ttl_seconds = session_ttl_seconds
        self.inactivity_timeout_seconds = inactivity_timeout_seconds or session_ttl_seconds
        self.concurrent_session_limit = concurrent_session_limit
        self.backend = backend
        self.audit_logger = audit_logger

        self._sessions: dict[str, SessionRecord] = {}
        self._user_index: dict[str, list[str]] = {}
        self._activity_history: dict[str, list[dict[str, Any]]] = {}
        self._org_limits: dict[str, int] = {}
        self._role_limits: dict[str, int] = {}

    def _now(self) -> int:
        return int(time.time())

    def _record_activity(self, session_id: str, event: str, metadata: dict[str, Any] | None = None) -> None:
        history = self._activity_history.setdefault(session_id, [])
        history.append(
            {
                "timestamp": self._now(),
                "event": event,
                "metadata": metadata or {},
            }
        )

    def _persist_backend(self, session: SessionRecord) -> None:
        if self.backend is None:
            return

        key = f"session:{session.session_id}"
        payload = json.dumps(asdict(session), sort_keys=True)

        try:
            if hasattr(self.backend, "set"):
                self.backend.set(key, payload, ex=self.session_ttl_seconds)
        except Exception as exc:
            logger.warning("Session backend write failed, using in-memory fallback: %s", exc)

    def _delete_backend(self, session_id: str) -> None:
        if self.backend is None:
            return
        try:
            if hasattr(self.backend, "delete"):
                self.backend.delete(f"session:{session_id}")
        except Exception as exc:
            logger.warning("Session backend delete failed: %s", exc)

    def _remove_session(self, session_id: str, reason: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        user_sessions = self._user_index.get(session.user_id, [])
        if session_id in user_sessions:
            user_sessions.remove(session_id)

        self._delete_backend(session_id)
        self._record_activity(session_id, "invalidated", {"reason": reason})

        if self.audit_logger:
            self.audit_logger.log_event(
                category="session",
                action="invalidate",
                resource_type="session",
                resource_id=session_id,
                user_id=session.user_id,
                org_id=session.org_id,
                details={"reason": reason},
            )

        return True

    def set_org_session_limit(self, org_id: str, limit: int) -> None:
        self._org_limits[org_id] = max(1, limit)

    def set_role_session_limit(self, role: str, limit: int) -> None:
        self._role_limits[role] = max(1, limit)

    def _effective_limit(self, org_id: str, roles: list[str]) -> int:
        limits = [self.concurrent_session_limit]
        if org_id in self._org_limits:
            limits.append(self._org_limits[org_id])
        role_limits = [self._role_limits[role] for role in roles if role in self._role_limits]
        if role_limits:
            limits.append(min(role_limits))
        return max(1, min(limits))

    def enforce_concurrent_limit(
        self,
        user_id: str,
        org_id: str,
        roles: list[str],
        *,
        notify_callback: Callable[[str, str], None] | None = None,
    ) -> int:
        """Terminate oldest sessions when concurrent limit is exceeded."""
        session_ids = self._user_index.get(user_id, [])
        if not session_ids:
            return 0

        limit = self._effective_limit(org_id, roles)
        active_sessions = [self._sessions[sid] for sid in session_ids if sid in self._sessions]
        active_sessions.sort(key=lambda record: record.login_time)

        removed = 0
        while len(active_sessions) > limit:
            oldest = active_sessions.pop(0)
            if self._remove_session(oldest.session_id, reason="concurrent_limit"):
                removed += 1
                if notify_callback:
                    notify_callback(user_id, oldest.session_id)

        return removed

    def create_session(
        self,
        *,
        user_id: str,
        org_id: str,
        roles: list[str],
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
        notify_callback: Callable[[str, str], None] | None = None,
    ) -> str:
        """Create a session with TTL and concurrent-session enforcement."""
        now = self._now()
        session_id = str(uuid.uuid4())

        session = SessionRecord(
            session_id=session_id,
            user_id=user_id,
            org_id=org_id,
            roles=list(roles),
            login_time=now,
            last_activity=now,
            expires_at=now + self.session_ttl_seconds,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {},
        )

        self._sessions[session_id] = session
        self._user_index.setdefault(user_id, []).append(session_id)
        self._record_activity(session_id, "created", {"ip_address": ip_address, "user_agent": user_agent})
        self._persist_backend(session)

        self.enforce_concurrent_limit(
            user_id,
            org_id,
            roles,
            notify_callback=notify_callback,
        )

        if self.audit_logger:
            self.audit_logger.log_event(
                category="session",
                action="create",
                resource_type="session",
                resource_id=session_id,
                user_id=user_id,
                org_id=org_id,
            )

        return session_id

    def _is_expired(self, session: SessionRecord) -> bool:
        now = self._now()
        if session.graceful_logout_at is not None and now >= session.graceful_logout_at:
            return True

        if now > session.expires_at:
            return True

        if self.inactivity_timeout_seconds > 0:
            return (now - session.last_activity) > self.inactivity_timeout_seconds

        return False

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None

        if self._is_expired(session):
            self._remove_session(session_id, reason="expired")
            return None

        return asdict(session)

    def update_activity(self, session_id: str, metadata: dict[str, Any] | None = None) -> bool:
        """Update last activity and extend TTL."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if self._is_expired(session):
            self._remove_session(session_id, reason="expired")
            return False

        now = self._now()
        session.last_activity = now
        session.expires_at = now + self.session_ttl_seconds
        self._record_activity(session_id, "activity", metadata)
        self._persist_backend(session)
        return True

    def get_activity_history(self, session_id: str) -> list[dict[str, Any]]:
        return list(self._activity_history.get(session_id, []))

    def detect_suspicious_activity(self, user_id: str, *, window_seconds: int = 120, max_events: int = 50) -> bool:
        """Detect unusual request volume for active user sessions."""
        now = self._now()
        session_ids = self._user_index.get(user_id, [])
        event_count = 0
        for session_id in session_ids:
            for event in self._activity_history.get(session_id, []):
                if event["timestamp"] >= now - window_seconds:
                    event_count += 1
        return event_count > max_events

    def invalidate_session(
        self,
        session_id: str,
        *,
        reason: str = "logout",
        graceful: bool = False,
        grace_seconds: int = 5,
    ) -> bool:
        """Invalidate one session, optionally after a grace period."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        if graceful:
            session.graceful_logout_at = self._now() + max(1, grace_seconds)
            self._record_activity(session_id, "graceful_logout_requested", {"reason": reason})
            return True

        return self._remove_session(session_id, reason=reason)

    def invalidate_user_sessions(self, user_id: str, *, reason: str = "logout_all") -> int:
        """Invalidate all active sessions for a user."""
        session_ids = list(self._user_index.get(user_id, []))
        removed = 0
        for session_id in session_ids:
            if self._remove_session(session_id, reason=reason):
                removed += 1
        return removed

    def list_active_sessions(
        self,
        *,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List active sessions, optionally scoped by user or organization."""
        sessions = []
        for session_id in list(self._sessions.keys()):
            session = self._sessions.get(session_id)
            if session is None:
                continue
            if self._is_expired(session):
                self._remove_session(session_id, reason="expired")
                continue
            if user_id and session.user_id != user_id:
                continue
            if org_id and session.org_id != org_id:
                continue
            sessions.append(asdict(session))
        return sessions
