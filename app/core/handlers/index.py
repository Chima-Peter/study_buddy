from logging import Logger

from aio_pika.abc import AbstractIncomingMessage

from app.core.handlers.dead_letter_queue import handle_dead_letter_queue as process_dead_letter_queue
from app.core.handlers.document import handle_document
from app.core.handlers.mail import handle_mail


class Handlers:
    def __init__(self, logger: Logger):
        self._logger = logger

    async def handle_mail(self, message: AbstractIncomingMessage) -> None:
        await handle_mail(message)

    async def handle_document(self, message: AbstractIncomingMessage) -> None:
        await handle_document(message)

    async def handle_dead_letter_queue(self, message: AbstractIncomingMessage) -> None:
        await process_dead_letter_queue(message, self._logger)
