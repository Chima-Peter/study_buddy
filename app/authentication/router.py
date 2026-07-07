import logging
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials

from app.authentication.models.user import UserModel
from app.authentication.schemas.auth import (
    FaceIdRequest,
    LoginRequest,
    RegisterRequest,
)
from app.authentication.services.auth_service import AuthService
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import bearer_scheme, get_current_user
from app.utils.errors import EmailAlreadyExistsError, UserNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
@inject
async def register(
    data: RegisterRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> BasicResponse:
    try:
        user, token = await service.register(name=data.name, email=data.email)
        return BasicResponse(
            data={
                "user": user.to_dict(),
                "access_token": token,
                "token_type": "bearer",
            },
            message="User registered successfully",
            status_code=status.HTTP_201_CREATED,
        )
    except EmailAlreadyExistsError:
        return BasicResponse(
            error="Email already registered",
            status_code=status.HTTP_409_CONFLICT,
        )
    except Exception:
        logger.exception("Unexpected error during registration")
        return BasicResponse(
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/login")
@inject
async def login(
    data: LoginRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> BasicResponse:
    try:
        token = await service.login(email=data.email)
        return BasicResponse(
            data={"access_token": token, "token_type": "bearer"},
            message="Login successful",
        )
    except UserNotFoundError:
        return BasicResponse(
            error="Invalid credentials",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception:
        logger.exception("Unexpected error during login")
        return BasicResponse(
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/logout")
@inject
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    _: Annotated[UserModel, Depends(get_current_user)],
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> BasicResponse:
    try:
        await service.logout(credentials.credentials)
        return BasicResponse(message="Logged out successfully")
    except Exception:
        logger.exception("Unexpected error during logout")
        return BasicResponse(
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/change-face-id")
async def change_face_id(
    data: FaceIdRequest,
    _: Annotated[UserModel, Depends(get_current_user)],
) -> BasicResponse:
    return BasicResponse(
        error="Changing face id is not implemented yet",
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )


@router.post("/set-new-face-id")
async def set_new_face_id(
    data: FaceIdRequest,
    _: Annotated[UserModel, Depends(get_current_user)],
) -> BasicResponse:
    return BasicResponse(
        error="Setting a new face id is not implemented yet",
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
