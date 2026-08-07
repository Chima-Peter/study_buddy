from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
import uuid_utils
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.system.question_bank.schema import (
    QuestionBankResultResponse,
    QuestionBankStatus,
)


class QuestionBankModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    user_id: str = Field(min_length=36, max_length=36)
    document_id: str = Field(min_length=36, max_length=36)
    status: QuestionBankStatus = "pending"
    result: Optional[Any] = None
    question_count: int = 0
    reason: Optional[str] = None
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
            "question_count": self.question_count,
            "reason": self.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_response(
        self,
        document_name: str | None = None,
    ) -> QuestionBankResultResponse:
        return QuestionBankResultResponse(
            id=self.id,
            document_id=self.document_id,
            document_name=document_name,
            status=self.status,
            result=self.result,
            question_count=self.question_count,
            reason=self.reason,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )

    @classmethod
    def pending(cls, *, document_id: str, user_id: str) -> "QuestionBankModel":
        return cls(
            document_id=document_id,
            user_id=user_id,
            status="pending",
            question_count=0,
            result=None,
        )


class QuestionBankDBModel(Base):
    __tablename__ = "question_banks"

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
    question_count: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    result: Mapped[Optional[Any]] = mapped_column(
        JSONB,
        nullable=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
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

    user = relationship("UserDBModel", back_populates="question_banks")
    document = relationship("DocumentDBModel", back_populates="question_banks")

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "document_id": str(self.document_id),
            "status": self.status,
            "result": self.result,
            "question_count": self.question_count,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
