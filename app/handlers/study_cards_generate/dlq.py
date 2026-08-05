import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage

from app.core.redis import RedisClient


async def handle_study_cards_generate_dead_letter_queue(
    message: AbstractIncomingMessage,
    logger: Logger,
    redis: RedisClient,
) -> None:
    async with message.process():
        body = message.body.decode()
        logger.error(
            "Study cards generate DLQ message id=%s routing_key=%s "
            "body=%s headers=%s",
            message.message_id,
            message.routing_key,
            body,
            message.headers,
        )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.exception("Invalid study cards generate DLQ payload")
            return

        logger.error(
            "Study cards generate exhausted retries document_id=%s user_id=%s",
            payload.get("document_id"),
            payload.get("user_id"),
        )
        await redis.publish_to_user(
            payload.get("user_id"),
            {
                "type": "study_cards_generate_exhausted",
                "data": {
                    "message": (
                        f"Study cards generation for document_id="
                        f"{payload.get('document_id')} failed after all retries"
                    ),
                },
            },
        )
