"""Unit tests for Phase 1 Auth Infrastructure (Tasks 1.1-1.5)."""

import time
import uuid

import pytest

from siof.auth import (
    AuthProvider,
    KeyManager,
    LoginHandler,
    PasswordManager,
    TokenManager,
)


class TestKeyManager:
    """Tests for RSA key generation and management (Task 1.2)."""

    def test_generate_key_pair_valid_size(self):
        """Test generating RSA key pair with valid size."""
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair(key_size=4096)

        assert private_pem.startswith("-----BEGIN PRIVATE KEY-----")
        assert public_pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert len(private_pem) > 1000
        assert len(public_pem) > 300

    def test_generate_key_pair_invalid_size(self):
        """Test generating RSA key pair with invalid size."""
        manager = KeyManager()

        with pytest.raises(ValueError, match="at least 4096 bits"):
            manager.generate_key_pair(key_size=2048)

    def test_register_key_pair(self):
        """Test registering a key pair."""
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair()

        key_id = manager.register_key_pair(private_pem, public_pem)

        assert key_id is not None
        assert manager.get_private_key(key_id) == private_pem
        assert manager.get_public_key(key_id) == public_pem
        assert manager.get_current_key_id() == key_id

    def test_register_invalid_key_pair(self):
        """Test registering invalid key pair."""
        manager = KeyManager()

        with pytest.raises(ValueError, match="Invalid key format"):
            manager.register_key_pair("invalid_private", "invalid_public")

    def test_rotate_keys(self):
        """Test key rotation."""
        manager = KeyManager()
        private_pem1, public_pem1 = manager.generate_key_pair()
        key_id1 = manager.register_key_pair(private_pem1, public_pem1)

        # Rotate to new key
        key_id2 = manager.rotate_keys()

        assert key_id2 != key_id1
        assert manager.get_current_key_id() == key_id2

        # Old key should still be active (in grace period)
        active_keys = manager.get_active_public_keys()
        assert key_id1 in active_keys
        assert key_id2 in active_keys

    def test_cleanup_expired_keys(self):
        """Test cleanup of expired keys."""
        manager = KeyManager(key_rotation_grace_period_seconds=1)
        private_pem1, public_pem1 = manager.generate_key_pair()
        key_id1 = manager.register_key_pair(private_pem1, public_pem1)

        # Rotate key
        key_id2 = manager.rotate_keys()

        # Wait for grace period to expire
        time.sleep(1.1)

        # Cleanup expired keys
        removed_count = manager.cleanup_expired_keys()

        assert removed_count == 1
        assert key_id1 not in manager.get_active_public_keys()
        assert key_id2 in manager.get_active_public_keys()

    def test_get_key_status(self):
        """Test getting key status."""
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair()
        key_id = manager.register_key_pair(private_pem, public_pem)

        status = manager.get_key_status(key_id)

        assert status is not None
        assert status["key_id"] == key_id
        assert status["is_current"] is True
        assert status["is_active"] is True
        assert status["is_expired"] is False


class TestAuthProvider:
    """Tests for JWT token generation and validation (Task 1.1)."""

    @pytest.fixture
    def auth_provider(self):
        """Create AuthProvider with test keys."""
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair()
        key_id = manager.register_key_pair(private_pem, public_pem)

        provider = AuthProvider(private_key_pem=private_pem)
        provider.register_public_key(key_id, public_pem)
        return provider

    def test_generate_tokens(self, auth_provider):
        """Test generating access and refresh tokens."""
        tokens = auth_provider.generate_tokens(
            user_id="user123",
            org_id="org456",
            roles=["analyst", "admin"],
        )

        assert tokens.access_token is not None
        assert tokens.refresh_token is not None
        assert tokens.access_token_expires_in == 1800
        assert tokens.refresh_token_expires_in == 604800
        assert tokens.token_type == "Bearer"

    def test_verify_valid_token(self, auth_provider):
        """Test verifying a valid token."""
        tokens = auth_provider.generate_tokens(
            user_id="user123",
            org_id="org456",
            roles=["analyst"],
        )

        payload = auth_provider.verify_token(tokens.access_token)

        assert payload is not None
        assert payload.sub == "user123"
        assert payload.org_id == "org456"
        assert payload.roles == ["analyst"]
        assert payload.iss == "siof-enterprise"
        assert payload.aud == "siof-api"

    def test_verify_expired_token(self, auth_provider):
        """Test verifying an expired token."""
        # Create provider with very short expiry
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair()
        key_id = manager.register_key_pair(private_pem, public_pem)

        provider = AuthProvider(
            private_key_pem=private_pem,
            access_token_expiry_seconds=1,
        )
        provider.register_public_key(key_id, public_pem)

        tokens = provider.generate_tokens(
            user_id="user123",
            org_id="org456",
            roles=["analyst"],
        )

        # Wait for token to expire
        time.sleep(1.1)

        payload = provider.verify_token(tokens.access_token)
        assert payload is None

    def test_verify_invalid_signature(self, auth_provider):
        """Test verifying token with invalid signature."""
        tokens = auth_provider.generate_tokens(
            user_id="user123",
            org_id="org456",
            roles=["analyst"],
        )

        # Tamper with token
        tampered_token = tokens.access_token[:-10] + "0000000000"

        payload = auth_provider.verify_token(tampered_token)
        assert payload is None

    def test_verify_token_with_wrong_issuer(self):
        """Test verifying token with wrong issuer."""
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair()
        key_id = manager.register_key_pair(private_pem, public_pem)

        provider1 = AuthProvider(private_key_pem=private_pem, issuer="issuer1")
        provider1.register_public_key(key_id, public_pem)

        tokens = provider1.generate_tokens(
            user_id="user123",
            org_id="org456",
            roles=["analyst"],
        )

        # Try to verify with different issuer
        provider2 = AuthProvider(private_key_pem=private_pem, issuer="issuer2")
        provider2.register_public_key(key_id, public_pem)

        payload = provider2.verify_token(tokens.access_token)
        assert payload is None

    def test_register_public_key(self, auth_provider):
        """Test registering public keys."""
        manager = KeyManager()
        private_pem, public_pem = manager.generate_key_pair()

        auth_provider.register_public_key("key2", public_pem)

        public_keys = auth_provider.get_public_keys()
        assert len(public_keys) >= 2

    def test_get_public_keys(self, auth_provider):
        """Test getting all public keys."""
        public_keys = auth_provider.get_public_keys()

        assert len(public_keys) > 0
        assert all(
            key.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----") for key in public_keys
        )


