"""JWT token generation and validation using RS256 algorithm."""

import logging
import time
import uuid

import jwt

from .models import PublicKey, TokenPair, TokenPayload

logger = logging.getLogger(__name__)


class AuthProvider:
    """Handles JWT token generation and validation with RS256 algorithm."""

    def __init__(
        self,
        private_key_pem: str,
        issuer: str = "siof-enterprise",
        audience: str = "siof-api",
        access_token_expiry_seconds: int = 1800,  # 30 minutes
        refresh_token_expiry_seconds: int = 604800,  # 7 days
    ):
        """Initialize AuthProvider.

        Args:
            private_key_pem: RSA private key in PEM format for signing tokens
            issuer: JWT issuer claim
            audience: JWT audience claim
            access_token_expiry_seconds: Access token expiry time in seconds
            refresh_token_expiry_seconds: Refresh token expiry time in seconds
        """
        self.private_key_pem = private_key_pem
        self.issuer = issuer
        self.audience = audience
        self.access_token_expiry_seconds = access_token_expiry_seconds
        self.refresh_token_expiry_seconds = refresh_token_expiry_seconds

        # In-memory storage for public keys
        # Maps key_id -> PublicKey
        self._public_keys: dict[str, PublicKey] = {}
        self._current_key_id: str | None = None

    def generate_tokens(
        self, user_id: str, org_id: str, roles: list[str]
    ) -> TokenPair:
        """Generate JWT access and refresh tokens.

        Args:
            user_id: User identifier
            org_id: Organization identifier
            roles: List of user roles

        Returns:
            TokenPair containing access and refresh tokens

        Raises:
            ValueError: If no signing key is available
        """
        if not self._current_key_id:
            raise ValueError("No signing key available for token generation")

        now = int(time.time())
        jti = str(uuid.uuid4())

        # Create access token payload
        access_payload = {
            "iss": self.issuer,
            "sub": user_id,
            "aud": self.audience,
            "org_id": org_id,
            "roles": roles,
            "iat": now,
            "exp": now + self.access_token_expiry_seconds,
            "jti": jti,
            "kid": self._current_key_id,
        }

        # Generate access token
        access_token = jwt.encode(
            access_payload, self.private_key_pem, algorithm="RS256"
        )

        # Create refresh token payload with longer expiry
        refresh_jti = f"{jti}_refresh"
        refresh_payload = {
            "iss": self.issuer,
            "sub": user_id,
            "aud": self.audience,
            "org_id": org_id,
            "roles": roles,
            "iat": now,
            "exp": now + self.refresh_token_expiry_seconds,
            "jti": refresh_jti,
            "kid": self._current_key_id,
            "token_type": "refresh",
        }
        refresh_token = jwt.encode(
            refresh_payload, self.private_key_pem, algorithm="RS256"
        )

        logger.info(
            f"Generated tokens for user {user_id} in org {org_id}",
            extra={"user_id": user_id, "org_id": org_id, "jti": jti},
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_in=self.access_token_expiry_seconds,
            refresh_token_expires_in=self.refresh_token_expiry_seconds,
        )

    def verify_token(self, token: str) -> TokenPayload | None:
        """Verify JWT token signature and expiry.

        Args:
            token: JWT token string

        Returns:
            TokenPayload if valid, None if invalid or expired

        Raises:
            ValueError: If token format is invalid
        """
        try:
            # Get the key ID from token header
            unverified_header = jwt.get_unverified_header(token)
            key_id = unverified_header.get("kid")

            # If no key ID in header, try all active public keys
            if not key_id:
                # Try to verify with any active public key
                for kid, public_key in self._public_keys.items():
                    try:
                        payload_dict = jwt.decode(
                            token,
                            public_key.public_key_pem,
                            algorithms=["RS256"],
                            issuer=self.issuer,
                            audience=self.audience,
                        )
                        # Successfully decoded, use this payload
                        break
                    except jwt.InvalidTokenError:
                        continue
                else:
                    # No key worked
                    logger.warning("Token could not be verified with any registered key")
                    return None
            else:
                if key_id not in self._public_keys:
                    logger.warning(
                        f"Token signed with unknown key: {key_id}",
                        extra={"kid": key_id},
                    )
                    return None

                public_key = self._public_keys[key_id]

                # Verify and decode token
                payload_dict = jwt.decode(
                    token,
                    public_key.public_key_pem,
                    algorithms=["RS256"],
                    issuer=self.issuer,
                    audience=self.audience,
                )

            # Create TokenPayload
            token_payload = TokenPayload(
                iss=payload_dict["iss"],
                sub=payload_dict["sub"],
                aud=payload_dict["aud"],
                org_id=payload_dict["org_id"],
                roles=payload_dict["roles"],
                iat=payload_dict["iat"],
                exp=payload_dict["exp"],
                jti=payload_dict["jti"],
            )

            logger.debug(
                f"Token verified for user {token_payload.sub}",
                extra={"jti": token_payload.jti},
            )
            return token_payload

        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidSignatureError:
            logger.warning("Token signature verification failed")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Token verification error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during token verification: {e}")
            return None

    def register_public_key(self, key_id: str, public_key_pem: str) -> None:
        """Register a public key for token verification.

        Args:
            key_id: Unique identifier for the key
            public_key_pem: Public key in PEM format
        """
        now = int(time.time())
        public_key = PublicKey(
            key_id=key_id,
            public_key_pem=public_key_pem,
            created_at=now,
        )
        self._public_keys[key_id] = public_key
        self._current_key_id = key_id
        logger.info(f"Registered public key {key_id}")

    def get_public_keys(self) -> list[PublicKey]:
        """Get all registered public keys.

        Returns:
            List of PublicKey objects
        """
        return list(self._public_keys.values())

    def get_current_key_id(self) -> str | None:
        """Get the current key ID used for signing.

        Returns:
            Current key ID or None if no key is registered
        """
        return self._current_key_id
