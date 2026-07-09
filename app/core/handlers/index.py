from aio_pika.abc import AbstractIncomingMessage

from app.core.handlers.document import handle_document
from app.core.handlers.mail import handle_mail


class Handlers:
    async def handle_mail(self, message: AbstractIncomingMessage) -> None:
        await handle_mail(message)

    async def handle_document(self, message: AbstractIncomingMessage) -> None:
        await handle_document(message)
