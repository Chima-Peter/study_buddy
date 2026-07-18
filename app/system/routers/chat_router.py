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
from app.core.response import BasicResponse
from app.core.security import get_current_user, get_current_user_websocket
from app.system.schemas.chat import QueryApiResponse, QueryRequest, validate_ws_message
from app.system.service.chat import ChatService

chat_router = APIRouter(prefix="/chat", tags=["chat"])

MAX_PAYLOAD_SIZE = 64 * 1024
MAX_CONNECTIONS_PER_USER = 5
ALLOWED_MESSAGE_TYPES = {"ping", "query", "subscribe", "unsubscribe"}


def validate_message(data: str) -> tuple[bool, str | dict]:
    """Validate incoming WebSocket message. Returns (is_valid, parsed_data_or_error)."""
    if data == "ping":
        return True, "ping"
    try:
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            return False, "Message must be a JSON object"
        msg_type = parsed.get("type")
        if not msg_type:
            return False, "Missing 'type' field"
        if msg_type not in ALLOWED_MESSAGE_TYPES:
            return False, f"Invalid message type: {msg_type}"
        return True, parsed
    except json.JSONDecodeError:
        return False, "Invalid JSON"


@chat_router.post(
    "/query",
    response_model=QueryApiResponse,
    summary="Query documents",
    description=(
        "RAG pipeline: embed query → Elasticsearch search (hybrid/vector/bm25) "
        "→ Gemini answer. Always retrieves the top 5 chunks."
    ),
)
@inject
async def query_documents(
    request: QueryRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ChatService = Depends(Provide[Container.chat_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.query(
            user.id,
            request.query,
        )
    except Exception:
        logger.exception(
            "Unexpected error querying documents user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Query completed successfully",
    )


@chat_router.websocket("")
@inject
async def websocket_endpoint(
    websocket: WebSocket,
    user: Annotated[UserResponse, Depends(get_current_user_websocket)],
    logger: Logger = Depends(Provide[Container.logger]),
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
        stream_name = await redis_service.orchestrate_stream(user.id)
        await websocket.send_text("Hello!")

        while True:
            recv_task = asyncio.create_task(websocket.receive_text())
            stream_task = asyncio.create_task(
                redis_service.read_stream(stream_name, cursor)
            )

            done, pending = await asyncio.wait(
                {recv_task, stream_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=600,
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            if recv_task in done:
                data = recv_task.result()
                if len(data.encode("utf-8")) > MAX_PAYLOAD_SIZE:
                    logger.warning(
                        "Message too big user_id=%s size=%d",
                        user.id,
                        len(data),
                    )
                    await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                    return

                is_valid, result = validate_ws_message(data)
                if not is_valid:
                    logger.warning(
                        "Invalid message user_id=%s error=%s",
                        user.id,
                        result,
                    )
                    await websocket.close(code=status.WS_1007_INVALID_FRAME_PAYLOAD_DATA)
                    return

                if result.type == "ping":
                    await websocket.send_text("pong")
                else:
                    logger.info(
                        "Received message user_id=%s type=%s",
                        user.id,
                        result.type,
                    )

            if stream_task in done:
                messages = stream_task.result()
                for message_id, fields in messages:
                    cursor = message_id
                    event_type = fields.get("type", "message")
                    raw_data = fields.get("data", "{}")
                    try:
                        payload_data = json.loads(raw_data)
                    except (TypeError, json.JSONDecodeError):
                        payload_data = raw_data

                    await websocket.send_text(
                        json.dumps({"type": event_type, "data": payload_data})
                    )
                    await redis_service.delete_message_from_stream(
                        stream_name, message_id
                    )
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
        if stream_name is not None:
            await redis_service.expire_connection(user.id)
