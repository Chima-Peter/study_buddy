from app.utils.errors.auth import EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.document import (
    DocumentCreateError,
    DocumentNotRetryableError,
    DuplicateDocumentHashError,
    DuplicateDocumentNameError,
    MissingUserForeignKeyError,
    handle_document_integrity_error,
)
from app.utils.errors.notification import NotificationNotFoundError
from app.utils.errors.user import DuplicateEmailError, UserCreateError

__all__ = [
    "DocumentCreateError",
    "DocumentNotRetryableError",
    "DuplicateDocumentHashError",
    "DuplicateDocumentNameError",
    "DuplicateEmailError",
    "EmailAlreadyExistsError",
    "MissingUserForeignKeyError",
    "NotificationNotFoundError",
    "UserCreateError",
    "UserNotFoundError",
    "handle_document_integrity_error",
]
