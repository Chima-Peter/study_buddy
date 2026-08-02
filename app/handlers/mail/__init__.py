from app.handlers.mail.consumer import handle_mail
from app.handlers.mail.dlq import handle_mail_dead_letter_queue

__all__ = ["handle_mail", "handle_mail_dead_letter_queue"]
