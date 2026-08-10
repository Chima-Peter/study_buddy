import asyncio
import json
from email.message import EmailMessage
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.core.smtp import SMTPPool
from app.mail.schema import AuthEmailRequest
from app.mail.templates import signup_email


def _build_email(
    request: AuthEmailRequest,
    *,
    from_address: str,
    app_name: str,
) -> EmailMessage:
    if request.type == "signup":
        subject, text, html = signup_email(name=request.name, app_name=app_name)
    else:
        raise ValueError(f"Unsupported auth email type: {request.type}")

    message = EmailMessage()
    message["From"] = from_address
    message["To"] = str(request.to)
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


async def handle_mail(
    message: AbstractIncomingMessage,
    *,
    smtp_pool: SMTPPool,
    logger: Logger,
    rabbitmq: RabbitMQ,
    from_address: str,
    app_name: str,
) -> None:
    payload: dict | None = None

    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body)
            request = AuthEmailRequest(**payload)
            retry_count = read_retry_count(message.headers)

            logger.info(
                "Sending auth email type=%s to=%s user_id=%s retry=%s",
                request.type,
                request.to,
                request.user_id,
                retry_count,
            )
            email = _build_email(
                request,
                from_address=from_address,
                app_name=app_name,
            )
            await asyncio.to_thread(smtp_pool.send_email, email)
            logger.info(
                "Auth email sent type=%s to=%s user_id=%s",
                request.type,
                request.to,
                request.user_id,
            )
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning("Non-retryable auth email payload error: %s", e)
            await message.reject(requeue=False)
            return
        except Exception as e:
            logger.exception("Error sending auth email: %s", e)
            if payload is None:
                await message.reject(requeue=False)
                return

            retry_count = read_retry_count(message.headers)
            if retry_count >= rabbitmq.max_retries:
                logger.error(
                    "Exhausted auth email retries to=%s user_id=%s "
                    "attempts=%s → DLQ",
                    payload.get("to"),
                    payload.get("user_id"),
                    retry_count,
                )
                await message.reject(requeue=False)
                return

            await rabbitmq.schedule_retry(
                "auth_email_queue",
                payload,
                retry_count=retry_count,
                headers=message.headers,
            )
            return
