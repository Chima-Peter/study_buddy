from typing import Any, Optional
import uuid_utils
from pydantic import BaseModel, Field, field_serializer
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMP

from app.database import Base
from app.system.schemas.document import (
    CreateDocumentRequest,
    DocumentResponse,
    DocumentStatus,
    PatchDocumentRequest,
    UpdateDocumentRequest,
)


class DocumentModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    name: str = Field(min_length=3, max_length=255)
    description: Optional[str] = Field(max_length=2000, default="")
    category: str = Field(min_length=3, max_length=255)
    user_id: str = Field(min_length=36, max_length=36)
    hash: Optional[str] = Field(max_length=255, default="")
    path: str = Field(max_length=255, default="")
    status: DocumentStatus = Field(default="pending")
    file_name: Optional[str] = Field(default=None, exclude=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    @property
    def display_file_name(self) -> str:
        return self.file_name or self.name

    def serialize_datetime(self, value: datetime) -> str:
        return value.isoformat()

    @field_serializer("created_at", "updated_at")
    def serialize_dates(self, value: datetime, _info) -> str:
        return self.serialize_datetime(value)

    def model_dump_for_db(self) -> dict:
        document_hash = (self.hash or "").strip() or None
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "user_id": self.user_id,
            "hash": document_hash,
            "path": self.path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def update_from_request(self, request: UpdateDocumentRequest) -> None:
        self.name = request.name
        self.description = request.description
        self.category = request.category
        self.updated_at = datetime.now(timezone.utc)

    def patch_from_request(self, request: PatchDocumentRequest) -> None:
        if request.name is not None:
            self.name = request.name
        if request.description is not None:
            self.description = request.description
        if request.category is not None:
            self.category = request.category
        self.updated_at = datetime.now(timezone.utc)

    @classmethod
    def from_request(
        cls,
        request: CreateDocumentRequest,
        user_id: str,
        path: str,
    ) -> "DocumentModel":
        return cls(
            name=request.name,
            description=request.description,
            category=request.category,
            user_id=user_id,
            file_name=request.file_name,
            path=path,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def to_response(self) -> DocumentResponse:
        return DocumentResponse(
            id=self.id,
            name=self.name,
            description=self.description,
            category=self.category,
            status=self.status,
            hash=self.hash,
            path=self.path,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class DocumentDBModel(Base):
    __tablename__ = "documents"
    __table_args__ = (
        sa.UniqueConstraint("hash", "user_id", name="uq_documents_hash_user_id"),
    )

    id: Mapped[str] = mapped_column(sa.UUID, primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(
        sa.String(), nullable=True)
    category: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.UUID,
        ForeignKey("users.id"),
        nullable=False,
    )
    hash: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True, default="pending", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    user = relationship("UserDBModel", back_populates="documents")


    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "hash": self.hash,
            "path": str(self.path),
            "status": self.status or "pending",
            "user_id": str(self.user_id),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
