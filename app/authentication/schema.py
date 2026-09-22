from pydantic import BaseModel, EmailStr, Field

from app.system.user.schema import UserResponse

BLACKLIST_PREFIX = "blacklist:"
PASSWORD_RESET_PREFIX = "password_reset:"
PASSWORD_RESET_TOKEN_PREFIX = "password_reset_token:"
PASSWORD_RESET_TTL_SECONDS = 5 * 60


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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyResetCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class VerifyResetCodeResponse(BaseModel):
    token: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=128)
