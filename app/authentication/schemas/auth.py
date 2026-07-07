from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

    def to_dict(self) -> dict:
        return {"access_token": self.access_token, "token_type": self.token_type}


class FaceIdRequest(BaseModel):
    face_id: str
