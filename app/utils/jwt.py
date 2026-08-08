from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.system.user.schema import UserResponse


def generate_token(
    subject: str,
    secret: str,
    algorithm: str,
    expire_minutes: int,
    claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT for the given subject and optional extra claims."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, secret: str, algorithm: str) -> dict:
    """Decode and validate a JWT, raising jwt.PyJWTError on failure."""
    return jwt.decode(token, secret, algorithms=[algorithm])


def verify_token(token: str, secret: str, algorithm: str) -> dict | None:
    """Return the token payload if valid, otherwise None."""
    try:
        return decode_token(token, secret, algorithm)
    except jwt.PyJWTError:
        return None


def user_from_token_payload(payload: dict[str, Any]) -> UserResponse:
    """Build UserResponse from JWT claims (no DB fetch)."""
    return UserResponse(
        id=str(payload["sub"]),
        name=payload["name"],
        email=payload["email"],
        gender=payload.get("gender"),
        university=payload.get("university"),
        bio=payload.get("bio"),
        timezone=payload.get("timezone"),
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
    )
