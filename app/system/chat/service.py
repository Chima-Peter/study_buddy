from asyncio import Queue
from logging import Logger
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.system.chat.model import ChatModel
from app.system.chat.repository import ChatRepository
from app.system.chat.schema import ChatResponse

SAVE_MAX_ATTEMPTS = 3
MAX_PAYLOAD_SIZE = 64 * 1024
MESSAGE_ID_LENGTH = 36
WEBSOCKET_MESSAGE_TYPES = frozenset({"chat", "edit", "retry"})


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        logger: Logger,
    ):
        self.repository = repository
        self.logger = logger

    @staticmethod
    def _is_valid_message_id(value: Any) -> bool:
        return isinstance(value, str) and len(value) == MESSAGE_ID_LENGTH

    def validate_websocket_message(
        self,
        message: Any,
        *,
        user_id: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Validate and normalize a websocket chat payload.

        Returns (payload, None) on success or (None, error_message) on failure.
        Payload keys: type, query, conversation_id, document_ids,
        query_message_id, response_message_id.
        """
        if isinstance(message, str):
            self.logger.warning(
                "Message is not a JSON object user_id=%s",
                user_id,
            )
            return None, "Message is not a JSON object"

        if not isinstance(message, dict):
            self.logger.warning(
                "Message is not a JSON object user_id=%s",
                user_id,
            )
            return None, "Message is not a JSON object"

        query = message.get("query")
        if query == "ping":
            return {
                "type": None,
                "query": "ping",
                "conversation_id": None,
                "document_ids": None,
            }, None

        message_type = message.get("type")
        if message_type not in WEBSOCKET_MESSAGE_TYPES:
            self.logger.warning(
                "Invalid message type user_id=%s type=%s",
                user_id,
                message_type,
            )
            return None, "type must be one of: chat, edit, retry"

        if not query:
            self.logger.warning(
                "No query in message user_id=%s",
                user_id,
            )
            return None, "No query in message"

        if len(query.encode("utf-8")) > MAX_PAYLOAD_SIZE:
            self.logger.warning(
                "Query too big user_id=%s size=%d",
                user_id,
                len(query),
            )
            return None, "Query too big"

        conversation_id = message.get("conversation_id")
        document_ids = message.get("document_ids")
        if document_ids is None and message.get("document_id"):
            if isinstance(message.get("document_id"), str):
                document_ids = [message.get("document_id")]
            else:
                document_ids = message.get("document_id")
        if isinstance(document_ids, str):
            document_ids = [document_ids]
        if not document_ids:
            return None, "At least one document is required for chat."

        query_message_id = message.get("query_message_id")
        response_message_id = message.get("response_message_id")

        if message_type == "edit" and not self._is_valid_message_id(query_message_id):
            self.logger.warning(
                "Invalid query_message_id for edit user_id=%s value=%r",
                user_id,
                query_message_id,
            )
            return None, "query_message_id must be a valid message id"

        if message_type == "retry" and not self._is_valid_message_id(
            response_message_id
        ):
            self.logger.warning(
                "Invalid response_message_id for retry user_id=%s value=%r",
                user_id,
                response_message_id,
            )
            return None, "response_message_id must be a valid message id"

        return {
            "type": message_type,
            "query": query,
            "conversation_id": conversation_id,
            "document_ids": document_ids,
            "query_message_id": query_message_id,
            "response_message_id": response_message_id,
        }, None

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
