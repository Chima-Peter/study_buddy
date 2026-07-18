import asyncio
import json
from logging import Logger
from typing import Annotated

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
from app.system.schemas.chat import QueryApiResponse, QueryRequest
from app.system.service.chat import ChatService

chat_router = APIRouter(prefix="/chat", tags=["chat"])


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
    cursor = "0"
    try:
        await websocket.accept()
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
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            if recv_task in done:
                data = recv_task.result()
                if data == "ping":
                    await websocket.send_text("pong")
                else:
                    logger.info(
                        "Received message user_id=%s data=%s",
                        user.id,
                        data,
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
    except Exception:
        logger.exception(
            "Unexpected error in websocket endpoint user_id=%s", user.id
        )
        raise WebSocketException(
            code=status.WS_1006_ABNORMAL_CLOSURE,
            reason="Internal server error",
        )
    finally:
        if stream_name is not None:
            await redis_service.expire_connection(user.id)
