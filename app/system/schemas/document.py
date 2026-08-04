from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel, Field

FileType = Literal[
    "pdf",
    "docx",
    "txt",
    "md",
    "html",
    "doc",
    "rtf",
    "odt",
    "htm",
    "epub",
]

DocumentStatus = Literal[
    "pending",
    "processing",
    "completed",
    "failed",
    "cancelled",
]

DOCUMENT_STATUS_COMMENTS: dict[DocumentStatus, str] = {
    "pending": "Your document is queued and will be processed shortly.",
    "processing": "We're preparing your document now. This may take a moment.",
    "completed": "Your document was processed successfully and is ready to use.",
    "failed": (
        "We couldn't finish processing your document. "
        "Please try again, or contact support if the problem continues."
    ),
    "cancelled": "Processing was cancelled for this document.",
}

ALLOWED_EXTENSIONS: dict[FileType, set[str]] = {
    "pdf": {".pdf"},
    "docx": {".docx"},
    "txt": {".txt"},
    "md": {".md", ".markdown"},
    "html": {".html"},
    "doc": {".doc"},
    "rtf": {".rtf"},
    "odt": {".odt"},
    "htm": {".htm"},
    "epub": {".epub"},
}

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50
ALL_ALLOWED_EXTENSIONS = {
    ext for exts in ALLOWED_EXTENSIONS.values() for ext in exts
}
_ALLOWED_EXT_HELP = ", ".join(sorted(ALL_ALLOWED_EXTENSIONS))


def ingest_failure_comment(
    reason: str,
    *,
    exhausted_retries: bool = False,
) -> str:
    """Build a user-facing ingest failure comment from an error reason."""
    because, hint = _classify_ingest_failure(reason)
    if exhausted_retries:
        return f"Ingestion failed after multiple retries because {because}. {hint}"
    return f"Ingestion failed because {because}. {hint}"


def _classify_ingest_failure(reason: str) -> tuple[str, str]:
    text = (reason or "").strip()
    lowered = text.lower()

    if any(
        token in lowered
        for token in (
            "not found",
            "404",
            "no such file",
            "nosuchkey",
            "object not found",
            "file could not be found",
            "couldn't be found",
            "could not be found",
        )
    ):
        return (
            "the file could not be found",
            "Check that the file was uploaded correctly, then retry ingestion.",
        )

    if "unsupported file type" in lowered:
        return (
            "the file type is not supported",
            "Re-upload a supported file and try again. The supported formats are: "
            + _ALLOWED_EXT_HELP,
        )

    if any(
        token in lowered
        for token in (
            "could not be parsed",
            "couldn't be parsed",
            "error loading",
            "failed to parse",
            "parse",
        )
    ):
        return (
            "the file could not be parsed",
            "Re-upload a supported file and try again. The supported formats are: "
            + _ALLOWED_EXT_HELP,
        )

    if any(
        token in lowered
        for token in (
            "no documents",
            "no readable content",
            "empty",
        )
    ):
        return (
            "no readable content was found in the file",
            "Upload a document with extractable text and try again.",
        )

    if "embedding" in lowered:
        return (
            "embeddings could not be generated",
            "Please retry ingestion. Contact support if the problem continues.",
        )

    if "index" in lowered:
        return (
            "the document could not be indexed",
            "Please retry ingestion. Contact support if the problem continues.",
        )

    if text:
        return (
            text.rstrip("."),
            "Please try again, or contact support if the problem continues.",
        )

    return (
        "processing could not be completed",
        "Please try again, or contact support if the problem continues.",
    )


def validate_upload(
    file: UploadFile,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> None:
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    allowed = ALL_ALLOWED_EXTENSIONS

    if extension not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File '{filename}' has extension '{extension or '(none)'}'; "
                f"allowed: {', '.join(sorted(allowed))}"
            ),
        )

    size = file.size
    if size is None and file.file is not None:
        pos = file.file.tell()
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(pos)

    if size is not None and size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File '{filename}' is {size} bytes; "
                f"max allowed is {max_bytes} bytes"
            ),
        )


class CreateDocumentRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=3,
        max_length=255,
        examples=["Lecture notes week 1"],
        description="Display name for the document",
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=255,
        examples=["pdf"],
        description="Document category/label (free text)",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        examples=["Notes from the first lecture"],
        description="Optional longer description",
    )
    file_name: str = Field(
        ...,
        examples=["notes.pdf"],
        description=(
            "Original filename including extension. "
            f"Allowed extensions: {_ALLOWED_EXT_HELP}"
        ),
    )

class PatchDocumentRequest(BaseModel):
    name: Optional[str] = Field(
        default=None, min_length=3, max_length=255, examples=["Updated title"]
    )
    description: Optional[str] = Field(
        default=None, max_length=1500, examples=["Updated description"]
    )
    category: Optional[str] = Field(
        default=None, min_length=1, max_length=255, examples=["pdf"]
    )
    sections: Optional[str] = Field(default=None, examples=["1,2,3"])


class DocumentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: str
    status: DocumentStatus
    comment: Optional[str] = DOCUMENT_STATUS_COMMENTS["pending"]
    hash: Optional[str] = None
    path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sections: Optional[str] = None


class UploadUrlResponseData(BaseModel):
    upload_url: str = Field(description="Signed URL to PUT the file to storage")
    path: str = Field(description="Storage path for the uploaded file")
    document: DocumentResponse


class UploadUrlApiResponse(BaseModel):
    data: Optional[UploadUrlResponseData] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None


class DocumentApiResponse(BaseModel):
    data: Optional[DocumentResponse] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None


class DocumentListResponseData(BaseModel):
    items: list[DocumentResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int


class DocumentListApiResponse(BaseModel):
    data: Optional[DocumentListResponseData] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None


class IngestDocumentRequest(BaseModel):
    name: str
    file_name: str
    category: str
    path: str
    user_id: str
    document_id: str
    sections: Optional[str] = None
