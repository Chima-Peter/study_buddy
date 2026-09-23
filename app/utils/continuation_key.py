"""Signed continuation keys for chat graph resume.

Format: ``{base64url_payload}.{hmac_sha256_hex}``

Payload (JSON, then base64url) contains ``chat_id``, ``thread_id``,
``checkpointer_id``, ``query_message_id``, and ``response_message_id``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


def create_continuation_key(
    *,
    chat_id: str,
    thread_id: str,
    checkpointer_id: str,
    query_message_id: str,
    response_message_id: str,
    secret: str,
) -> str:
    payload = {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "checkpointer_id": checkpointer_id,
        "query_message_id": query_message_id,
        "response_message_id": response_message_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_continuation_key(
    key: str,
    secret: str,
) -> dict[str, str] | None:
    if not isinstance(key, str) or "." not in key:
        return None

    payload_b64, signature = key.rsplit(".", 1)
    if not payload_b64 or not signature:
        return None

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        data: Any = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    chat_id = data.get("chat_id")
    thread_id = data.get("thread_id")
    checkpointer_id = data.get("checkpointer_id")
    query_message_id = data.get("query_message_id")
    response_message_id = data.get("response_message_id")
    if not all(
        isinstance(value, str) and value
        for value in (
            chat_id,
            thread_id,
            checkpointer_id,
            query_message_id,
            response_message_id,
        )
    ):
        return None

    return {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "checkpointer_id": checkpointer_id,
        "query_message_id": query_message_id,
        "response_message_id": response_message_id,
    }
