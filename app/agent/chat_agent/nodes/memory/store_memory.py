from logging import Logger

from app.agent.chat_agent.messages import format_history
from app.agent.chat_agent.schema import SUMMARY_EVERY
from app.agent.chat_agent.state import AgentState
from app.core.rabbitmq import RabbitMQ
from app.memory.schema import MemoryExtractRequest


class StoreMemoryNode:
    """Enqueue LLM memory extraction every SUMMARY_EVERY chats (async via RabbitMQ)."""

    def __init__(self, rabbitmq: RabbitMQ, logger: Logger):
        self.rabbitmq = rabbitmq
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state.get("is_academic_discussion", True):
            self.logger.info(
                "Store memory node skipped id=%s user_id=%s reason=non_academic",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        messages = state.get("messages") or []
        if not messages:
            self.logger.info(
                "Store memory node skipped id=%s user_id=%s reason=no_messages",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        context = format_history(messages, limit=SUMMARY_EVERY)
        known_memories = [
            memory.content for memory in (state.get("memories") or [])
        ]
        payload = MemoryExtractRequest(
            user_id=state["user_id"],
            context=context,
            conversation_id=state["conversation_id"],
            known_memories=known_memories,
        )
        self.logger.info(
            "Store memory node enqueue id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        try:
            await self.rabbitmq.publish_message(
                "memory_extract_queue",
                payload.model_dump(),
            )
        except Exception:
            self.logger.exception(
                "Store memory node enqueue failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Store memory node enqueued id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {}
