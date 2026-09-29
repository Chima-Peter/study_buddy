import asyncio
from asyncio import Queue, Task
from datetime import datetime, timezone
from logging import Logger
from typing import Any

from app.core.redis import RedisClient
import uuid_utils
from fastapi import WebSocket, WebSocketDisconnect, status
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.state import CompiledStateGraph

from app.system.chat.model import ChatModel
from app.system.chat.repository import (
    DEFAULT_SUBSEQUENT_LIMIT,
    ChatRepository,
)
from app.system.chat.schema import ChatResponse
from app.utils.continuation_key import (
    create_continuation_key,
    verify_continuation_key,
)

SAVE_MAX_ATTEMPTS = 3
MAX_PAYLOAD_SIZE = 64 * 1024
MESSAGE_ID_LENGTH = 36
WEBSOCKET_MESSAGE_TYPES = frozenset({"chat", "edit", "retry"})
CHAT_QUEUED = "queued"


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        logger: Logger,
        redis: RedisClient,
        continuation_secret: str,
    ):
        self.repository = repository
        self.logger = logger
        self.continuation_secret = continuation_secret
        self.redis = redis

    def start_drain(
        self,
        websocket: WebSocket,
        queue: Queue,
    ) -> Task[None]:
        """Start a single connection-scoped drain task."""
        return asyncio.create_task(
            self._drain_websocket(websocket, queue),
            name="chat_ws_drain",
        )

    async def stop_drain(
        self,
        queue: Queue,
        drain_task: Task[None] | None,
    ) -> None:
        """Signal the drain to stop and wait for it."""
        if drain_task is None:
            return
        await queue.put(None)
        try:
            await drain_task
        except asyncio.CancelledError:
            pass

    async def _drain_websocket(
        self,
        websocket: WebSocket,
        queue: Queue,
    ) -> None:
        """Send outbound events until ``None`` or an error closes the socket."""
        while True:
            event = await queue.get()
            if event is None:
                return

            if not isinstance(event, dict):
                self.logger.warning(
                    "Ignoring non-dict drain event type=%s",
                    type(event).__name__,
                )
                continue

            if not await self._safe_send_json(websocket, event):
                self.logger.info("WebSocket send failed during drain; closing")
                await self._safe_close(
                    websocket,
                    code=status.WS_1011_INTERNAL_ERROR,
                    reason="Send failed",
                )
                return

    @staticmethod
    async def _safe_send_json(
        websocket: WebSocket,
        data: dict[str, Any],
    ) -> bool:
        try:
            await websocket.send_json(data)
            return True
        except (WebSocketDisconnect, RuntimeError):
            return False
        except Exception:
            return False

    async def close_websocket(
        self,
        websocket: WebSocket,
        *,
        code: int,
        reason: str = "",
    ) -> None:
        await self._safe_close(websocket, code=code, reason=reason)

    @staticmethod
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

    @staticmethod
    def _event_with_request_id(
        event: dict[str, Any],
        request_id: str | None,
    ) -> dict[str, Any]:
        if not request_id or "request_id" in event:
            return event
        return {**event, "request_id": request_id}

    def validate_websocket_message(
        self,
        message: Any,
        *,
        user_id: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Validate and normalize a websocket chat payload.

        Returns (payload, None) on success or (None, error_message) on failure.
        Payload keys: type, query, conversation_id, document_id,
        query_message_id, response_message_id, chat_id, checkpointer_id,
        continuation_key.

        Absence of ``continuation_key`` means a new request. When present, the
        key is verified and its chat_id / thread_id / checkpointer_id /
        query_message_id / response_message_id are used.
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
            }, None

        request_id = message.get("request_id")
        if request_id is None or not isinstance(request_id, str):
            self.logger.warning(
                "Invalid request_id in message user_id=%s value=%r",
                user_id,
                request_id,
            )
            return None, "Invalid request_id in message"

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
        document_id = message.get("document_id")
        if not document_id:
            return None, "document_id is required for chat"
        if not isinstance(document_id, str) or not document_id.strip():
            return None, "document_id is required for chat"
        document_id = document_id.strip()

        continuation_key = message.get("continuation_key")
        chat_id = None
        checkpointer_id = None
        query_message_id = None
        response_message_id = None

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
            query_message_id = verified["query_message_id"]
            response_message_id = verified["response_message_id"]
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

        if message_type in ("edit", "retry") and not continuation_key:
            self.logger.warning(
                "Missing continuation_key for edit/retry user_id=%s",
                user_id,
            )
            return None, "continuation_key is required for edit and retry"

        if message_type in ("edit", "retry"):
            if not self._is_valid_message_id(query_message_id):
                self.logger.warning(
                    "Invalid query_message_id for %s user_id=%s value=%r",
                    message_type,
                    user_id,
                    query_message_id,
                )
                return None, "continuation key missing query_message_id"
            if not self._is_valid_message_id(response_message_id):
                self.logger.warning(
                    "Invalid response_message_id for %s user_id=%s value=%r",
                    message_type,
                    user_id,
                    response_message_id,
                )
                return None, "continuation key missing response_message_id"

        return {
            "type": message_type,
            "query": query,
            "conversation_id": conversation_id,
            "document_id": document_id,
            "query_message_id": query_message_id,
            "response_message_id": response_message_id,
            "chat_id": chat_id,
            "checkpointer_id": checkpointer_id,
            "continuation_key": continuation_key,
            "user_id": user_id,
            "request_id": request_id,
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
        chat_id: str | None = None,
        continuation_key: str | None = None,
    ) -> ChatResponse | None:
        """Create a new chat turn."""
        create_fields: dict[str, Any] = {
            "conversation_id": conversation_id,
            "query": query,
            "chat": response,
            "query_message_id": query_message_id,
            "response_message_id": response_message_id,
            "audit": {"source": source},
            "continuation_key": continuation_key,
        }
        if chat_id:
            create_fields["id"] = chat_id
        record = ChatModel(**create_fields)

        for attempt in range(1, SAVE_MAX_ATTEMPTS + 1):
            try:
                await self.repository.create(record, user_id)
                self.logger.info(
                    "Chat saved successfully chat_id=%s user_id=%s",
                    record.id,
                    user_id,
                )
                return self._to_response(record)
            except Exception:
                self.logger.exception(
                    "Chat save failed user_id=%s chat_id=%s attempt=%s/%s",
                    user_id,
                    record.id,
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                )
        self.logger.error(
            "Chat save failed after %s attempts user_id=%s chat_id=%s",
            SAVE_MAX_ATTEMPTS,
            user_id,
            record.id,
        )
        return None

    async def replace_turn(
        self,
        *,
        chat_id: str,
        user_id: str,
        query: str,
        response: str,
        source: list[dict[str, Any]],
        query_message_id: str | None = None,
        response_message_id: str | None = None,
    ) -> ChatResponse | None:
        """Overwrite an existing chat turn (edit/retry)."""
        for attempt in range(1, SAVE_MAX_ATTEMPTS + 1):
            try:
                record = await self.repository.update_turn(
                    chat_id,
                    user_id,
                    query=query,
                    response=response,
                    query_message_id=query_message_id,
                    response_message_id=response_message_id,
                    audit={"source": source},
                )
                if record is None:
                    self.logger.error(
                        "Chat replace failed: not found chat_id=%s user_id=%s",
                        chat_id,
                        user_id,
                    )
                    return None
                self.logger.info(
                    "Chat replaced successfully chat_id=%s user_id=%s",
                    chat_id,
                    user_id,
                )
                return self._to_response(record)
            except Exception:
                self.logger.exception(
                    "Chat replace failed user_id=%s chat_id=%s attempt=%s/%s",
                    user_id,
                    chat_id,
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                )
        self.logger.error(
            "Chat replace failed after %s attempts user_id=%s chat_id=%s",
            SAVE_MAX_ATTEMPTS,
            user_id,
            chat_id,
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

    async def delete_chats_after(
        self,
        *,
        chat_id: str,
        user_id: str,
    ) -> None:
        """Delete chats after ``chat_id`` (keeps ``chat_id`` itself)."""
        for attempt in range(1, SAVE_MAX_ATTEMPTS + 1):
            try:
                anchor = await self.repository.get(chat_id, user_id)
                if anchor is None:
                    self.logger.warning(
                        "delete_chats_after: chat not found "
                        "chat_id=%s user_id=%s",
                        chat_id,
                        user_id,
                    )
                    return

                started_at = datetime.now(timezone.utc)
                cursor = chat_id
                total_deleted = 0

                while True:
                    page, next_cursor, has_more = (
                        await self.repository.list_subsequent(
                            anchor.conversation_id,
                            cursor=cursor,
                            before_created_at=started_at,
                            limit=DEFAULT_SUBSEQUENT_LIMIT,
                        )
                    )
                    if page:
                        total_deleted += await self.repository.delete_by_ids(
                            [chat.id for chat in page]
                        )

                    if not has_more or next_cursor is None:
                        break
                    cursor = next_cursor

                self.logger.info(
                    "delete_chats_after completed chat_id=%s user_id=%s "
                    "conversation_id=%s deleted=%s",
                    chat_id,
                    user_id,
                    anchor.conversation_id,
                    total_deleted,
                )
                return
            except Exception:
                self.logger.exception(
                    "delete_chats_after failed chat_id=%s user_id=%s "
                    "attempt=%s/%s",
                    chat_id,
                    user_id,
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                )
        self.logger.error(
            "delete_chats_after failed after %s attempts "
            "chat_id=%s user_id=%s",
            SAVE_MAX_ATTEMPTS,
            chat_id,
            user_id,
        )

    async def branch(
        self,
        graph: CompiledStateGraph,
        *,
        user_id: str,
        payload: dict[str, str],
        new_conversation_id: str,
    ) -> ChatResponse:
        """Seed a new thread from a verified turn payload and persist its chat.

        ``payload`` must include ``thread_id``, ``checkpointer_id``, ``chat_id``,
        ``query_message_id``, and ``response_message_id``. Loads that turn,
        writes fresh messages into the new thread, creates the chat row, and
        returns it with a new continuation key.
        """
        source_thread_id = payload["thread_id"]
        checkpointer_id = payload["checkpointer_id"]
        query_message_id = payload["query_message_id"]
        response_message_id = payload["response_message_id"]
        source_chat_id = payload["chat_id"]

        source_chat = await self.repository.get(source_chat_id, user_id)
        if source_chat is None:
            self.logger.warning(
                "Branch failed: source chat not found chat_id=%s user_id=%s",
                source_chat_id,
                user_id,
            )
            raise ValueError("Conversation not found")
        if source_chat.conversation_id != source_thread_id:
            self.logger.warning(
                "Branch failed: chat/thread mismatch chat_id=%s "
                "conversation_id=%s thread_id=%s",
                source_chat_id,
                source_chat.conversation_id,
                source_thread_id,
            )
            raise ValueError("Invalid branch payload")

        source_config = {
            "configurable": {
                "thread_id": source_thread_id,
                "checkpoint_id": checkpointer_id,
            },
        }
        snapshot = await graph.aget_state(source_config)
        messages = list((snapshot.values or {}).get("messages") or [])

        human_message, ai_message = self._find_turn_messages(
            messages,
            query_message_id=query_message_id,
            response_message_id=response_message_id,
        )
        if human_message is None or ai_message is None:
            self.logger.warning(
                "Branch failed: turn not found thread_id=%s "
                "query_message_id=%s response_message_id=%s",
                source_thread_id,
                query_message_id,
                response_message_id,
            )
            raise ValueError("Turn not found in checkpoint")

        query = str(human_message.content)
        response = str(ai_message.content)
        source = list((source_chat.audit or {}).get("source") or [])

        new_thread_config = {"configurable": {"thread_id": new_conversation_id}}
        new_config = await graph.aupdate_state(
            new_thread_config,
            {
                "messages": [
                    HumanMessage(content=query),
                    AIMessage(content=response),
                ],
                "query": query,
                "response": response,
                "conversation_id": new_conversation_id,
                "user_id": user_id,
                "document_id": (snapshot.values or {}).get("document_id"),
            },
        )
        new_checkpointer_id = (
            (new_config or {})
            .get("configurable", {})
            .get("checkpoint_id")
        )
        if not new_checkpointer_id:
            self.logger.error(
                "Branch failed: no checkpoint_id after seed "
                "new_conversation_id=%s",
                new_conversation_id,
            )
            raise ValueError("Failed to seed branched conversation")

        branched_snapshot = await graph.aget_state(new_thread_config)
        branched_messages = list(
            (branched_snapshot.values or {}).get("messages") or []
        )
        new_query_message_id = None
        new_response_message_id = None
        for message in reversed(branched_messages):
            if new_response_message_id is None and message.type == "ai":
                new_response_message_id = message.id
            elif new_query_message_id is None and message.type == "human":
                new_query_message_id = message.id
            if new_query_message_id and new_response_message_id:
                break
        if not new_query_message_id or not new_response_message_id:
            self.logger.error(
                "Branch failed: missing message ids after seed "
                "new_conversation_id=%s",
                new_conversation_id,
            )
            raise ValueError("Failed to seed branched conversation")

        new_chat_id = str(uuid_utils.uuid7())
        new_continuation_key = create_continuation_key(
            chat_id=new_chat_id,
            thread_id=new_conversation_id,
            checkpointer_id=new_checkpointer_id,
            query_message_id=new_query_message_id,
            response_message_id=new_response_message_id,
            secret=self.continuation_secret,
        )
        chat = await self.save(
            user_id=user_id,
            conversation_id=new_conversation_id,
            query=query,
            response=response,
            source=source,
            query_message_id=new_query_message_id,
            response_message_id=new_response_message_id,
            chat_id=new_chat_id,
            continuation_key=new_continuation_key,
        )
        if chat is None:
            self.logger.error(
                "Branch failed: chat save failed new_conversation_id=%s "
                "user_id=%s",
                new_conversation_id,
                user_id,
            )
            raise ValueError("Failed to create branched chat")

        self.logger.info(
            "Branched turn source_thread=%s new_conversation_id=%s "
            "chat_id=%s checkpointer_id=%s",
            source_thread_id,
            new_conversation_id,
            chat.id,
            new_checkpointer_id,
        )
        return chat

    async def apply_edit(
        self,
        graph: CompiledStateGraph,
        *,
        conversation_id: str,
        query: str,
        document_id: str,
        query_message_id: str,
        response_message_id: str,
        checkpointer_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Update the human message by id and remove its AI reply.

        Returns ``(error, new_checkpointer_id)``. On success ``error`` is None and
        ``new_checkpointer_id`` is the branch tip after the edit.
        """
        configurable: dict[str, Any] = {"thread_id": conversation_id}
        if checkpointer_id:
            configurable["checkpoint_id"] = checkpointer_id
        config = {"configurable": configurable}
        snapshot = await graph.aget_state(config)
        messages = list((snapshot.values or {}).get("messages") or [])

        human_message, ai_message = self._find_turn_messages(
            messages,
            query_message_id=query_message_id,
            response_message_id=response_message_id,
        )
        if human_message is None:
            self.logger.warning(
                "Edit failed: human message not found conversation_id=%s "
                "query_message_id=%s",
                conversation_id,
                query_message_id,
            )
            return "Human message not found", None

        if ai_message is None:
            self.logger.info(
                "Edit: AI reply missing, continuing conversation_id=%s "
                "response_message_id=%s",
                conversation_id,
                response_message_id,
            )

        message_updates: list[Any] = [
            HumanMessage(content=query, id=human_message.id),
        ]
        if ai_message is not None:
            message_updates.append(RemoveMessage(id=ai_message.id))

        new_config = await graph.aupdate_state(
            config,
            {
                "messages": message_updates,
                "query": query,
                "document_id": document_id,
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
            ai_message.id if ai_message is not None else None,
            new_checkpointer_id,
        )
        return None, new_checkpointer_id

    async def apply_retry(
        self,
        graph: CompiledStateGraph,
        *,
        conversation_id: str,
        query: str,
        document_id: str,
        query_message_id: str,
        response_message_id: str,
        checkpointer_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Remove the AI message by id so the graph can regenerate it.

        Returns ``(error, new_checkpointer_id)``. On success ``error`` is None and
        ``new_checkpointer_id`` is the branch tip after the retry fork.
        """
        configurable: dict[str, Any] = {"thread_id": conversation_id}
        if checkpointer_id:
            configurable["checkpoint_id"] = checkpointer_id
        config = {"configurable": configurable}
        snapshot = await graph.aget_state(config)
        messages = list((snapshot.values or {}).get("messages") or [])

        human_message, ai_message = self._find_turn_messages(
            messages,
            query_message_id=query_message_id,
            response_message_id=response_message_id,
        )
        if human_message is None:
            self.logger.warning(
                "Retry failed: human message not found conversation_id=%s "
                "query_message_id=%s",
                conversation_id,
                query_message_id,
            )
            return "Human message not found", None

        if ai_message is None:
            self.logger.info(
                "Retry: AI reply missing, continuing conversation_id=%s "
                "response_message_id=%s",
                conversation_id,
                response_message_id,
            )

        state_update: dict[str, Any] = {
            "query": query,
            "document_id": document_id,
        }
        if ai_message is not None:
            state_update["messages"] = [RemoveMessage(id=ai_message.id)]

        new_config = await graph.aupdate_state(config, state_update)
        new_checkpointer_id = (
            (new_config or {})
            .get("configurable", {})
            .get("checkpoint_id")
        )
        self.logger.info(
            "Applied retry conversation_id=%s query_message_id=%s "
            "response_message_id=%s checkpointer_id=%s",
            conversation_id,
            query_message_id,
            response_message_id,
            new_checkpointer_id,
        )
        return None, new_checkpointer_id

    async def handle_chat_queue(
        self,
        graph: CompiledStateGraph,
        *,
        payload: dict[str, Any],
        queue: Queue,
    ) -> str | None:
        """Dispatch a chat payload; chat type uses Redis arrival/completion.

        Returns ``CHAT_QUEUED`` if the chat was enqueued, an error message on
        failure, or None on success.
        """
        message_type = payload["type"]
        if message_type in ("edit", "retry"):
            turn_error = await self.handle_retry_and_edit_turns(
                graph,
                payload=payload,
                queue=queue,
            )
            if turn_error:
                await queue.put(
                    self._event_with_request_id(
                        {
                            "type": "error",
                            "message": turn_error,
                            "conversation_id": payload.get("conversation_id"),
                        },
                        payload.get("request_id"),
                    )
                )
            return turn_error

        user_id = payload["user_id"]
        conversation_id = payload["conversation_id"]
        request_id = payload["request_id"]
        lock_key, queue_key, items_key = self._chat_queue_keys(
            user_id,
            conversation_id,
        )

        acquired = await self.redis.arrival(
            lock_key=lock_key,
            queue_key=queue_key,
            items_key=items_key,
            item_id=request_id,
            item=payload,
        )
        if not acquired:
            self.logger.info(
                "Chat turn enqueued user_id=%s conversation_id=%s "
                "request_id=%s",
                user_id,
                conversation_id,
                request_id,
            )
            return CHAT_QUEUED

        current: dict[str, Any] | None = payload
        lock_token = request_id
        while current is not None:
            checkpointer_id: str | None = None
            checkpointer_id = await self.handle_chat_turns(
                graph,
                payload=current,
                queue=queue,
            )

            next_payload = await self.redis.completion(
                lock_key=lock_key,
                queue_key=queue_key,
                items_key=items_key,
                lock_token=lock_token,
            )
            if next_payload is None:
                return None
            next_payload["checkpointer_id"] = checkpointer_id
            current = next_payload
            lock_token = next_payload["request_id"]
        
    async def handle_retry_and_edit_turns(
        self,
        graph: CompiledStateGraph,
        *,
        payload: dict[str, Any],
        queue: Queue,
    ) -> str | None:
        """
            Handle retry and edit.

            Returns an error message on failure, or None on success.
        """
        
        user_id = payload["user_id"]
        conversation_id = payload["conversation_id"]
        query = payload["query"]
        document_id = payload["document_id"]
        message_type = payload["type"]
        checkpointer_id = payload.get("checkpointer_id")
        fork_chat_id: str | None = None

        graph_input: dict[str, Any] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query": query,
            "document_id": document_id,
            "turn_type": message_type,
            "fork_chat_id": None,
        }

        if message_type == "edit":
            edit_error, checkpointer_id = await self.apply_edit(
                graph,
                conversation_id=conversation_id,
                query=query,
                document_id=document_id,
                query_message_id=payload["query_message_id"],
                response_message_id=payload["response_message_id"],
                checkpointer_id=checkpointer_id,
            )
            if edit_error:
                return edit_error
            fork_chat_id = payload.get("chat_id")
        elif message_type == "retry":
            retry_error, checkpointer_id = await self.apply_retry(
                graph,
                conversation_id=conversation_id,
                query=query,
                document_id=document_id,
                query_message_id=payload["query_message_id"],
                response_message_id=payload["response_message_id"],
                checkpointer_id=checkpointer_id,
            )
            if retry_error:
                return retry_error
            fork_chat_id = payload.get("chat_id")

        if fork_chat_id:
            graph_input["fork_chat_id"] = fork_chat_id
            asyncio.create_task(
                self.delete_chats_after(
                    chat_id=fork_chat_id,
                    user_id=user_id,
                )
            )

        await self.run_graph(
            graph,
            {
                "conversation_id": conversation_id,
                "checkpointer_id": checkpointer_id,
                "request_id": payload.get("request_id"),
            },
            queue,
            graph_input,
        )
        return None

    async def handle_chat_turns(
        self,
        graph: CompiledStateGraph,
        *,
        payload: dict[str, Any],
        queue: Queue,
    ) -> str | None:
        """Run ``run_graph`` for a new chat turn.

        Returns the latest checkpointer_id after the turn, or None.
        """
        message_type = payload["type"]
        query = payload["query"]
        document_id = payload["document_id"]
        checkpointer_id = payload.get("checkpointer_id")
        user_id = payload["user_id"]
        conversation_id = payload["conversation_id"]
        request_id = payload.get("request_id")

        graph_input: dict[str, Any] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query": query,
            "document_id": document_id,
            "turn_type": message_type,
            "fork_chat_id": None,
            "messages": [HumanMessage(content=query)],
        }

        try:
            return await self.run_graph(
                graph,
                {
                    "conversation_id": conversation_id,
                    "checkpointer_id": checkpointer_id,
                    "request_id": request_id,
                },
                queue,
                graph_input,
            )
        except Exception:
            self.logger.exception(
                "Error running graph user_id=%s conversation_id=%s",
                user_id,
                conversation_id,
            )
            await queue.put(
                self._event_with_request_id(
                    {
                        "type": "chat.error",
                        "message": (
                            "Error processing your request. Please try again"
                        ),
                        "conversation_id": conversation_id,
                    },
                    request_id,
                )
            )
            chat_id = payload.get("chat_id")
            if chat_id:
                await self.delete_chats_after(
                    chat_id=chat_id,
                    user_id=user_id,
                )
            return checkpointer_id

    async def run_graph(
        self,
        graph: CompiledStateGraph,
        config_dict: dict[str, Any],
        queue: Queue,
        input: dict[str, Any],
    ) -> str | None:
        thread_id = config_dict["conversation_id"]
        user_id = input["user_id"]
        checkpointer_id = config_dict.get("checkpointer_id")
        request_id = config_dict.get("request_id")
        configurable: dict[str, Any] = {"thread_id": thread_id}
        if checkpointer_id:
            configurable["checkpoint_id"] = checkpointer_id
        config = {"configurable": configurable}
        pending_done: dict[str, Any] | None = None
        latest_checkpointer_id: str | None = None

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
                if isinstance(chunk, dict):
                    await queue.put(
                        self._event_with_request_id(chunk, request_id)
                    )
                else:
                    await queue.put(chunk)

            if pending_done is not None:
                chat_id = pending_done.get("chat_id")
                continuation_key = None
                if chat_id:
                    (
                        continuation_key,
                        latest_checkpointer_id,
                    ) = await self._issue_continuation_key(
                        graph=graph,
                        chat_id=chat_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        query_message_id=pending_done.get("query_message_id"),
                        response_message_id=pending_done.get(
                            "response_message_id"
                        ),
                    )
                if continuation_key:
                    pending_done = {
                        **pending_done,
                        "continuation_key": continuation_key,
                    }
                await queue.put(
                    self._event_with_request_id(pending_done, request_id)
                )
        except Exception:
            self.logger.exception(
                "Error running graph user_id=%s conversation_id=%s",
                user_id,
                thread_id,
            )
            raise
        return latest_checkpointer_id

    async def _issue_continuation_key(
        self,
        *,
        graph: CompiledStateGraph,
        chat_id: str,
        thread_id: str,
        user_id: str,
        query_message_id: str | None,
        response_message_id: str | None,
    ) -> tuple[str | None, str | None]:
        try:
            if not query_message_id or not response_message_id:
                self.logger.warning(
                    "Missing message ids for continuation_key chat_id=%s "
                    "thread_id=%s query_message_id=%r response_message_id=%r",
                    chat_id,
                    thread_id,
                    query_message_id,
                    response_message_id,
                )
                return None, None

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
                    "thread_id=%s",
                    chat_id,
                    thread_id,
                )
                return None, None

            continuation_key = create_continuation_key(
                chat_id=chat_id,
                thread_id=thread_id,
                checkpointer_id=checkpointer_id,
                query_message_id=query_message_id,
                response_message_id=response_message_id,
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
                "checkpointer_id=%s query_message_id=%s "
                "response_message_id=%s",
                chat_id,
                thread_id,
                checkpointer_id,
                query_message_id,
                response_message_id,
            )
            return continuation_key, checkpointer_id
        except Exception:
            self.logger.exception(
                "Failed to issue continuation_key chat_id=%s thread_id=%s",
                chat_id,
                thread_id,
            )
            return None, None

    @staticmethod
    def _is_valid_message_id(value: Any) -> bool:
        return isinstance(value, str) and len(value) == MESSAGE_ID_LENGTH

    @staticmethod
    def _find_turn_messages(
        messages: list[Any],
        *,
        query_message_id: str,
        response_message_id: str,
    ) -> tuple[Any | None, Any | None]:
        human_message = None
        ai_message = None
        for message in messages:
            if message.type == "human" and message.id == query_message_id:
                human_message = message
            elif message.type == "ai" and message.id == response_message_id:
                ai_message = message
            if human_message is not None and ai_message is not None:
                break
        return human_message, ai_message

    @staticmethod
    def _to_response(record: ChatModel) -> ChatResponse:
        return ChatResponse(
            id=record.id,
            conversation_id=record.conversation_id,
            query=record.query,
            response=record.chat,
            continuation_key=record.continuation_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _chat_queue_keys(user_id: str, conversation_id: str) -> tuple[str, str, str]:
        return (
            f"chat_lock:{user_id}:{conversation_id}",
            f"chat_queue:{user_id}:{conversation_id}",
            f"chat_items:{user_id}:{conversation_id}",
        )

