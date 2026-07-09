from aio_pika.abc import AbstractIncomingMessage


async def handle_document(message: AbstractIncomingMessage) -> None:
    async with message.process():
        pass
