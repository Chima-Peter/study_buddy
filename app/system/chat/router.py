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
from app.utils.llm import is_rate_limit_error
from app.core.redis import RedisClient
from app.core.security import get_current_user_websocket
from app.system.conversation.schema import CreateConversationRequest
from app.system.conversation.service import ConversationService

chat_router = APIRouter(prefix="/chat", tags=["chat"])

MAX_PAYLOAD_SIZE = 64 * 1024
MAX_CONNECTIONS_PER_USER = 1

@chat_router.websocket("")
@inject
async def websocket_endpoint(
    websocket: WebSocket,
    user: Annotated[UserResponse, Depends(get_current_user_websocket)],
    agent_graph: AgentGraph = Depends(Provide[Container.agent_graph]),
    logger: Logger = Depends(Provide[Container.logger]),
    redis_service: RedisClient = Depends(Provide[Container.redis_client]),
    conversation_service: ConversationService = Depends(Provide[Container.conversation_service]),
) -> None:
    connection_counted = False

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
              reason="Too many connections. Max connections per user is 5."
              )
            return

        await websocket.accept()
        await redis_service.incr_connection_count(user.id)
        connection_counted = True
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
                    first_message = False
                    message: dict[str, Any] = chat_task.result()
                    if isinstance(message, str):
                        logger.warning(
                            "Message is not a JSON object user_id=%s",
                            user.id,
                        )
                        await websocket.send_json({
                            "type": "error",
                            "message": "Message is not a JSON object",
                        })
                        continue

                    query = message.get("query")
                    if not query:
                        logger.warning(
                            "No query in message user_id=%s",
                            user.id,
                        )
                        await websocket.send_json({
                            "type": "error",
                            "message": "No query in message",
                        })
                        continue

                    if len(query.encode("utf-8")) > MAX_PAYLOAD_SIZE:
                        logger.warning(
                            "Query too big user_id=%s size=%d",
                            user.id,
                            len(query),
                        )
                        await websocket.send_json({
                            "type": "error",
                            "message": "Query too big",
                        })
                        continue

                    conversation_id = message.get("conversation_id")
                    document_ids = message.get("document_ids")
                    if document_ids is None and message.get("document_id"):
                        document_ids = [message["document_id"]]
                    if isinstance(document_ids, str):
                        document_ids = [document_ids]
                    if not document_ids:
                        await websocket.send_json({
                            "type": "error",
                            "message": "At least one document is required for chat.",
                        })
                        continue

                    if query == "ping":
                        await websocket.send_json({
                            "type": "heartbeat",
                            "message": "Pong",
                        })
                    else:
                        if not conversation_id:
                            first_message = True
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
                            "document_ids=%s",
                            user.id,
                            conversation_id,
                            document_ids,
                        )
                        graph = agent_graph.start()
                        try:
                            async for chunk in graph.astream(
                                input={
                                    "user_id": user.id,
                                    "first_message": first_message,
                                    "conversation_id": conversation_id,
                                    "query": query,
                                    "conversation_summary": "",
                                    "title": "",
                                    "document_ids": document_ids,
                                },
                                stream_mode="custom",
                                config={
                                    "configurable": {
                                        "thread_id": conversation_id,
                                    }
                                }
                            ):
                                await websocket.send_json({
                                    "type": chunk["type"],
                                    "response": chunk["response"],
                                    "conversation_id": conversation_id,
                                })
                        except WebSocketDisconnect:
                            raise
                        except Exception as e:
                            if is_rate_limit_error(e):
                                logger.warning(
                                    "Agent graph rate limited user_id=%s",
                                    user.id,
                                )
                                error_message = (
                                    "Rate limit exceeded. Please try again shortly."
                                )
                            else:
                                logger.exception(
                                    "Error in agent graph user_id=%s", user.id
                                )
                                error_message = "Failed to generate response"
                            await _safe_send_json(websocket, {
                                "type": "chat.error",
                                "message": error_message,
                                "conversation_id": conversation_id,
                            })
                            continue
                        await websocket.send_json({
                            "type": "chat.done",
                            "conversation_id": conversation_id,
                        })
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
    except WebSocketDisconnect:
        raise
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