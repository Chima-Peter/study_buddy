from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, Response, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.authentication.service import AuthService
from app.container import Container
from app.system.user.schema import UserResponse
from app.utils.errors import UserNotFoundError
from app.utils.errors.auth import InvalidCredentialsError
from app.utils.jwt import user_from_token_payload, verify_token

bearer_scheme = HTTPBearer()
NEW_TOKEN_HEADER = "X-New-Token"


@inject
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    response: Response,
    auth_service: AuthService = Depends(Provide[Container.auth_service]),
) -> UserResponse:
    token = credentials.credentials
    if await auth_service.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    payload = verify_token(
        token,
        auth_service.settings.jwt_secret,
        auth_service.settings.jwt_algorithm,
    )
    if payload is not None:
        try:
            return user_from_token_payload(payload)
        except (KeyError, TypeError, ValueError, ValidationError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

    try:
        refreshed = await auth_service.refresh_token(token)
    except (InvalidCredentialsError, UserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    response.headers[NEW_TOKEN_HEADER] = refreshed.token
    return refreshed.user


@inject
async def get_current_user_websocket(
    websocket: WebSocket,
    auth_service: AuthService = Depends(Provide[Container.auth_service]),
) -> UserResponse:
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing token",
        )

    if await auth_service.is_blacklisted(token):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token",
        )

    payload = verify_token(
        token,
        auth_service.settings.jwt_secret,
        auth_service.settings.jwt_algorithm,
    )
    if payload is not None:
        try:
            return user_from_token_payload(payload)
        except (KeyError, TypeError, ValueError, ValidationError):
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid or expired token",
            )

    try:
        refreshed = await auth_service.refresh_token(token)
    except (InvalidCredentialsError, UserNotFoundError):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token",
        )

    websocket.state.refreshed_token = refreshed.token
    return refreshed.user
