from typing import Literal

from pydantic import BaseModel, EmailStr, Field


AuthEmailType = Literal["signup"]


class AuthEmailRequest(BaseModel):
    type: AuthEmailType
    to: EmailStr
    name: str = Field(min_length=1, max_length=200)
    user_id: str | None = None
