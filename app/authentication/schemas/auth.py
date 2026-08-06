from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=3, max_length=255)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=255)
    gender: Optional[str] = Field(default=None, max_length=50)
    university: Optional[str] = Field(default=None, max_length=255)
    bio: Optional[str] = Field(default=None, max_length=1500)
    timezone: Optional[str] = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateProfileRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class UserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    gender: Optional[str] = None
    university: Optional[str] = None
    bio: Optional[str] = None
    timezone: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class LoginResponse(BaseModel):
    user: UserResponse
    token: str

class RefreshTokenRequest(BaseModel):
    token: str