"""RSA key generation, storage, and rotation for JWT signing."""

import logging
import time
import uuid
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)


class KeyManager:
    """Manages RSA key pairs for JWT signing with rotation support."""

    def __init__(
        self,
        key_rotation_grace_period_seconds: int = 604800,  # 7 days
    ):
        """Initialize KeyManager.

        Args:
            key_rotation_grace_period_seconds: Grace period for key rotation in seconds
        """
        self.key_rotation_grace_period_seconds = key_rotation_grace_period_seconds

        # Storage for active keys
        # Maps key_id -> {"private_key_pem": str, "public_key_pem": str, "created_at": int, "expires_at": Optional[int]}
        self._keys: dict[str, dict] = {}
        self._current_key_id: Optional[str] = None

    def generate_key_pair(self, key_size: int = 4096) -> tuple[str, str]:
        """Generate RSA key pair.

        Args:
            key_size: RSA key size in bits (minimum 4096)

        Returns:
            Tuple of (private_key_pem, public_key_pem)

        Raises:
            ValueError: If key_size is less than 4096
        """
        if key_size < 4096:
            raise ValueError("RSA key size must be at least 4096 bits")

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )

        # Serialize private key to PEM
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        # Serialize public key to PEM
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        logger.info(f"Generated RSA key pair with {key_size}-bit key")
        return private_pem, public_pem

    def register_key_pair(
        self, private_key_pem: str, public_key_pem: str
    ) -> str:
        """Register a key pair for use in token signing.

        Args:
            private_key_pem: Private key in PEM format
            public_key_pem: Public key in PEM format

        Returns:
            Key ID for the registered key pair

        Raises:
            ValueError: If keys are invalid
        """
        # Validate keys by attempting to load them
        try:
            from cryptography.hazmat.backends import default_backend

            serialization.load_pem_private_key(
                private_key_pem.encode(), password=None, backend=default_backend()
            )
            serialization.load_pem_public_key(
                public_key_pem.encode(), backend=default_backend()
            )
        except Exception as e:
            raise ValueError(f"Invalid key format: {e}")

        key_id = str(uuid.uuid4())
        now = int(time.time())

        self._keys[key_id] = {
            "private_key_pem": private_key_pem,
            "public_key_pem": public_key_pem,
            "created_at": now,
            "expires_at": None,
        }

        # Set as current key if this is the first key
        if self._current_key_id is None:
            self._current_key_id = key_id

        logger.info(f"Registered key pair with ID {key_id}")
        return key_id

    def rotate_keys(self) -> str:
        """Rotate to a new key pair.

        The old key enters a grace period where both old and new keys are accepted.
        After the grace period, the old key is rejected.

        Returns:
            New key ID

        Raises:
            ValueError: If key generation fails
        """
        # Generate new key pair
        private_pem, public_pem = self.generate_key_pair()

        # Register new key
        new_key_id = self.register_key_pair(private_pem, public_pem)

        # Mark old key with expiry (grace period)
        if self._current_key_id:
            old_key = self._keys[self._current_key_id]
            old_key["expires_at"] = int(time.time()) + self.key_rotation_grace_period_seconds
            logger.info(
                f"Marked key {self._current_key_id} for rotation with grace period",
                extra={
                    "old_key_id": self._current_key_id,
                    "new_key_id": new_key_id,
                    "grace_period_seconds": self.key_rotation_grace_period_seconds,
                },
            )

        # Set new key as current
        self._current_key_id = new_key_id

        logger.info(
            f"Rotated keys: new key ID {new_key_id}",
            extra={"new_key_id": new_key_id},
        )
        return new_key_id

    def get_private_key(self, key_id: Optional[str] = None) -> Optional[str]:
        """Get private key for signing.

        Args:
            key_id: Key ID to retrieve (uses current key if not specified)

        Returns:
            Private key in PEM format or None if key not found
        """
        if key_id is None:
            key_id = self._current_key_id

        if key_id is None or key_id not in self._keys:
            return None

        return self._keys[key_id]["private_key_pem"]

    def get_public_key(self, key_id: str) -> Optional[str]:
        """Get public key for verification.

        Args:
            key_id: Key ID to retrieve

        Returns:
            Public key in PEM format or None if key not found
        """
        if key_id not in self._keys:
            return None

        return self._keys[key_id]["public_key_pem"]

    def get_active_public_keys(self) -> dict[str, str]:
        """Get all active public keys (including those in grace period).

        Returns:
            Dictionary mapping key_id -> public_key_pem
        """
        now = int(time.time())
        active_keys = {}

        for key_id, key_data in self._keys.items():
            # Include keys that haven't expired yet
            if key_data["expires_at"] is None or key_data["expires_at"] > now:
                active_keys[key_id] = key_data["public_key_pem"]

        return active_keys

    def get_current_key_id(self) -> Optional[str]:
        """Get the current key ID used for signing.

        Returns:
            Current key ID or None if no key is registered
        """
        return self._current_key_id

    def cleanup_expired_keys(self) -> int:
        """Remove expired keys from storage.

        Returns:
            Number of keys removed
        """
        now = int(time.time())
        expired_keys = [
            key_id
            for key_id, key_data in self._keys.items()
            if key_data["expires_at"] is not None and key_data["expires_at"] <= now
        ]

        for key_id in expired_keys:
            del self._keys[key_id]
            logger.info(f"Removed expired key {key_id}")

        return len(expired_keys)

    def get_key_status(self, key_id: str) -> Optional[dict]:
        """Get status of a key.

        Args:
            key_id: Key ID to check

        Returns:
            Dictionary with key status or None if key not found
        """
        if key_id not in self._keys:
            return None

        key_data = self._keys[key_id]
        now = int(time.time())

        status = {
            "key_id": key_id,
            "created_at": key_data["created_at"],
            "expires_at": key_data["expires_at"],
            "is_current": key_id == self._current_key_id,
            "is_active": key_data["expires_at"] is None or key_data["expires_at"] > now,
            "is_expired": key_data["expires_at"] is not None and key_data["expires_at"] <= now,
        }

        return status
