from pathlib import Path
from typing import IO, Literal

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


class DocumentDetails(BaseModel):
    filename: str
    category: str
    document_id: str
    file: IO[bytes]
    user_id: str
