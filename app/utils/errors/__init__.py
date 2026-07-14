from app.utils.errors.auth import EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.repository import (
    DocumentCreateError,
    DuplicateEmailError,
    MissingUserForeignKeyError,
    UserCreateError,
    handle_document_integrity_error,
)

__all__ = [
    "DocumentCreateError",
    "DuplicateEmailError",
    "EmailAlreadyExistsError",
    "MissingUserForeignKeyError",
    "UserCreateError",
    "UserNotFoundError",
    "handle_document_integrity_error",
]
