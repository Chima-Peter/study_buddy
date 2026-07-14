import re
from typing import Iterable

from sqlalchemy.exc import IntegrityError

_UNIQUE_KEY_RE = re.compile(
    r"key \(([^)]+)\)=\((.+)\) already exists",
    re.IGNORECASE,
)


def _format_file_names(file_names: Iterable[str] | str | None) -> list[str]:
    if file_names is None:
        return []
    if isinstance(file_names, str):
        return [file_names] if file_names else []
    return [file_name for file_name in file_names if file_name]


def _file_names_suffix(file_names: list[str]) -> str:
    if not file_names:
        return ""
    labeled = ", ".join(f"'{file_name}'" for file_name in file_names)
    return f" ({labeled})"


def _document_file_names(documents: list) -> list[str]:
    return [
        getattr(document, "display_file_name", None)
        or getattr(document, "file_name", None)
        or getattr(document, "name", None)
        for document in documents
        if getattr(document, "display_file_name", None)
        or getattr(document, "file_name", None)
        or getattr(document, "name", None)
    ]


class DocumentCreateError(Exception):
    """Failed to create document."""

    def __init__(
        self,
        message: str | None = None,
        *,
        file_names: Iterable[str] | str | None = None,
    ):
        self.file_names = _format_file_names(file_names)
        base = message or "Failed to create document"
        super().__init__(f"{base}{_file_names_suffix(self.file_names)}")


class DuplicateDocumentNameError(DocumentCreateError):
    """Document name already exists in the database."""

    def __init__(
        self,
        name: str | None = None,
        *,
        file_names: Iterable[str] | str | None = None,
    ):
        self.name = name
        formatted = _format_file_names(file_names)
        if name and formatted:
            message = (
                f"A document with the name '{name}' already exists"
                f"{_file_names_suffix(formatted)}"
            )
        elif name:
            message = f"A document with the name '{name}' already exists"
        else:
            message = f"Document name already exists{_file_names_suffix(formatted)}"
        Exception.__init__(self, message)
        self.file_names = formatted


class DuplicateDocumentHashError(DocumentCreateError):
    """Document hash already exists for this user."""

    def __init__(
        self,
        document_hash: str | None = None,
        *,
        file_name: str | None = None,
        file_names: Iterable[str] | str | None = None,
    ):
        self.hash = document_hash
        formatted = _format_file_names(file_names) or _format_file_names(file_name)
        message = (
            f"A document with this content already exists{_file_names_suffix(formatted)}"
            if document_hash or formatted
            else "Document already exists"
        )
        Exception.__init__(self, message)
        self.file_names = formatted


class MissingUserForeignKeyError(DocumentCreateError):
    """user_id does not reference an existing user."""

    def __init__(
        self,
        user_id: str,
        *,
        file_names: Iterable[str] | str | None = None,
    ):
        self.user_id = user_id
        super().__init__("User not found", file_names=file_names)


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
    documents: list | None = None,
) -> None:
    """Raise a typed error for known document IntegrityError cases.

    Reads the conflicting column/value from the Postgres error detail when
    available, so batch inserts report the real failing document.
    """
    message = str(error.orig) if error.orig else str(error)
    message_lower = message.lower()
    docs = documents or []
    file_names = _document_file_names(docs)

    is_foreign_key = (
        "foreign key" in message_lower
        or "foreignkeyviolation" in message_lower
    )
    references_user = "user_id" in message_lower or "users" in message_lower
    if is_foreign_key and references_user:
        raise MissingUserForeignKeyError(user_id, file_names=file_names) from error

    fields = _extract_unique_violation(message)

    if "name" in fields or "uq_documents_name" in message_lower:
        conflict_name = fields.get("name")
        matching = [
            document.display_file_name
            for document in docs
            if conflict_name and document.name == conflict_name
        ]
        raise DuplicateDocumentNameError(
            conflict_name,
            file_names=matching or file_names,
        ) from error

    is_duplicate_hash = (
        ("hash" in fields and "user_id" in fields)
        or "uq_documents_hash_user_id" in message_lower
    )
    if is_duplicate_hash:
        document_hash = fields.get("hash")
        matching = [
            document.display_file_name
            for document in docs
            if document_hash
            and (document.hash or "").strip() == document_hash
        ]
        raise DuplicateDocumentHashError(
            document_hash,
            file_names=matching or file_names,
        ) from error

    raise DocumentCreateError(
        "Failed to create document",
        file_names=file_names,
    ) from error
