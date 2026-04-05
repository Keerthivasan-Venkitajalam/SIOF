"""Enterprise audit logging primitives.

Provides immutable, append-only audit events for mutation and access tracking,
with filtering, pagination, full-text search, and export helpers.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditLogEntry:
    """Single immutable audit log entry."""

    log_id: str
    timestamp: int
    correlation_id: str
    category: str
    action: str
    resource_type: str
    resource_id: str | None
    status: str
    user_id: str | None
    org_id: str | None
    details: dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """Append-only audit logger with query and export support."""

    def __init__(self, retention_days: int = 365):
        self.retention_days = retention_days
        self._entries: list[AuditLogEntry] = []

    def _now(self) -> int:
        return int(time.time())

    def _new_correlation_id(self, correlation_id: str | None) -> str:
        return correlation_id or str(uuid.uuid4())

    def _append(self, entry: AuditLogEntry) -> None:
        self._entries.append(entry)

    def log_event(
        self,
        *,
        category: str,
        action: str,
        resource_type: str,
        status: str = "success",
        resource_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Log a generic audit event."""
        entry = AuditLogEntry(
            log_id=str(uuid.uuid4()),
            timestamp=self._now(),
            correlation_id=self._new_correlation_id(correlation_id),
            category=category,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            user_id=user_id,
            org_id=org_id,
            details=details or {},
        )
        self._append(entry)
        return entry

    def log_mutation(
        self,
        *,
        user_id: str,
        org_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        old_value: dict[str, Any] | None,
        new_value: dict[str, Any] | None,
        correlation_id: str | None = None,
    ) -> AuditLogEntry:
        """Log create, update, or delete mutation."""
        return self.log_event(
            category="mutation",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            org_id=org_id,
            correlation_id=correlation_id,
            details={"old_value": old_value, "new_value": new_value},
        )

    def log_access(
        self,
        *,
        access_type: str,
        status: str,
        user_id: str | None,
        org_id: str | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Log access events: login, logout, refresh, deny, api-key auth."""
        merged_details = {
            "access_type": access_type,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "reason": reason,
        }
        if details:
            merged_details.update(details)

        return self.log_event(
            category="access",
            action=access_type,
            resource_type="auth",
            status=status,
            user_id=user_id,
            org_id=org_id,
            correlation_id=correlation_id,
            details=merged_details,
        )

    def log_api_key_usage(
        self,
        *,
        api_key_id: str,
        org_id: str,
        action: str,
        resource: str,
        status: str = "success",
        correlation_id: str | None = None,
    ) -> AuditLogEntry:
        """Log API key usage events."""
        return self.log_event(
            category="access",
            action="api_key_usage",
            resource_type="api_key",
            resource_id=api_key_id,
            org_id=org_id,
            status=status,
            correlation_id=correlation_id,
            details={"requested_action": action, "resource": resource},
        )

    def _apply_filters(
        self, entries: list[AuditLogEntry], filters: dict[str, Any]
    ) -> list[AuditLogEntry]:
        user_id = filters.get("user_id")
        org_id = filters.get("org_id")
        action = filters.get("action")
        resource_type = filters.get("resource_type")
        category = filters.get("category")
        correlation_id = filters.get("correlation_id")
        start_ts = filters.get("start_ts")
        end_ts = filters.get("end_ts")
        full_text = filters.get("full_text")

        filtered = entries
        if user_id is not None:
            filtered = [entry for entry in filtered if entry.user_id == user_id]
        if org_id is not None:
            filtered = [entry for entry in filtered if entry.org_id == org_id]
        if action is not None:
            filtered = [entry for entry in filtered if entry.action == action]
        if resource_type is not None:
            filtered = [entry for entry in filtered if entry.resource_type == resource_type]
        if category is not None:
            filtered = [entry for entry in filtered if entry.category == category]
        if correlation_id is not None:
            filtered = [entry for entry in filtered if entry.correlation_id == correlation_id]
        if start_ts is not None:
            filtered = [entry for entry in filtered if entry.timestamp >= int(start_ts)]
        if end_ts is not None:
            filtered = [entry for entry in filtered if entry.timestamp <= int(end_ts)]
        if full_text:
            needle = str(full_text).lower()
            filtered = [
                entry
                for entry in filtered
                if needle in json.dumps(asdict(entry), sort_keys=True).lower()
            ]

        return filtered

    def query_logs(
        self,
        *,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 100,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """Query logs with filtering, sorting, and pagination."""
        filters = filters or {}
        page = max(page, 1)
        page_size = max(min(page_size, 1000), 1)

        filtered = self._apply_filters(self._entries, filters)

        reverse = sort_order.lower() == "desc"
        if sort_by not in {"timestamp", "user_id", "action"}:
            sort_by = "timestamp"

        filtered = sorted(
            filtered,
            key=lambda entry: (
                getattr(entry, sort_by) if getattr(entry, sort_by) is not None else ""
            ),
            reverse=reverse,
        )

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]

        return {
            "items": [asdict(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    def export_logs(self, *, format_name: str, filters: dict[str, Any] | None = None) -> str:
        """Export logs as JSON or CSV text."""
        data = self.query_logs(filters=filters, page=1, page_size=100000, sort_order="asc")
        items = data["items"]

        format_name = format_name.lower()
        if format_name == "json":
            return json.dumps(items, indent=2, sort_keys=True)

        if format_name == "csv":
            output = io.StringIO()
            fieldnames = [
                "log_id",
                "timestamp",
                "correlation_id",
                "category",
                "action",
                "resource_type",
                "resource_id",
                "status",
                "user_id",
                "org_id",
                "details",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                row = dict(item)
                row["details"] = json.dumps(row.get("details", {}), sort_keys=True)
                writer.writerow(row)
            return output.getvalue()

        raise ValueError("Unsupported export format. Expected 'json' or 'csv'.")

    def cleanup_expired_logs(self) -> int:
        """Apply retention policy and remove expired logs."""
        cutoff = self._now() - (self.retention_days * 86400)
        kept = [entry for entry in self._entries if entry.timestamp >= cutoff]
        removed = len(self._entries) - len(kept)
        self._entries = kept
        if removed:
            logger.info("Removed %s expired audit entries", removed)
        return removed

    def detect_suspicious_failed_logins(
        self, *, window_seconds: int = 300, threshold: int = 5
    ) -> list[str]:
        """Return organization or user identifiers with repeated failed logins."""
        now = self._now()
        failed = [
            entry
            for entry in self._entries
            if entry.category == "access"
            and entry.action == "login"
            and entry.status == "denied"
            and entry.timestamp >= now - window_seconds
        ]

        counts: dict[str, int] = {}
        for entry in failed:
            principal = entry.user_id or entry.org_id or "anonymous"
            counts[principal] = counts.get(principal, 0) + 1

        return [principal for principal, count in counts.items() if count >= threshold]

    def count(self) -> int:
        """Total number of stored audit events."""
        return len(self._entries)
