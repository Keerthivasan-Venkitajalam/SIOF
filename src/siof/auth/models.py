"""Data models for authentication."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TokenPayload:
    """JWT token payload."""

    iss: str  # issuer
    sub: str  # subject (user_id)
    aud: str  # audience
    org_id: str  # organization_id
    roles: list[str]  # user roles
    iat: int  # issued at (unix timestamp)
    exp: int  # expiry (unix timestamp)
    jti: str  # JWT ID (unique token identifier)


@dataclass
class TokenPair:
    """Access and refresh token pair."""

    access_token: str
    refresh_token: str
    access_token_expires_in: int  # seconds
    refresh_token_expires_in: int  # seconds
    token_type: str = "Bearer"


@dataclass
class PublicKey:
    """RSA public key with metadata."""

    key_id: str
    public_key_pem: str
    created_at: int  # unix timestamp
    expires_at: Optional[int] = None  # unix timestamp, None if no expiry
