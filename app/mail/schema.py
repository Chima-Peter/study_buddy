from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


AuthEmailType = Literal["signup", "password_reset", "password_changed"]


class AuthEmailRequest(BaseModel):
    type: AuthEmailType
    to: EmailStr
    name: str = Field(min_length=1, max_length=200)
    user_id: str | None = None
    code: str | None = None

    @model_validator(mode="after")
    def require_code_for_password_reset(self) -> "AuthEmailRequest":
        if self.type == "password_reset" and not self.code:
            raise ValueError("code is required for password_reset emails")
        return self
