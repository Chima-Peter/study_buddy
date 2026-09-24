import asyncio
import json
from logging import Logger
from typing import Annotated, Any

from app.agent.chat_agent.graph import AgentGraph
from redis.exceptions import ConnectionError
from dependency_injector.wiring import Provide, inject
from fastapi import (
    APIRouter,
    Depends,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.system.user.schema import UserResponse
from app.container import Container
from app.core.redis import RedisClient
from app.core.security import get_current_user_websocket
from app.system.chat.service import ChatService
from app.system.conversation.schema import CreateConversationRequest
from app.system.conversation.service import ConversationService

chat_router = APIRouter(prefix="/chat", tags=["chat"])

MAX_CONNECTIONS_PER_USER = 1

@chat_router.websocket("")
@inject
async def websocket_endpoint(
    websocket: WebSocket,
    user: Annotated[UserResponse, Depends(get_current_user_websocket)],
    agent_graph: AgentGraph = Depends(Provide[Container.agent_graph]),
    chat_service: ChatService = Depends(Provide[Container.chat_service]),
    logger: Logger = Depends(Provide[Container.logger]),
    redis_service: RedisClient = Depends(Provide[Container.redis_client]),
    conversation_service: ConversationService = Depends(Provide[Container.conversation_service]),
) -> None:
    connection_counted = False
    queue_bucket: dict[str, asyncio.Queue] = {}

    try:
        connection_count = await redis_service.get_connection_count(user.id)
        if connection_count > 1:
            logger.warning(
                "Too many connections user_id=%s count=%d",
                user.id,
                connection_count,
            )
            await websocket.close(
              code=status.WS_1008_POLICY_VIOLATION,
              reason="Too many connections. Max connections per user is 1."
              )
            return

        await websocket.accept()
        await redis_service.incr_connection_count(user.id)
        connection_counted = True

        refreshed_token = getattr(websocket.state, "refreshed_token", None)
        if refreshed_token:
            await websocket.send_json({
                "type": "token_refresh",
                "token": refreshed_token,
            })

        await websocket.send_json({
            "type": "heartbeat",
            "message": "Ping",
        })

        while True:
            if not await redis_service.exists(f"auth_{user.id}"):
                logger.info(
                    "WebSocket client not authenticated user_id=%s",
                    user.id,
                )
                await websocket.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Not authenticated",
                )
                return

            chat_task = asyncio.create_task(websocket.receive_json())

            done, pending = await asyncio.wait(
                {chat_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=80,
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            if chat_task in done:
                try:
                    message: dict[str, Any] = chat_task.result()
                    payload, error = chat_service.validate_websocket_message(
                        message,
                        user_id=user.id,
                    )
                    if error or not payload:
                        await websocket.send_json({
                            "type": "error",
                            "message": error or "Invalid message",
                        })
                        continue

                    query = payload["query"]
                    conversation_id = payload["conversation_id"]
                    document_ids = payload["document_ids"]
                    message_type = payload["type"]

                    if query == "ping":
                        await websocket.send_json({
                            "type": "heartbeat",
                            "message": "Pong",
                        })
                    else:
                        if not conversation_id:
                            conversation = await conversation_service.create(
                                CreateConversationRequest(title="New Conversation"),
                                user_id=user.id,
                            )
                            conversation_id = conversation.id
                            logger.info(
                                "Created conversation id=%s user_id=%s",
                                conversation_id,
                                user.id,
                            )
                        logger.info(
                            "Received message user_id=%s conversation_id=%s "
                            "type=%s document_ids=%s",
                            user.id,
                            conversation_id,
                            message_type,
                            document_ids,
                        )

                        queue = queue_bucket.get(conversation_id)
                        if queue is None:
                            queue = asyncio.Queue()
                            queue_bucket[conversation_id] = queue

                        lock_token = await redis_service.acquire_chat_lock(
                            user.id,
                            conversation_id,
                        )
                        if lock_token is None:
                            await websocket.send_json({
                                "type": "error",
                                "message": (
                                    "This conversation is already processing "
                                    "a message. Please wait."
                                ),
                            })
                            continue

                        try:
                            graph = agent_graph.start()
                            turn_error = await chat_service.handle_turn(
                                graph,
                                user_id=user.id,
                                conversation_id=conversation_id,
                                payload={
                                    **payload,
                                    "conversation_id": conversation_id,
                                },
                                queue=queue,
                            )
                            if turn_error:
                                await websocket.send_json({
                                    "type": "error",
                                    "message": turn_error,
                                })
                                continue

                            while True:
                                event = await queue.get()
                                if event is None:
                                    queue_bucket.pop(conversation_id, None)
                                    break
                                if not await _safe_send_json(
                                    websocket, {**event}
                                ):
                                    logger.info(
                                        "WebSocket disconnected during stream "
                                        "user_id=%s conversation_id=%s",
                                        user.id,
                                        conversation_id,
                                    )
                                    return
                        finally:
                            await redis_service.release_chat_lock(
                                user.id,
                                conversation_id,
                                lock_token,
                            )
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid JSON message user_id=%s", user.id,
                    )
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON message",
                    })
                    continue
                except asyncio.TimeoutError:
                    logger.warning(
                        "Timeout error user_id=%s. Sending heartbeat.", user.id
                    )
                    await websocket.send_json({
                        "type": "heartbeat",
                        "message": "Ping",
                    })
                    continue
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected user_id=%s", user.id)
    except ConnectionError:
        logger.exception(
            "Redis connection error user_id=%s", user.id
        )
        await _safe_close(
            websocket,
            code=status.WS_1012_SERVICE_RESTART,
        )
    except Exception:
        logger.exception(
            "Unexpected error in websocket endpoint user_id=%s", user.id
        )
        await _safe_close(
            websocket,
            code=status.WS_1011_INTERNAL_ERROR,
            reason="Internal server error",
        )
    finally:
        if connection_counted:
            await redis_service.decr_connection_count(user.id)


async def _safe_send_json(websocket: WebSocket, data: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(data)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False
    except Exception:
        return False


async def _safe_close(
    websocket: WebSocket,
    *,
    code: int,
    reason: str = "",
) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except (WebSocketDisconnect, RuntimeError):
        pass
