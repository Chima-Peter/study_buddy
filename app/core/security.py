from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.authentication.service import AuthService
from app.container import Container
from app.system.user.schema import UserResponse
from app.system.user.service import UserService
from app.utils.jwt import verify_token

bearer_scheme = HTTPBearer()


@inject
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    auth_service: AuthService = Depends(Provide[Container.auth_service]),
    user_service: UserService = Depends(Provide[Container.user_service]),
) -> UserResponse:
    token = credentials.credentials
    payload = verify_token(
        token,
        auth_service.settings.jwt_secret,
        auth_service.settings.jwt_algorithm,
    )
    if payload is None or await auth_service.is_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = await user_service.get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


@inject
async def get_current_user_websocket(
    websocket: WebSocket,
    auth_service: AuthService = Depends(Provide[Container.auth_service]),
    user_service: UserService = Depends(Provide[Container.user_service]),
) -> UserResponse:
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing token",
        )

    payload = verify_token(
        token,
        auth_service.settings.jwt_secret,
        auth_service.settings.jwt_algorithm,
    )
    if payload is None or await auth_service.is_blacklisted(token):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token",
        )
    user = await user_service.get_user_by_id(payload["sub"])
    if user is None:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="User not found",
        )
    return user
