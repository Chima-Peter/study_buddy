from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel, Field

FileType = Literal[
    "pdf",
    "txt",
    "csv",
    "json",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "markdown",
    "aws",
    "reddit",
    "chatgpt",
    "word",
]

DocumentStatus = Literal[
    "pending",
    "processing",
    "completed",
    "failed",
    "cancelled",
]

ALLOWED_EXTENSIONS: dict[FileType, set[str]] = {
    "pdf": {".pdf"},
    "txt": {".txt"},
    "csv": {".csv"},
    "json": {".json"},
    "png": {".png"},
    "jpg": {".jpg", ".jpeg"},
    "jpeg": {".jpg", ".jpeg"},
    "gif": {".gif"},
    "webp": {".webp"},
    "markdown": {".md", ".markdown"},
    "aws": {".json", ".txt", ".csv"},
    "reddit": {".json", ".txt"},
    "chatgpt": {".json", ".txt"},
    "word": {".doc", ".docx"},
}

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALL_ALLOWED_EXTENSIONS = {
    ext for exts in ALLOWED_EXTENSIONS.values() for ext in exts
}
_ALLOWED_EXT_HELP = ", ".join(sorted(ALL_ALLOWED_EXTENSIONS))


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


class UpdateDocumentRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=255, examples=["Updated title"])
    description: str = Field(..., max_length=2000, examples=["Updated description"])
    category: str = Field(..., min_length=1, max_length=255, examples=["pdf"])


class PatchDocumentRequest(BaseModel):
    name: Optional[str] = Field(
        default=None, min_length=3, max_length=255, examples=["Updated title"]
    )
    description: Optional[str] = Field(
        default=None, max_length=2000, examples=["Updated description"]
    )
    category: Optional[str] = Field(
        default=None, min_length=1, max_length=255, examples=["csv"]
    )


class DocumentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category: str
    status: DocumentStatus
    hash: Optional[str] = None
    path: Optional[str] = None
    created_at: datetime
    updated_at: datetime


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


class DocumentListApiResponse(BaseModel):
    data: Optional[list[DocumentResponse]] = None
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
