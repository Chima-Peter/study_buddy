from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel

FileType = Literal[
    "pdf",
    "txt",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
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
    "png": {".png"},
    "jpg": {".jpg", ".jpeg"},
    "jpeg": {".jpg", ".jpeg"},
    "gif": {".gif"},
    "webp": {".webp"},
    "aws": {".json", ".txt", ".csv"},
    "reddit": {".json", ".txt"},
    "chatgpt": {".json", ".txt"},
    "word": {".doc", ".docx"},
}

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALL_ALLOWED_EXTENSIONS = {
    ext for exts in ALLOWED_EXTENSIONS.values() for ext in exts}


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
    name: str
    category: str
    description: Optional[str] = None
    file_name: str


class UpdateDocumentRequest(BaseModel):
    name: str
    description: str
    category: str


class PatchDocumentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None


class DocumentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    category: str
    status: DocumentStatus
    hash: Optional[str] = None
    path: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class IngestDocumentRequest(BaseModel):
    name: str
    file_name: str
    category: str
    path: str
    user_id: str
    document_id: str
