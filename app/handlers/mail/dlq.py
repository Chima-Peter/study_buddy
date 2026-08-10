from logging import Logger

from aio_pika.abc import AbstractIncomingMessage


async def handle_mail_dead_letter_queue(
    message: AbstractIncomingMessage,
    logger: Logger,
) -> None:
    async with message.process():
        logger.error(
            "Auth email DLQ message id=%s routing_key=%s body=%s headers=%s",
            message.message_id,
            message.routing_key,
            message.body.decode(),
            message.headers,
        )
