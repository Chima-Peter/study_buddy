from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
import uuid_utils
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConversationModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    title: Optional[str] = None
    summary: Optional[str] = None
    user_id: str = Field(min_length=36, max_length=36)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime, _info) -> str:
        return value.isoformat()

    def model_dump_for_db(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "user_id": self.user_id,
            "created_at": self.created_at,
        }


class ConversationDBModel(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(sa.UUID, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(sa.String(255), nullable=True)
    user_id: Mapped[str] = mapped_column(
        sa.UUID,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    user = relationship("UserDBModel", back_populates="conversations")
    chats = relationship(
        "ChatDBModel",
        back_populates="conversation",
        order_by="ChatDBModel.created_at",
    )

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "title": self.title,
            "summary": self.summary,
            "user_id": str(self.user_id),
            "created_at": self.created_at.isoformat(),
        }
