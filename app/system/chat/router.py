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
    out_queue: asyncio.Queue = asyncio.Queue()
    drain_task: asyncio.Task | None = None

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
        drain_task = chat_service.start_drain(websocket, out_queue)

        refreshed_token = getattr(websocket.state, "refreshed_token", None)
        if refreshed_token:
            await out_queue.put({
                "type": "token_refresh",
                "token": refreshed_token,
            })

        await out_queue.put({
            "type": "heartbeat",
            "message": "Ping",
        })

        while True:
            if drain_task.done():
                logger.info(
                    "WebSocket drain ended user_id=%s",
                    user.id,
                )
                return

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
                {chat_task, drain_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=80,
            )

            if drain_task in done:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                logger.info(
                    "WebSocket drain ended user_id=%s",
                    user.id,
                )
                return

            if chat_task not in done:
                for task in pending:
                    if task is not drain_task:
                        task.cancel()
                await asyncio.gather(
                    *[t for t in pending if t is not drain_task],
                    return_exceptions=True,
                )
                await out_queue.put({
                    "type": "heartbeat",
                    "message": "Ping",
                })
                continue

            try:
                message: dict[str, Any] = chat_task.result()
                payload, error = chat_service.validate_websocket_message(
                    message,
                    user_id=user.id,
                )
                if error or not payload:
                    await out_queue.put({
                        "type": "chat.error",
                        "message": error or "Invalid message",
                        "request_id": (
                            message.get("request_id")
                            if isinstance(message, dict)
                            else None
                        ),
                        "conversation_id": (
                            message.get("conversation_id")
                            if isinstance(message, dict)
                            else None
                        ),
                    })
                    continue

                query = payload["query"]
                conversation_id = payload.get("conversation_id")
                request_id = payload.get("request_id")

                if query == "ping":
                    await out_queue.put({
                        "type": "heartbeat",
                        "message": "Pong",
                    })
                    continue

                if conversation_id is None:
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
                    await out_queue.put({
                        "type": "chat.started",
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                    })

                logger.info(
                    "Received message user_id=%s conversation_id=%s "
                    "type=%s document_id=%s",
                    user.id,
                    conversation_id,
                    payload["type"],
                    payload["document_id"],
                )

                graph = agent_graph.start()
                asyncio.create_task(
                    chat_service.handle_chat_queue(
                        graph,
                        payload={
                            **payload,
                            "conversation_id": conversation_id,
                        },
                        queue=out_queue,
                    )
                )
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid JSON message user_id=%s", user.id,
                )
                await out_queue.put({
                    "type": "chat.error",
                    "message": "Invalid JSON message",
                })
                continue
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout error user_id=%s. Sending heartbeat.", user.id
                )
                await out_queue.put({
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
        await chat_service.close_websocket(
            websocket,
            code=status.WS_1012_SERVICE_RESTART,
        )
    except Exception:
        logger.exception(
            "Unexpected error in websocket endpoint user_id=%s", user.id
        )
        await chat_service.close_websocket(
            websocket,
            code=status.WS_1011_INTERNAL_ERROR,
            reason="Internal server error",
        )
    finally:
        await chat_service.stop_drain(out_queue, drain_task)
        if connection_counted:
            await redis_service.decr_connection_count(user.id)
