"""Login endpoint handler with account lockout and session management."""

import logging
import time

logger = logging.getLogger(__name__)


class LoginHandler:
    """Handles user login with account lockout and session management."""

    def __init__(
        self,
        max_failed_attempts: int = 5,
        lockout_duration_seconds: int = 900,  # 15 minutes
    ):
        """Initialize LoginHandler.

        Args:
            max_failed_attempts: Maximum failed login attempts before lockout
            lockout_duration_seconds: Duration of account lockout in seconds
        """
        self.max_failed_attempts = max_failed_attempts
        self.lockout_duration_seconds = lockout_duration_seconds

        # Storage for login attempts
        # Maps user_id -> {"failed_attempts": int, "locked_until": Optional[int]}
        self._login_attempts: dict[str, dict] = {}

    def check_account_lockout(self, user_id: str) -> tuple[bool, str | None]:
        """Check if account is locked.

        Args:
            user_id: User identifier

        Returns:
            Tuple of (is_locked, error_message)
        """
        if user_id not in self._login_attempts:
            return False, None

        attempt_data = self._login_attempts[user_id]
        now = int(time.time())

        # Check if account is locked
        if attempt_data.get("locked_until") and attempt_data["locked_until"] > now:
            remaining_seconds = attempt_data["locked_until"] - now
            error_msg = f"Account is locked. Try again in {remaining_seconds} seconds."
            logger.warning(f"Login attempt on locked account: {user_id}")
            return True, error_msg

        # Clear lockout if expired
        if attempt_data.get("locked_until") and attempt_data["locked_until"] <= now:
            attempt_data["locked_until"] = None
            attempt_data["failed_attempts"] = 0

        return False, None

    def record_failed_attempt(self, user_id: str) -> tuple[bool, str | None]:
        """Record a failed login attempt.

        Args:
            user_id: User identifier

        Returns:
            Tuple of (is_now_locked, error_message)
        """
        if user_id not in self._login_attempts:
            self._login_attempts[user_id] = {
                "failed_attempts": 0,
                "locked_until": None,
            }

        attempt_data = self._login_attempts[user_id]
        attempt_data["failed_attempts"] += 1

        logger.warning(
            f"Failed login attempt for user {user_id}",
            extra={
                "user_id": user_id,
                "failed_attempts": attempt_data["failed_attempts"],
            },
        )

        # Lock account if max attempts exceeded
        if attempt_data["failed_attempts"] >= self.max_failed_attempts:
            attempt_data["locked_until"] = int(time.time()) + self.lockout_duration_seconds
            logger.warning(
                f"Account locked due to failed login attempts: {user_id}",
                extra={
                    "user_id": user_id,
                    "failed_attempts": attempt_data["failed_attempts"],
                    "locked_until": attempt_data["locked_until"],
                },
            )
            return True, "Account locked due to too many failed login attempts"

        return False, None

    def record_successful_login(self, user_id: str) -> None:
        """Record a successful login.

        Args:
            user_id: User identifier
        """
        if user_id in self._login_attempts:
            self._login_attempts[user_id]["failed_attempts"] = 0
            self._login_attempts[user_id]["locked_until"] = None

        logger.info(f"Successful login for user {user_id}")

    def get_attempt_status(self, user_id: str) -> dict:
        """Get login attempt status for a user.

        Args:
            user_id: User identifier

        Returns:
            Dictionary with attempt status
        """
        if user_id not in self._login_attempts:
            return {
                "user_id": user_id,
                "failed_attempts": 0,
                "is_locked": False,
                "locked_until": None,
            }

        attempt_data = self._login_attempts[user_id]
        now = int(time.time())
        is_locked = (
            attempt_data.get("locked_until") is not None and attempt_data["locked_until"] > now
        )

        return {
            "user_id": user_id,
            "failed_attempts": attempt_data["failed_attempts"],
            "is_locked": is_locked,
            "locked_until": attempt_data.get("locked_until"),
        }

    def reset_attempts(self, user_id: str) -> None:
        """Reset login attempts for a user (admin action).

        Args:
            user_id: User identifier
        """
        if user_id in self._login_attempts:
            self._login_attempts[user_id]["failed_attempts"] = 0
            self._login_attempts[user_id]["locked_until"] = None
            logger.info(f"Reset login attempts for user {user_id}")
