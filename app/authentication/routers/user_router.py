from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.authentication.schemas import UserResponse
from app.authentication.schemas.auth import UpdateProfileRequest
from app.authentication.services.auth_service import AuthService
from app.container import Container
from app.core.response import ApiResponse, BasicResponse
from app.core.security import bearer_scheme, get_current_user
from app.utils.errors import EmailAlreadyExistsError, UserNotFoundError

user_router = APIRouter(prefix="/users", tags=["users"])


@user_router.get(
    "/me",
    response_model=ApiResponse,
    summary="Get current user profile",
)
async def get_profile(
    user: Annotated[UserResponse, Depends(get_current_user)],
) -> BasicResponse:
    return BasicResponse(
        data=user.model_dump(mode="json"),
        message="Profile retrieved successfully",
    )


@user_router.patch(
    "/me",
    response_model=ApiResponse,
    summary="Update account details",
)
@inject
async def update_profile(
    data: UpdateProfileRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: AuthService = Depends(Provide[Container.auth_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        response = await service.update_profile(user.id, data)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error updating profile user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=response.model_dump(mode="json"),
        message="Profile updated successfully",
    )


@user_router.delete(
    "/me",
    response_model=ApiResponse,
    summary="Delete account",
)
@inject
async def delete_account(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: AuthService = Depends(Provide[Container.auth_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        await service.delete_account(user.id)
        await service.logout(credentials.credentials)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error deleting account user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(message="Account deleted successfully")
