"""Token bucket rate limiting for organizations and users."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BucketState:
    """Mutable token bucket state."""

    tokens: float
    last_refill_ts: float
    capacity: float
    refill_rate: float


@dataclass(slots=True)
class RateLimitDecision:
    """Result of a rate-limit check."""

    allowed: bool
    retry_after_seconds: int
    remaining_tokens: float
    capacity: float


class RateLimiter:
    """Redis-compatible token bucket limiter with role-aware user limits."""

    DEFAULT_ROLE_MULTIPLIERS = {
        "viewer": 0.5,
        "analyst": 1.0,
        "admin": 2.0,
        "service": 5.0,
    }

    def __init__(
        self,
        *,
        org_limit_per_minute: int = 1000,
        user_limit_per_minute: int = 100,
        burst_allowance: float = 0.2,
        window_seconds: int = 60,
        role_multipliers: dict[str, float] | None = None,
        audit_logger: Any | None = None,
    ):
        self.org_limit_per_minute = org_limit_per_minute
        self.user_limit_per_minute = user_limit_per_minute
        self.burst_allowance = burst_allowance
        self.window_seconds = max(1, window_seconds)
        self.role_multipliers = dict(self.DEFAULT_ROLE_MULTIPLIERS)
        if role_multipliers:
            self.role_multipliers.update(role_multipliers)

        self.audit_logger = audit_logger

        self._org_limits: dict[str, tuple[int, float]] = {}
        self._user_limits: dict[str, tuple[int, float]] = {}
        self._buckets: dict[str, BucketState] = {}
        self._violation_history: dict[str, list[int]] = {}

    def _bucket_key(self, scope: str, identifier: str) -> str:
        return f"{scope}:{identifier}"

    def _effective_config(
        self, scope: str, identifier: str, role: str | None = None
    ) -> tuple[int, float]:
        if scope == "org":
            base_limit, base_burst = self._org_limits.get(
                identifier,
                (self.org_limit_per_minute, self.burst_allowance),
            )
            return max(1, base_limit), max(0.0, base_burst)

        if scope == "user":
            base_limit, base_burst = self._user_limits.get(
                identifier,
                (self.user_limit_per_minute, self.burst_allowance),
            )
            multiplier = self.role_multipliers.get(role or "analyst", 1.0)
            return max(1, int(base_limit * multiplier)), max(0.0, base_burst)

        raise ValueError("scope must be 'org' or 'user'")

    def _build_state(
        self, limit_per_minute: int, burst_allowance: float, now: float
    ) -> BucketState:
        capacity = float(limit_per_minute) * (1.0 + burst_allowance)
        refill_rate = float(limit_per_minute) / float(self.window_seconds)
        return BucketState(
            tokens=capacity,
            last_refill_ts=now,
            capacity=capacity,
            refill_rate=refill_rate,
        )

    def _consume(self, key: str, limit: int, burst_allowance: float) -> RateLimitDecision:
        now = time.time()
        state = self._buckets.get(key)
        if state is None:
            state = self._build_state(limit, burst_allowance, now)
            self._buckets[key] = state

        elapsed = max(0.0, now - state.last_refill_ts)
        if elapsed > 0:
            state.tokens = min(state.capacity, state.tokens + (elapsed * state.refill_rate))
            state.last_refill_ts = now

        if state.tokens >= 1.0:
            state.tokens -= 1.0
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                remaining_tokens=state.tokens,
                capacity=state.capacity,
            )

        missing_tokens = 1.0 - state.tokens
        retry_after = math.ceil(missing_tokens / max(state.refill_rate, 0.00001))
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=max(1, retry_after),
            remaining_tokens=state.tokens,
            capacity=state.capacity,
        )

    def _record_violation(self, key: str) -> None:
        now = int(time.time())
        history = self._violation_history.setdefault(key, [])
        history.append(now)

    def get_repeated_violators(self, *, window_seconds: int = 300, threshold: int = 5) -> list[str]:
        """Return bucket keys with repeated violations in a time window."""
        now = int(time.time())
        violators: list[str] = []
        for key, timestamps in self._violation_history.items():
            recent = [ts for ts in timestamps if ts >= now - window_seconds]
            self._violation_history[key] = recent
            if len(recent) >= threshold:
                violators.append(key)
        return violators

    def set_org_limit(
        self, org_id: str, *, requests_per_minute: int, burst_allowance: float | None = None
    ) -> None:
        self._org_limits[org_id] = (
            max(1, requests_per_minute),
            self.burst_allowance if burst_allowance is None else max(0.0, burst_allowance),
        )

    def set_user_limit(
        self,
        user_id: str,
        *,
        requests_per_minute: int,
        burst_allowance: float | None = None,
    ) -> None:
        self._user_limits[user_id] = (
            max(1, requests_per_minute),
            self.burst_allowance if burst_allowance is None else max(0.0, burst_allowance),
        )

    def reset_bucket(self, *, scope: str, identifier: str) -> None:
        self._buckets.pop(self._bucket_key(scope, identifier), None)

    def get_status(self, *, scope: str, identifier: str, role: str | None = None) -> dict[str, Any]:
        limit, burst = self._effective_config(scope, identifier, role=role)
        key = self._bucket_key(scope, identifier)
        state = self._buckets.get(key)
        if state is None:
            state = self._build_state(limit, burst, time.time())
            self._buckets[key] = state

        return {
            "scope": scope,
            "identifier": identifier,
            "limit_per_minute": limit,
            "burst_allowance": burst,
            "remaining_tokens": state.tokens,
            "capacity": state.capacity,
        }

    def check_org_limit(self, org_id: str) -> RateLimitDecision:
        limit, burst = self._effective_config("org", org_id)
        key = self._bucket_key("org", org_id)
        result = self._consume(key, limit, burst)
        if not result.allowed:
            self._record_violation(key)
            logger.warning("Organization rate limit exceeded for %s", org_id)
            if self.audit_logger:
                self.audit_logger.log_event(
                    category="rate_limit",
                    action="org_limit_exceeded",
                    resource_type="organization",
                    resource_id=org_id,
                    org_id=org_id,
                    status="denied",
                    details={"retry_after": result.retry_after_seconds},
                )
        return result

    def check_user_limit(
        self, user_id: str, *, role: str = "analyst", org_id: str | None = None
    ) -> RateLimitDecision:
        limit, burst = self._effective_config("user", user_id, role=role)
        key = self._bucket_key("user", user_id)
        result = self._consume(key, limit, burst)
        if not result.allowed:
            self._record_violation(key)
            logger.warning("User rate limit exceeded for %s", user_id)
            if self.audit_logger:
                self.audit_logger.log_event(
                    category="rate_limit",
                    action="user_limit_exceeded",
                    resource_type="user",
                    resource_id=user_id,
                    user_id=user_id,
                    org_id=org_id,
                    status="denied",
                    details={"retry_after": result.retry_after_seconds, "role": role},
                )
        return result

    def check_combined_limit(self, *, org_id: str, user_id: str, role: str) -> dict[str, Any]:
        """Check both org and user limits and return the most restrictive decision."""
        org_decision = self.check_org_limit(org_id)
        user_decision = self.check_user_limit(user_id, role=role, org_id=org_id)

        allowed = org_decision.allowed and user_decision.allowed
        retry_after = max(org_decision.retry_after_seconds, user_decision.retry_after_seconds)

        return {
            "allowed": allowed,
            "retry_after_seconds": retry_after,
            "organization": asdict(org_decision),
            "user": asdict(user_decision),
        }
