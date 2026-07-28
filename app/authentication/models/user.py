import uuid_utils
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, EmailStr, Field, field_serializer
from sqlalchemy import String, func, UUID
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserModel(BaseModel):
    """Pydantic model for User - handles conversions between schemas and DB model."""

    id: str = Field(default_factory=lambda: str(uuid_utils.uuid7()))
    name: str = Field(min_length=3, max_length=255)
    email: EmailStr
    hashed_password: str = Field(min_length=8, max_length=255)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    def serialize_datetime(self, value: datetime) -> str:
        return value.isoformat()

    @field_serializer("created_at", "updated_at")
    def serialize_dates(self, value: datetime, _info) -> str:
        return self.serialize_datetime(value)

    def model_dump_for_db(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "hashed_password": self.hashed_password,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class UserDBModel(Base):
    """SQLAlchemy database model for users table."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    documents = relationship(
        "DocumentDBModel",
        back_populates="user",
    )
    chats = relationship(
        "ChatDBModel",
        back_populates="user",
    )
    notifications = relationship(
        "NotificationDBModel",
        back_populates="user",
    )

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "hashed_password": self.hashed_password,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
