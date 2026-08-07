from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.authentication.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
)
from app.authentication.schemas.user import UserResponse
from app.authentication.services.auth_service import AuthService
from app.container import Container
from app.core.response import ApiResponse, BasicResponse
from app.core.security import bearer_scheme, get_current_user
from app.utils.errors import EmailAlreadyExistsError, UserNotFoundError
from app.utils.errors.auth import InvalidCredentialsError

auth_router = APIRouter(prefix="/authentication", tags=["authentication"])


@auth_router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse,
    summary="Register user",
)
@inject
async def register(
    data: RegisterRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        response = await service.register(data)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    except Exception:
        logger.exception("Unexpected error during registration email=%s", data.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=response.model_dump(mode="json"),
        message="User registered successfully",
        status_code=status.HTTP_201_CREATED,
    )


@auth_router.post(
    "/login",
    response_model=ApiResponse,
    summary="Login",
)
@inject
async def login(
    data: LoginRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        response = await service.login(request=data)
    except (InvalidCredentialsError, UserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password or email",
        )
    except Exception:
        logger.exception("Unexpected error during login email=%s", data.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=response.model_dump(mode="json"),
        message="Login successful",
    )


@auth_router.post(
    "/refresh",
    response_model=ApiResponse,
    summary="Refresh token",
    description=(
        "Exchange an expired JWT for a new access token. "
        "Only tokens that expired within the last 10 minutes are accepted. "
        "Blacklisted tokens are rejected."
    ),
)
@inject
async def refresh(
    data: RefreshTokenRequest,
    service: AuthService = Depends(Provide[Container.auth_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        response = await service.refresh_token(data)
    except (InvalidCredentialsError, UserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    except Exception:
        logger.exception("Unexpected error during token refresh")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=response.model_dump(mode="json"),
        message="Token refreshed successfully",
    )


@auth_router.post(
    "/logout",
    response_model=ApiResponse,
    summary="Logout",
    description=(
        "Requires a valid Bearer token. "
        "Blacklists it for its remaining lifetime."
    ),
)
@inject
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    _: Annotated[UserResponse, Depends(get_current_user)],
    service: AuthService = Depends(Provide[Container.auth_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        await service.logout(credentials.credentials)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    except Exception:
        logger.exception("Unexpected error during logout")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(message="Logged out successfully")
