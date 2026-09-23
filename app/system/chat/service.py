import asyncio
from asyncio import Queue
from logging import Logger
from typing import Any

from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph.state import CompiledStateGraph

from app.system.chat.model import ChatModel
from app.system.chat.repository import ChatRepository
from app.system.chat.schema import ChatResponse
from app.utils.continuation_key import (
    create_continuation_key,
    verify_continuation_key,
)

SAVE_MAX_ATTEMPTS = 3
MAX_PAYLOAD_SIZE = 64 * 1024
MESSAGE_ID_LENGTH = 36
WEBSOCKET_MESSAGE_TYPES = frozenset({"chat", "edit", "retry"})


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        logger: Logger,
        continuation_secret: str,
    ):
        self.repository = repository
        self.logger = logger
        self.continuation_secret = continuation_secret

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
        query_message_id, response_message_id, chat_id, checkpointer_id,
        continuation_key.

        Absence of ``continuation_key`` means a new request. When present, the
        key is verified and its chat_id / thread_id / checkpointer_id are used.
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
        continuation_key = message.get("continuation_key")
        chat_id = None
        checkpointer_id = None

        if continuation_key:
            verified = verify_continuation_key(
                continuation_key,
                self.continuation_secret,
            )
            if verified is None:
                self.logger.warning(
                    "Invalid continuation_key user_id=%s",
                    user_id,
                )
                return None, "Invalid continuation key"

            chat_id = verified["chat_id"]
            checkpointer_id = verified["checkpointer_id"]
            thread_id = verified["thread_id"]
            if conversation_id and conversation_id != thread_id:
                self.logger.warning(
                    "continuation_key thread mismatch user_id=%s "
                    "conversation_id=%s thread_id=%s",
                    user_id,
                    conversation_id,
                    thread_id,
                )
                return None, "continuation key does not match conversation"
            conversation_id = thread_id

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

        if message_type in ("edit", "retry") and not continuation_key:
            self.logger.warning(
                "Missing continuation_key for edit/retry user_id=%s",
                user_id,
            )
            return None, "continuation_key is required for edit and retry"

        return {
            "type": message_type,
            "query": query,
            "conversation_id": conversation_id,
            "document_ids": document_ids,
            "query_message_id": query_message_id,
            "response_message_id": response_message_id,
            "chat_id": chat_id,
            "checkpointer_id": checkpointer_id,
            "continuation_key": continuation_key,
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
                    continuation_key=record.continuation_key,
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

    async def update_continuation_key(
        self,
        *,
        chat_id: str,
        continuation_key: str,
        user_id: str,
    ) -> None:
        try:
            await self.repository.update_continuation_key(
                chat_id,
                continuation_key,
                user_id,
            )
        except Exception:
            self.logger.exception(
                "Failed to update continuation_key chat_id=%s user_id=%s",
                chat_id,
                user_id,
            )

    async def apply_edit(
        self,
        graph: CompiledStateGraph,
        *,
        conversation_id: str,
        query: str,
        document_ids: list[str],
        query_message_id: str,
        checkpointer_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Update the human message by id and remove its following AI reply.

        Returns ``(error, new_checkpointer_id)``. On success ``error`` is None and
        ``new_checkpointer_id`` is the branch tip after the edit.
        """
        configurable: dict[str, Any] = {"thread_id": conversation_id}
        if checkpointer_id:
            configurable["checkpoint_id"] = checkpointer_id
        config = {"configurable": configurable}
        snapshot = await graph.aget_state(config)
        messages = list((snapshot.values or {}).get("messages") or [])

        human_index = next(
            (
                i
                for i, message in enumerate(messages)
                if message.type == "human" and message.id == query_message_id
            ),
            None,
        )
        if human_index is None:
            self.logger.warning(
                "Edit failed: human message not found conversation_id=%s "
                "query_message_id=%s",
                conversation_id,
                query_message_id,
            )
            return "Human message not found", None

        human_message = messages[human_index]
        next_index = human_index + 1
        ai_message = (
            messages[next_index]
            if next_index < len(messages) and messages[next_index].type == "ai"
            else None
        )
        if ai_message is None:
            self.logger.warning(
                "Edit failed: no AI reply for human conversation_id=%s "
                "query_message_id=%s",
                conversation_id,
                query_message_id,
            )
            return "AI reply not found for this message", None

        new_config = await graph.aupdate_state(
            config,
            {
                "messages": [
                    HumanMessage(content=query, id=human_message.id),
                    RemoveMessage(id=ai_message.id),
                ],
                "query": query,
                "document_ids": document_ids,
            },
        )
        new_checkpointer_id = (
            (new_config or {})
            .get("configurable", {})
            .get("checkpoint_id")
        )
        self.logger.info(
            "Applied edit conversation_id=%s query_message_id=%s "
            "removed_ai_id=%s checkpointer_id=%s",
            conversation_id,
            query_message_id,
            ai_message.id,
            new_checkpointer_id,
        )
        return None, new_checkpointer_id

    async def run_graph(
        self,
        graph: CompiledStateGraph,
        config_dict: dict[str, Any],
        queue: Queue,
        input: dict[str, Any],
    ) -> None:
        thread_id = config_dict["conversation_id"]
        user_id = input["user_id"]
        checkpointer_id = config_dict.get("checkpointer_id")
        configurable: dict[str, Any] = {"thread_id": thread_id}
        if checkpointer_id:
            configurable["checkpoint_id"] = checkpointer_id
        config = {"configurable": configurable}
        pending_done: dict[str, Any] | None = None

        try:
            async for chunk in graph.astream(
                input=input,
                stream_mode="custom",
                config=config,
            ):
                if (
                    isinstance(chunk, dict)
                    and chunk.get("type") == "chat.done"
                ):
                    pending_done = chunk
                    continue
                await queue.put(chunk)

            if pending_done is not None:
                chat_id = pending_done.get("chat_id")
                continuation_key = None
                if chat_id:
                    continuation_key = await self._issue_continuation_key(
                        graph=graph,
                        chat_id=chat_id,
                        thread_id=thread_id,
                        user_id=user_id,
                    )
                if continuation_key:
                    pending_done = {
                        **pending_done,
                        "continuation_key": continuation_key,
                    }
                await queue.put(pending_done)
        except Exception:
            self.logger.exception(
                "Error running graph user_id=%s conversation_id=%s",
                user_id,
                thread_id,
            )
            await queue.put({
                "type": "chat.error",
                "message": "Error processing your request. Please try again",
                "conversation_id": thread_id,
            })
        finally:
            await queue.put(None)

    async def _issue_continuation_key(
        self,
        *,
        graph: CompiledStateGraph,
        chat_id: str,
        thread_id: str,
        user_id: str,
    ) -> str | None:
        try:
            snapshot = await graph.aget_state({
                "configurable": {"thread_id": thread_id},
            })
            checkpointer_id = (
                (snapshot.config or {})
                .get("configurable", {})
                .get("checkpoint_id")
            )
            if not checkpointer_id:
                self.logger.warning(
                    "No checkpoint_id after graph done chat_id=%s "
                    "thread_id=%s started_from=%s",
                    chat_id,
                    thread_id,
                    checkpointer_id,
                )
                return None

            continuation_key = create_continuation_key(
                chat_id=chat_id,
                thread_id=thread_id,
                checkpointer_id=checkpointer_id,
                secret=self.continuation_secret,
            )
            asyncio.create_task(
                self.update_continuation_key(
                    chat_id=chat_id,
                    continuation_key=continuation_key,
                    user_id=user_id,
                )
            )
            self.logger.info(
                "Issued continuation_key chat_id=%s thread_id=%s "
                "checkpointer_id=%s started_from=%s",
                chat_id,
                thread_id,
                checkpointer_id,
                checkpointer_id,
            )
            return continuation_key
        except Exception:
            self.logger.exception(
                "Failed to issue continuation_key chat_id=%s thread_id=%s",
                chat_id,
                thread_id,
            )
            return None
