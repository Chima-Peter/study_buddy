from asyncio import Queue
from logging import Logger
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.system.chat.model import ChatModel
from app.system.chat.repository import ChatRepository
from app.system.chat.schema import ChatResponse

SAVE_MAX_ATTEMPTS = 3


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        logger: Logger,
    ):
        self.repository = repository
        self.logger = logger

    async def save(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
        response: str,
        source: list[dict[str, Any]],
        query_message_id: str | None = None,
        response_message_id: str | None = None,
    ) -> ChatResponse | None:
        record = ChatModel(
            conversation_id=conversation_id,
            query=query,
            chat=response,
            query_message_id=query_message_id,
            response_message_id=response_message_id,
            audit={
                "source": source,
            },
        )

        for attempt in range(1, SAVE_MAX_ATTEMPTS + 1):
            try:
                await self.repository.create(record, user_id)

                self.logger.info(
                    "Chat saved successfully user_id=%s",
                    user_id,
                )

                result = ChatResponse(
                    id=record.id,
                    conversation_id=record.conversation_id,
                    query=record.query,
                    response=record.chat,
                    query_message_id=record.query_message_id,
                    response_message_id=record.response_message_id,
                    created_at=record.created_at,
                )

                return result
            except Exception:
                self.logger.exception(
                    "Chat save failed user_id=%s attempt=%s/%s",
                    user_id,
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                )
        self.logger.error(
            "Chat save failed after %s attempts user_id=%s",
            SAVE_MAX_ATTEMPTS,
            user_id,
        )
        return None

    async def run_graph(
        self,
        graph: CompiledStateGraph,
        queue: Queue,
        input: dict[str, Any],
    ) -> None:
        try:
            async for chunk in graph.astream(
                input=input,
                stream_mode="custom",
                config={
                    "configurable": {
                        "thread_id": input["conversation_id"],
                    }
                },
            ):
                await queue.put(chunk)
        except Exception:
            self.logger.exception(
                "Error running graph user_id=%s conversation_id=%s",
                input["user_id"],
                input["conversation_id"],
            )
            await queue.put({
                "type": "chat.error",
                "message": "Error processing your request. Please try again",
                "conversation_id": input["conversation_id"],
            })
        finally:
            await queue.put(None)
