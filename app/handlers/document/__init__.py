from app.handlers.document.consumer import handle_document
from app.handlers.document.dlq import handle_document_dead_letter_queue

__all__ = ["handle_document", "handle_document_dead_letter_queue"]
