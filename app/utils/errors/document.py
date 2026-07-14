from sqlalchemy.exc import IntegrityError


class DocumentCreateError(Exception):
    """Failed to create document."""


class DuplicateDocumentNameError(DocumentCreateError):
    """Document name already exists in the database."""

    def __init__(self, name: str | None = None):
        self.name = name
        message = f"A document with the name '{name}' already exists" if name else "Document name already exists"
        super().__init__(message)


class MissingUserForeignKeyError(DocumentCreateError):
    """user_id does not reference an existing user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User not found for user_id={user_id}")


def handle_document_integrity_error(
    error: IntegrityError,
    *,
    user_id: str,
    document_name: str | None = None,
) -> None:
    """Raise a typed error for known document IntegrityError cases.

    Detects a missing users.id foreign key on documents.user_id.
    Re-raises DocumentCreateError for other integrity failures.
    """
    message = str(error.orig).lower() if error.orig else str(error).lower()
    is_foreign_key = (
        "foreign key" in message
        or "foreignkeyviolation" in message
    )
    references_user = "user_id" in message or "users" in message
    is_duplicate_name = "unique constraint" in message or "uq_documents_name" in message

    if is_foreign_key and references_user:
        raise MissingUserForeignKeyError(user_id) from error

    if is_duplicate_name:
        raise DuplicateDocumentNameError(document_name) from error

    raise DocumentCreateError(str(error)) from error
