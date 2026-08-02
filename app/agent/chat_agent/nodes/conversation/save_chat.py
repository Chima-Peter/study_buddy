from logging import Logger

from app.agent.chat_agent.state import AgentState
from app.system.service.chat import ChatService


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
            for r in state["rag_documents"]
        ]
        self.logger.info(
            "Save chat node started id=%s user_id=%s sources=%s",
            state["conversation_id"],
            state["user_id"],
            len(sources),
        )
        chat = await self.chat_service.save(
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
            query=state["query"],
            response=state["response"],
            source=sources,
        )
        if chat is None:
            self.logger.warning(
                "Save chat node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Save chat node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        return {
            "conversation_history": [chat],
        }
