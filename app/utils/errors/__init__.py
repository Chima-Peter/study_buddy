from app.utils.errors.auth import EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.document import (
    DocumentCreateError,
    DuplicateDocumentHashError,
    DuplicateDocumentNameError,
    MissingUserForeignKeyError,
    handle_document_integrity_error,
)
from app.utils.errors.user import DuplicateEmailError, UserCreateError

__all__ = [
    "DocumentCreateError",
    "DuplicateDocumentHashError",
    "DuplicateDocumentNameError",
    "DuplicateEmailError",
    "EmailAlreadyExistsError",
    "MissingUserForeignKeyError",
    "UserCreateError",
    "UserNotFoundError",
    "handle_document_integrity_error",
]
