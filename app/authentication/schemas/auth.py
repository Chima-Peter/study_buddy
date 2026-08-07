from pydantic import BaseModel, EmailStr

from app.authentication.schemas.user import UserResponse

BLACKLIST_PREFIX = "blacklist:"

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    user: UserResponse
    token: str


class RefreshTokenRequest(BaseModel):
    token: str
