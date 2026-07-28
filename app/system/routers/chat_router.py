import asyncio
import json
from logging import Logger
from typing import Annotated

from redis.exceptions import ConnectionError
from dependency_injector.wiring import Provide, inject
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.redis import RedisClient
from app.core.security import get_current_user, get_current_user_websocket
from app.system.schemas.chat import ConversationResponse
from app.system.service.chat import ChatService

chat_router = APIRouter(prefix="/chat", tags=["chat"])

MAX_PAYLOAD_SIZE = 64 * 1024
MAX_CONNECTIONS_PER_USER = 5

@chat_router.get(
    "",
    response_model=list[ConversationResponse],
    summary="Get conversations",
    description="Get conversations for a user",
)
@inject
async def list_conversations(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ChatService = Depends(Provide[Container.chat_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> list[ConversationResponse]:
    try:
        return await service.list_by_user(user.id)
    except Exception:
        logger.exception(
            "Unexpected error listing conversations user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@chat_router.websocket("")
@inject
async def websocket_endpoint(
    websocket: WebSocket,
    user: Annotated[UserResponse, Depends(get_current_user_websocket)],
    logger: Logger = Depends(Provide[Container.logger]),
    service: ChatService = Depends(Provide[Container.chat_service]),
    redis_service: RedisClient = Depends(Provide[Container.redis_client]),
) -> None:
    stream_name: str | None = None
    cursor = websocket.query_params.get("cursor", "0")
    connection_counted = False

    try:
        connection_count = await redis_service.get_connection_count(user.id)
        if connection_count >= MAX_CONNECTIONS_PER_USER:
            logger.warning(
                "Too many connections user_id=%s count=%d",
                user.id,
                connection_count,
            )
            await websocket.close(
              code=status.WS_1008_POLICY_VIOLATION,
              reason="Too many connections. Max connections per user is 5."
              )
            return

        await websocket.accept()
        await redis_service.incr_connection_count(user.id)
        connection_counted = True
        await websocket.send_text("Hello!")

        while True:
            chat_task = asyncio.create_task(websocket.receive_text())

            async def idle_ping() -> None:
                await asyncio.sleep(80)
                await websocket.send_text("ping")

            ping_task = asyncio.create_task(idle_ping())
            done, pending = await asyncio.wait(
                {chat_task, ping_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=80,
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            if chat_task in done:
                message = chat_task.result()
                if len(message.encode("utf-8")) > MAX_PAYLOAD_SIZE:
                    logger.warning(
                        "Message too big user_id=%s size=%d",
                        user.id,
                        len(message),
                    )
                    await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                    return

                if message == "ping":
                    await websocket.send_text("pong")
                else:
                    logger.info(
                        "Received message user_id=%s type=%s",
                        user.id,
                        message,
                    )
                    async for chunk in service.query(
                        user_id=user.id,
                        query=message,
                    ):
                        await websocket.send_text(chunk)
                    await websocket.send_text("DONE")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected user_id=%s", user.id)
    except asyncio.TimeoutError:
        logger.warning(
            "Timeout error user_id=%s", user.id
        )
        await websocket.close(
            code=status.WS_1001_GOING_AWAY,
            reason="Timeout error",
        )
        return
    except ConnectionError:
        logger.exception(
            "Redis connection error user_id=%s", user.id
        )
        await websocket.close(
            code=status.WS_1012_SERVICE_RESTART,
        )
    except Exception:
        logger.exception(
            "Unexpected error in websocket endpoint user_id=%s", user.id
        )
        try:
            await websocket.send_text(json.dumps({"type": "error", "cursor": cursor}))
        except Exception:
            logger.exception(
                "Unexpected error sending error message user_id=%s", user.id
            )
        raise WebSocketException(
            code=status.WS_1006_ABNORMAL_CLOSURE,
            reason="Internal server error",
        )
    finally:
        if connection_counted:
            await redis_service.decr_connection_count(user.id)