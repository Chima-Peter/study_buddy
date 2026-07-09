from aio_pika.abc import AbstractIncomingMessage


async def handle_mail(message: AbstractIncomingMessage) -> None:
    pass
