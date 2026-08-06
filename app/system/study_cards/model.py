from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
import uuid_utils
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.system.study_cards.schema import StudyCardsResultResponse, StudyCardsStatus


class StudyCardsModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    user_id: str = Field(min_length=36, max_length=36)
    document_id: str = Field(min_length=36, max_length=36)
    status: StudyCardsStatus = "pending"
    result: Optional[dict[str, Any]] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_serializer("created_at", "updated_at")
    def serialize_dates(self, value: datetime, _info) -> str:
        return value.isoformat()

    def model_dump_for_db(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "document_id": self.document_id,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_response(
        self,
        document_name: str | None = None,
    ) -> StudyCardsResultResponse:
        return StudyCardsResultResponse(
            id=self.id,
            document_id=self.document_id,
            document_name=document_name,
            status=self.status,
            result=self.result,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )

    @classmethod
    def pending(cls, *, document_id: str, user_id: str) -> "StudyCardsModel":
        return cls(
            document_id=document_id,
            user_id=user_id,
            status="pending",
            result=None,
        )


class StudyCardsDBModel(Base):
    __tablename__ = "study_cards"

    id: Mapped[str] = mapped_column(sa.UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.UUID,
        ForeignKey("users.id"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        sa.UUID,
        ForeignKey("documents.id"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    user = relationship("UserDBModel", back_populates="study_cards")
    document = relationship("DocumentDBModel", back_populates="study_cards")

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "document_id": str(self.document_id),
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
