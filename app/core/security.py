from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.authentication.schemas import UserResponse
from app.authentication.services.auth_service import AuthService
from app.container import Container
from app.utils.jwt import verify_token

bearer_scheme = HTTPBearer()


@inject
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> UserResponse:
    token = credentials.credentials
    payload = verify_token(
        token, service.settings.jwt_secret, service.settings.jwt_algorithm
    )
    if payload is None or await service.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = await service.get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


@inject
async def get_current_user_websocket(
    websocket: WebSocket,
    service: AuthService = Depends(Provide[Container.auth_service]),
) -> UserResponse:
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing token",
        )

    payload = verify_token(
        token, service.settings.jwt_secret, service.settings.jwt_algorithm
    )
    if payload is None or await service.is_blacklisted(token):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token",
        )
    user = await service.get_user_by_id(payload["sub"])
    if user is None:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="User not found",
        )
    return user
