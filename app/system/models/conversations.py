from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
import uuid_utils
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConversationModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    user_id: str = Field(min_length=36, max_length=36)
    query: str = Field(min_length=1)
    conversation: str = Field(default="")
    audit: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_serializer("created_at")
    def serialize_dates(self, value: datetime, _info) -> str:
        return value.isoformat()

    def model_dump_for_db(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "query": self.query,
            "conversation": self.conversation,
            "audit": self.audit,
            "created_at": self.created_at,
        }


class ConversationDBModel(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(sa.UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.UUID,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(sa.String(), nullable=False)
    conversation: Mapped[str] = mapped_column(sa.String(), nullable=False)
    audit: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    user = relationship("UserDBModel", back_populates="conversations")

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "query": self.query,
            "conversation": self.conversation,
            "audit": self.audit or {},
            "created_at": self.created_at.isoformat(),
        }
