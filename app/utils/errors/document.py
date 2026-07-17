import re

from sqlalchemy.exc import IntegrityError

from app.system.models.documents import DocumentModel

_UNIQUE_KEY_RE = re.compile(
    r"key \(([^)]+)\)=\((.+)\) already exists",
    re.IGNORECASE,
)


def _file_name_suffix(file_name: str | None) -> str:
    if not file_name:
        return ""
    return f" ('{file_name}')"


class DocumentCreateError(Exception):
    """Failed to create document."""

    def __init__(
        self,
        message: str | None = None,
        *,
        file_name: str | None = None,
    ):
        self.file_name = file_name
        base = message or "Failed to create document"
        super().__init__(f"{base}{_file_name_suffix(file_name)}")


class DuplicateDocumentNameError(DocumentCreateError):
    """Document name already exists in the database."""

    def __init__(
        self,
        name: str | None = None,
        *,
        file_name: str | None = None,
    ):
        self.name = name
        if name:
            message = f"A document with the name '{name}' already exists"
        else:
            message = "Document name already exists"
        super().__init__(message, file_name=file_name)


class DuplicateDocumentHashError(DocumentCreateError):
    """Document hash already exists for this user."""

    def __init__(
        self,
        document_hash: str | None = None,
        *,
        file_name: str | None = None,
    ):
        self.hash = document_hash
        super().__init__(
            "A document with this content already exists",
            file_name=file_name,
        )


class MissingUserForeignKeyError(DocumentCreateError):
    """user_id does not reference an existing user."""

    def __init__(
        self,
        user_id: str,
        *,
        file_name: str | None = None,
    ):
        self.user_id = user_id
        super().__init__("User not found", file_name=file_name)


class DocumentNotRetryableError(Exception):
    """Document cannot be retried because it is not in failed status."""

    def __init__(self, document_id: str, status: str):
        self.document_id = document_id
        self.status = status
        super().__init__(
            f"Document '{document_id}' cannot be retried from status '{status}'"
        )


def _extract_unique_violation(message: str) -> dict[str, str]:
    """Parse Postgres unique detail like Key (hash, user_id)=(abc, uuid)."""
    match = _UNIQUE_KEY_RE.search(message)
    if not match:
        return {}

    columns = [column.strip().lower() for column in match.group(1).split(",")]
    values = [value.strip() for value in match.group(2).split(",")]
    if len(columns) != len(values):
        return {}
    return dict(zip(columns, values))


def handle_document_integrity_error(
    error: IntegrityError,
    *,
    user_id: str,
    document: DocumentModel | None = None,
) -> None:
    """Raise a typed error for known document IntegrityError cases."""
    message = str(error.orig) if error.orig else str(error)
    message_lower = message.lower()
    file_name = document.display_file_name if document else None

    is_foreign_key = (
        "foreign key" in message_lower
        or "foreignkeyviolation" in message_lower
    )
    references_user = "user_id" in message_lower or "users" in message_lower
    if is_foreign_key and references_user:
        raise MissingUserForeignKeyError(user_id, file_name=file_name) from error

    fields = _extract_unique_violation(message)

    if "name" in fields or "uq_documents_name" in message_lower:
        raise DuplicateDocumentNameError(
            fields.get("name"),
            file_name=file_name,
        ) from error

    is_duplicate_hash = (
        ("hash" in fields and "user_id" in fields)
        or "uq_documents_hash_user_id" in message_lower
    )
    if is_duplicate_hash:
        raise DuplicateDocumentHashError(
            fields.get("hash"),
            file_name=file_name,
        ) from error

    raise DocumentCreateError(
        "Failed to create document",
        file_name=file_name,
    ) from error
