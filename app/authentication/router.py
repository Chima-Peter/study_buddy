import logging
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.authentication.schemas import UserResponse
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
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    except Exception:
        logger.exception("Unexpected error during registration")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=response.model_dump(mode="json"),
        message="User registered successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/login")
@inject
async def login(
    data: LoginRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> BasicResponse:
    try:
        response = await service.login(request=data)
    except (InvalidCredentialsError, UserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password or email",
        )
    except Exception:
        logger.exception("Unexpected error during login")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=response.model_dump(mode="json"),
        message="Login successful",
    )


@router.post("/logout")
@inject
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    _: Annotated[UserResponse, Depends(get_current_user)],
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> BasicResponse:
    try:
        await service.logout(credentials.credentials)
    except Exception:
        logger.exception("Unexpected error during logout")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(message="Logged out successfully")
