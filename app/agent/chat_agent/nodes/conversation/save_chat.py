from logging import Logger

from langgraph.config import get_stream_writer

from app.agent.chat_agent.state import AgentState
from app.system.chat.service import ChatService


class SaveChatNode:
    def __init__(self, chat_service: ChatService, logger: Logger):
        self.chat_service = chat_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        sources = [
            {
                "content": r.document.content,
                "metadata": r.document.metadata,
                "rrf_score": r.score,
            }
            for r in (state.get("rag_documents") or [])
        ]

        query_message_id = None
        response_message_id = None
        for message in reversed(state.get("messages") or []):
            if response_message_id is None and message.type == "ai":
                response_message_id = message.id
            elif query_message_id is None and message.type == "human":
                query_message_id = message.id
            if query_message_id and response_message_id:
                break

        self.logger.info(
            "Save chat node started id=%s user_id=%s sources=%s "
            "query_message_id=%s response_message_id=%s",
            state["conversation_id"],
            state["user_id"],
            len(sources),
            query_message_id,
            response_message_id,
        )
        chat = await self.chat_service.save(
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            query=state["query"],
            response=state["response"],
            source=sources,
            query_message_id=query_message_id,
            response_message_id=response_message_id,
        )

        writer = get_stream_writer()
        if chat is None:
            self.logger.warning(
                "Save chat node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            writer({
                "type": "chat.done",
                "conversation_id": state["conversation_id"],
                "query_message_id": query_message_id,
                "response_message_id": response_message_id,
            })
            return {}

        writer({
            "type": "chat.done",
            "chat_id": chat.id,
            "conversation_id": state["conversation_id"],
            "query_message_id": query_message_id,
            "response_message_id": response_message_id,
        })

        self.logger.info(
            "Save chat node completed id=%s user_id=%s chat_id=%s",
            state["conversation_id"],
            state["user_id"],
            chat.id,
        )
        return {}
