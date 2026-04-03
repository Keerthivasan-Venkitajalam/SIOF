from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PolicyContext:
    """Authorization context for policy decisions."""

    role: str = "reader"
    approval_token: str | None = None
    org: str = "default"
    user_id: str | None = None


class PolicyEngine:
    """RBAC policy engine for tool authorization and rate limiting."""

    # Role hierarchy: lower index = fewer permissions
    ROLE_HIERARCHY: ClassVar[list[str]] = ["viewer", "analyst", "admin", "service"]

    # Tool permissions by role
    TOOL_PERMISSIONS: ClassVar[dict[str, set[str]]] = {
        "viewer": {
            "find_data_lineage",
            "get_intent_history",
        },
        "analyst": {
            "find_data_lineage",
            "impact_of_change",
            "validate_relationship",
            "get_dead_paths",
            "find_unhandled_exceptions",
            "get_intent_history",
            "get_run_energy",
        },
        "admin": {
            "find_data_lineage",
            "impact_of_change",
            "validate_relationship",
            "get_dead_paths",
            "find_unhandled_exceptions",
            "get_intent_history",
            "get_run_energy",
            "apply_patch_to_file",
        },
        "service": {
            "find_data_lineage",
            "impact_of_change",
            "validate_relationship",
            "get_dead_paths",
            "find_unhandled_exceptions",
            "get_intent_history",
            "get_run_energy",
        },
    }

    # Mutation tools requiring approval token
    MUTATING_TOOLS: ClassVar[set[str]] = {"apply_patch_to_file"}

    # Rate limits per role (requests per hour)
    RATE_LIMITS: ClassVar[dict[str, int]] = {
        "viewer": 100,
        "analyst": 1000,
        "admin": 10000,
        "service": 5000,
    }

    def __init__(self):
        """Initialize policy engine."""
        self.request_counts: dict[str, int] = {}
        logger.info("Policy engine initialized")

    def authorize(self, tool_name: str, ctx: PolicyContext) -> bool:
        """Check if tool access is authorized.

        Args:
            tool_name: Name of the tool to authorize
            ctx: Policy context with role and approval token

        Returns:
            True if authorized, False otherwise
        """
        # Validate role
        if ctx.role not in self.ROLE_HIERARCHY:
            logger.warning(f"Invalid role: {ctx.role}")
            return False

        # Check tool permission
        allowed_tools = self.TOOL_PERMISSIONS.get(ctx.role, set())
        if tool_name not in allowed_tools:
            logger.warning(f"Tool {tool_name} not allowed for role {ctx.role}")
            return False

        # Require approval token for mutations
        if tool_name in self.MUTATING_TOOLS:
            if not ctx.approval_token:
                logger.warning(f"Mutation tool {tool_name} requires approval token")
                return False

        logger.debug(f"Authorized {ctx.role} for tool {tool_name}")
        return True

    def check_rate_limit(self, ctx: PolicyContext) -> bool:
        """Check if request is within rate limit.

        Args:
            ctx: Policy context with role

        Returns:
            True if within limit, False otherwise
        """
        key = f"{ctx.org}:{ctx.role}"
        current = self.request_counts.get(key, 0)
        limit = self.RATE_LIMITS.get(ctx.role, 100)

        if current >= limit:
            logger.warning(f"Rate limit exceeded for {key}: {current}/{limit}")
            return False

        self.request_counts[key] = current + 1
        return True

    def reset_rate_limits(self) -> None:
        """Reset all rate limit counters."""
        self.request_counts.clear()
        logger.info("Rate limits reset")
