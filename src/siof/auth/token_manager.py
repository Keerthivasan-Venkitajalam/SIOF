"""Token refresh mechanism with single-use enforcement."""

import logging
import time

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages token refresh with single-use enforcement."""

    def __init__(self):
        """Initialize TokenManager."""
        # Storage for refresh tokens
        # Maps token_jti -> {"user_id": str, "org_id": str, "used": bool, "used_at": Optional[int], "created_at": int, "expires_at": int}
        self._refresh_tokens: dict[str, dict] = {}

    def store_refresh_token(
        self, jti: str, user_id: str, org_id: str, expires_at: int
    ) -> None:
        """Store a refresh token.

        Args:
            jti: JWT ID (unique token identifier)
            user_id: User identifier
            org_id: Organization identifier
            expires_at: Token expiry timestamp (unix)
        """
        now = int(time.time())
        self._refresh_tokens[jti] = {
            "user_id": user_id,
            "org_id": org_id,
            "used": False,
            "used_at": None,
            "created_at": now,
            "expires_at": expires_at,
        }
        logger.debug(f"Stored refresh token {jti} for user {user_id}")

    def validate_refresh_token(self, jti: str) -> dict | None:
        """Validate a refresh token.

        Args:
            jti: JWT ID to validate

        Returns:
            Token data if valid, None if invalid, expired, or already used
        """
        if jti not in self._refresh_tokens:
            logger.warning(f"Refresh token not found: {jti}")
            return None

        token_data = self._refresh_tokens[jti]
        now = int(time.time())

        # Check if expired
        if token_data["expires_at"] < now:
            logger.warning(f"Refresh token expired: {jti}")
            return None

        # Check if already used (single-use constraint)
        if token_data["used"]:
            logger.warning(f"Refresh token already used: {jti}")
            return None

        return token_data

    def mark_token_used(self, jti: str) -> bool:
        """Mark a refresh token as used.

        Args:
            jti: JWT ID to mark as used

        Returns:
            True if successfully marked, False if token not found or already used
        """
        if jti not in self._refresh_tokens:
            logger.warning(f"Refresh token not found: {jti}")
            return False

        token_data = self._refresh_tokens[jti]

        if token_data["used"]:
            logger.warning(f"Refresh token already marked as used: {jti}")
            return False

        token_data["used"] = True
        token_data["used_at"] = int(time.time())
        logger.info(f"Marked refresh token as used: {jti}")
        return True

    def revoke_user_tokens(self, user_id: str) -> int:
        """Revoke all refresh tokens for a user.

        Args:
            user_id: User identifier

        Returns:
            Number of tokens revoked
        """
        tokens_to_revoke = [
            jti
            for jti, token_data in self._refresh_tokens.items()
            if token_data["user_id"] == user_id
        ]

        for jti in tokens_to_revoke:
            del self._refresh_tokens[jti]

        logger.info(f"Revoked {len(tokens_to_revoke)} refresh tokens for user {user_id}")
        return len(tokens_to_revoke)

    def cleanup_expired_tokens(self) -> int:
        """Remove expired tokens from storage.

        Returns:
            Number of tokens removed
        """
        now = int(time.time())
        expired_tokens = [
            jti
            for jti, token_data in self._refresh_tokens.items()
            if token_data["expires_at"] < now
        ]

        for jti in expired_tokens:
            del self._refresh_tokens[jti]

        logger.debug(f"Cleaned up {len(expired_tokens)} expired refresh tokens")
        return len(expired_tokens)

    def get_token_status(self, jti: str) -> dict | None:
        """Get status of a refresh token.

        Args:
            jti: JWT ID to check

        Returns:
            Token status or None if not found
        """
        if jti not in self._refresh_tokens:
            return None

        token_data = self._refresh_tokens[jti]
        now = int(time.time())

        return {
            "jti": jti,
            "user_id": token_data["user_id"],
            "org_id": token_data["org_id"],
            "used": token_data["used"],
            "used_at": token_data["used_at"],
            "created_at": token_data["created_at"],
            "expires_at": token_data["expires_at"],
            "is_expired": token_data["expires_at"] < now,
        }
