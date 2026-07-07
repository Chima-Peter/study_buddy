import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

if TYPE_CHECKING:
    from app.authentication.schemas.auth import RegisterRequest


class UserDBModel(Base):
    """SQLAlchemy database model for users table."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserModel(BaseModel):
    """Pydantic model for User - handles conversions between schemas and DB model."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_db(cls, db_model: UserDBModel) -> Self:
        """Convert SQLAlchemy model to Pydantic model."""
        return cls.model_validate(db_model)

    def to_db(self) -> UserDBModel:
        """Convert Pydantic model to SQLAlchemy model."""
        return UserDBModel(
            id=self.id,
            name=self.name,
            email=self.email,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_register_request(cls, schema: "RegisterRequest", db_model: UserDBModel) -> Self:
        """Create UserModel from register request after DB creation."""
        return cls.from_db(db_model)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
