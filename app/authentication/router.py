from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.authentication.models.user import User
from app.authentication.schemas.auth import (
    FaceIdRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    TokenResponse,
    UserRead,
)
from app.authentication.services.auth_service import AuthService
from app.utils.errors import EmailAlreadyExistsError, UserNotFoundError
from app.container import Container
from app.core.security import bearer_scheme, get_current_user

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register", response_model=UserRead, status_code=status.HTTP_201_CREATED
)
@inject
async def register(
    data: RegisterRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> User:
    try:
        return await service.register(name=data.name, email=data.email)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )


@router.post("/login", response_model=TokenResponse)
@inject
async def login(
    data: LoginRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> TokenResponse:
    try:
        token = await service.login(email=data.email)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    return TokenResponse(access_token=token)


@router.post("/logout", response_model=MessageResponse)
@inject
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    _: Annotated[User, Depends(get_current_user)],
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> MessageResponse:
    await service.logout(credentials.credentials)
    return MessageResponse(detail="Logged out")


@router.post("/change-face-id", response_model=MessageResponse)
async def change_face_id(
    data: FaceIdRequest,
    _: Annotated[User, Depends(get_current_user)],
) -> MessageResponse:
    # Face-id storage lives in a separate service and is not wired up yet.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Changing face id is not implemented yet",
    )


@router.post("/set-new-face-id", response_model=MessageResponse)
async def set_new_face_id(
    data: FaceIdRequest,
    _: Annotated[User, Depends(get_current_user)],
) -> MessageResponse:
    # Face-id storage lives in a separate service and is not wired up yet.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Setting a new face id is not implemented yet",
    )