class TestTokenManager:
    """Tests for token refresh mechanism (Task 1.3)."""

    def test_store_and_validate_refresh_token(self):
        """Test storing and validating refresh token."""
        manager = TokenManager()
        jti = str(uuid.uuid4())
        expires_at = int(time.time()) + 3600

        manager.store_refresh_token(jti, "user123", "org456", expires_at)

        token_data = manager.validate_refresh_token(jti)
        assert token_data is not None
        assert token_data["user_id"] == "user123"
        assert token_data["org_id"] == "org456"
        assert token_data["used"] is False

    def test_single_use_constraint(self):
        """Test single-use constraint on refresh tokens."""
        manager = TokenManager()
        jti = str(uuid.uuid4())
        expires_at = int(time.time()) + 3600

        manager.store_refresh_token(jti, "user123", "org456", expires_at)

        # First use should succeed
        token_data = manager.validate_refresh_token(jti)
        assert token_data is not None

        # Mark as used
        manager.mark_token_used(jti)

        # Second use should fail
        token_data = manager.validate_refresh_token(jti)
        assert token_data is None

    def test_expired_refresh_token(self):
        """Test validation of expired refresh token."""
        manager = TokenManager()
        jti = str(uuid.uuid4())
        expires_at = int(time.time()) - 1  # Already expired

        manager.store_refresh_token(jti, "user123", "org456", expires_at)

        token_data = manager.validate_refresh_token(jti)
        assert token_data is None

    def test_revoke_user_tokens(self):
        """Test revoking all tokens for a user."""
        manager = TokenManager()

        # Store multiple tokens for same user
        for i in range(3):
            jti = str(uuid.uuid4())
            expires_at = int(time.time()) + 3600
            manager.store_refresh_token(jti, "user123", "org456", expires_at)

        # Revoke all tokens
        revoked_count = manager.revoke_user_tokens("user123")
        assert revoked_count == 3

    def test_cleanup_expired_tokens(self):
        """Test cleanup of expired tokens."""
        manager = TokenManager()

        # Store expired token
        jti1 = str(uuid.uuid4())
        manager.store_refresh_token(jti1, "user123", "org456", int(time.time()) - 1)

        # Store valid token
        jti2 = str(uuid.uuid4())
        manager.store_refresh_token(jti2, "user123", "org456", int(time.time()) + 3600)

        # Cleanup
        removed_count = manager.cleanup_expired_tokens()
        assert removed_count == 1

        # Valid token should still exist
        token_data = manager.validate_refresh_token(jti2)
        assert token_data is not None

    def test_get_token_status(self):
        """Test getting token status."""
        manager = TokenManager()
        jti = str(uuid.uuid4())
        expires_at = int(time.time()) + 3600

        manager.store_refresh_token(jti, "user123", "org456", expires_at)

        status = manager.get_token_status(jti)
        assert status is not None
        assert status["jti"] == jti
        assert status["user_id"] == "user123"
        assert status["used"] is False
        assert status["is_expired"] is False


