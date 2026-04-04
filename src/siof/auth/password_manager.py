"""Password hashing and validation with security requirements."""

import logging
import re

import bcrypt

logger = logging.getLogger(__name__)


class PasswordManager:
    """Manages password hashing and validation."""

    def __init__(
        self,
        min_length: int = 12,
        require_uppercase: bool = True,
        require_lowercase: bool = True,
        require_numbers: bool = True,
        require_special: bool = True,
        bcrypt_cost: int = 12,
    ):
        """Initialize PasswordManager.

        Args:
            min_length: Minimum password length
            require_uppercase: Require uppercase letters
            require_lowercase: Require lowercase letters
            require_numbers: Require numbers
            require_special: Require special characters
            bcrypt_cost: Bcrypt cost factor (higher = slower but more secure)
        """
        self.min_length = min_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_numbers = require_numbers
        self.require_special = require_special
        self.bcrypt_cost = bcrypt_cost

    def validate_password(self, password: str) -> tuple[bool, str | None]:
        """Validate password against requirements.

        Args:
            password: Password to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(password) < self.min_length:
            return False, f"Password must be at least {self.min_length} characters long"

        if self.require_uppercase and not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"

        if self.require_lowercase and not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"

        if self.require_numbers and not re.search(r"\d", password):
            return False, "Password must contain at least one number"

        if self.require_special and not re.search(r"[!@#$%^&*()_+\-=\[\]{};:'\",.<>?/\\|`~]", password):
            return False, "Password must contain at least one special character"

        return True, None

    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt.

        Args:
            password: Password to hash

        Returns:
            Hashed password

        Raises:
            ValueError: If password is invalid
        """
        is_valid, error_message = self.validate_password(password)
        if not is_valid:
            raise ValueError(error_message)

        # Generate salt and hash
        salt = bcrypt.gensalt(rounds=self.bcrypt_cost)
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)

        logger.debug("Password hashed successfully")
        return hashed.decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash.

        Args:
            password: Password to verify
            password_hash: Hashed password to compare against

        Returns:
            True if password matches, False otherwise
        """
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception as e:
            logger.error(f"Error verifying password: {e}")
            return False

    def get_requirements(self) -> dict:
        """Get password requirements.

        Returns:
            Dictionary describing password requirements
        """
        requirements = {
            "min_length": self.min_length,
            "require_uppercase": self.require_uppercase,
            "require_lowercase": self.require_lowercase,
            "require_numbers": self.require_numbers,
            "require_special": self.require_special,
        }
        return requirements
