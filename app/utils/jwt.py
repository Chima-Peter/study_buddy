from datetime import datetime, timedelta, timezone

import jwt


def generate_token(
    subject: str, secret: str, algorithm: str, expire_minutes: int
) -> str:
    """Create a signed JWT for the given subject."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
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
