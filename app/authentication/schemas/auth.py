import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FaceIdRequest(BaseModel):
    face_id: str


class MessageResponse(BaseModel):
    detail: str
