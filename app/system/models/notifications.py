from typing import Any, Optional
from datetime import datetime, timezone

import sqlalchemy as sa
import uuid_utils
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.system.schemas.notification import (
    CreateNotificationRequest,
    NotificationResponse,
)


class NotificationModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    user_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    read_at: Optional[datetime] = None

    @field_serializer("created_at", "read_at")
    def serialize_dates(self, value: datetime | None, _info) -> str | None:
        return value.isoformat() if value is not None else None

    def model_dump_for_db(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at,
            "read_at": self.read_at,
        }

    def to_response(self) -> NotificationResponse:
        return NotificationResponse(
            id=self.id,
            title=self.title,
            content=self.content,
            created_at=self.created_at,
            read_at=self.read_at,
        )

    @classmethod
    def from_request(
        cls,
        request: CreateNotificationRequest,
        user_id: str,
    ) -> "NotificationModel":
        return cls(
            user_id=user_id,
            title=request.title,
            content=request.content,
            created_at=datetime.now(timezone.utc),
        )


class NotificationDBModel(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(sa.UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        sa.UUID,
        ForeignKey("users.id"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content: Mapped[str] = mapped_column(sa.String(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    user = relationship("UserDBModel", back_populates="notifications")

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }
