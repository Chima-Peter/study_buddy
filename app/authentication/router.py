import logging
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials

from app.authentication.models.user import UserModel
from app.authentication.schemas.auth import (
    LoginRequest,
    RegisterRequest,
)
from app.authentication.services.auth_service import AuthService
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import bearer_scheme, get_current_user
from app.utils.errors import EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.auth import InvalidCredentialsError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
@inject
async def register(
    data: RegisterRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> BasicResponse:
    try:
        response = await service.register(data)
        return BasicResponse(
            data=response.model_dump(),
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
        response = await service.login(request=data)
        return BasicResponse(
            data=response.model_dump(),
            message="Login successful",
        )
    except (InvalidCredentialsError, UserNotFoundError) as e:
        return BasicResponse(
            error="Incorrect password or email",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception as e:
        logger.exception(f"Unexpected error during login: {e}")
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