class TestPasswordManager:
    """Tests for password hashing and validation (Task 1.4)."""

    def test_validate_password_valid(self):
        """Test validating a valid password."""
        manager = PasswordManager()
        password = "SecurePass123!@#"

        is_valid, error = manager.validate_password(password)
        assert is_valid is True
        assert error is None

    def test_validate_password_too_short(self):
        """Test validating password that's too short."""
        manager = PasswordManager(min_length=12)
        password = "Short1!@"

        is_valid, error = manager.validate_password(password)
        assert is_valid is False
        assert "at least 12 characters" in error

    def test_validate_password_missing_uppercase(self):
        """Test validating password missing uppercase."""
        manager = PasswordManager(require_uppercase=True)
        password = "securepass123!@#"

        is_valid, error = manager.validate_password(password)
        assert is_valid is False
        assert "uppercase" in error

    def test_validate_password_missing_lowercase(self):
        """Test validating password missing lowercase."""
        manager = PasswordManager(require_lowercase=True)
        password = "SECUREPASS123!@#"

        is_valid, error = manager.validate_password(password)
        assert is_valid is False
        assert "lowercase" in error

    def test_validate_password_missing_numbers(self):
        """Test validating password missing numbers."""
        manager = PasswordManager(require_numbers=True)
        password = "SecurePass!@#"

        is_valid, error = manager.validate_password(password)
        assert is_valid is False
        assert "number" in error

    def test_validate_password_missing_special(self):
        """Test validating password missing special characters."""
        manager = PasswordManager(require_special=True)
        password = "SecurePass123"

        is_valid, error = manager.validate_password(password)
        assert is_valid is False
        assert "special character" in error

    def test_hash_password(self):
        """Test hashing a password."""
        manager = PasswordManager()
        password = "SecurePass123!@#"

        hashed = manager.hash_password(password)

        assert hashed != password
        assert hashed.startswith("$2b$")  # bcrypt format

    def test_hash_invalid_password(self):
        """Test hashing an invalid password."""
        manager = PasswordManager()
        password = "weak"

        with pytest.raises(ValueError):
            manager.hash_password(password)

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        manager = PasswordManager()
        password = "SecurePass123!@#"

        hashed = manager.hash_password(password)
        is_correct = manager.verify_password(password, hashed)

        assert is_correct is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        manager = PasswordManager()
        password = "SecurePass123!@#"
        wrong_password = "WrongPass123!@#"

        hashed = manager.hash_password(password)
        is_correct = manager.verify_password(wrong_password, hashed)

        assert is_correct is False

    def test_get_requirements(self):
        """Test getting password requirements."""
        manager = PasswordManager(
            min_length=16,
            require_uppercase=True,
            require_lowercase=True,
            require_numbers=True,
            require_special=True,
        )

        requirements = manager.get_requirements()

        assert requirements["min_length"] == 16
        assert requirements["require_uppercase"] is True
        assert requirements["require_lowercase"] is True
        assert requirements["require_numbers"] is True
        assert requirements["require_special"] is True


class TestLoginHandler:
    """Tests for login endpoint (Task 1.5)."""

    def test_successful_login(self):
        """Test successful login."""
        handler = LoginHandler()

        is_locked, error = handler.check_account_lockout("user123")
        assert is_locked is False
        assert error is None

        handler.record_successful_login("user123")

        status = handler.get_attempt_status("user123")
        assert status["failed_attempts"] == 0
        assert status["is_locked"] is False

    def test_failed_login_attempts(self):
        """Test failed login attempts."""
        handler = LoginHandler(max_failed_attempts=3)

        # First two attempts
        for i in range(2):
            is_now_locked, error = handler.record_failed_attempt("user123")
            assert is_now_locked is False

        # Third attempt should lock account
        is_now_locked, error = handler.record_failed_attempt("user123")
        assert is_now_locked is True
        assert "locked" in error.lower()

    def test_account_lockout(self):
        """Test account lockout after max attempts."""
        handler = LoginHandler(max_failed_attempts=2, lockout_duration_seconds=1)

        # Trigger lockout
        handler.record_failed_attempt("user123")
        handler.record_failed_attempt("user123")

        # Check lockout
        is_locked, error = handler.check_account_lockout("user123")
        assert is_locked is True
        assert error is not None

    def test_lockout_expiry(self):
        """Test lockout expiry."""
        handler = LoginHandler(max_failed_attempts=1, lockout_duration_seconds=1)

        # Trigger lockout
        handler.record_failed_attempt("user123")

        # Check locked
        is_locked, error = handler.check_account_lockout("user123")
        assert is_locked is True

        # Wait for lockout to expire
        time.sleep(1.1)

        # Check unlocked
        is_locked, error = handler.check_account_lockout("user123")
        assert is_locked is False

    def test_reset_attempts(self):
        """Test resetting login attempts."""
        handler = LoginHandler()

        # Record failed attempts
        handler.record_failed_attempt("user123")
        handler.record_failed_attempt("user123")

        # Reset
        handler.reset_attempts("user123")

        status = handler.get_attempt_status("user123")
        assert status["failed_attempts"] == 0
        assert status["is_locked"] is False

    def test_get_attempt_status(self):
        """Test getting attempt status."""
        handler = LoginHandler()

        status = handler.get_attempt_status("user123")
        assert status["user_id"] == "user123"
        assert status["failed_attempts"] == 0
        assert status["is_locked"] is False
