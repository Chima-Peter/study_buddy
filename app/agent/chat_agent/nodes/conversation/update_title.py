from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.config import get_stream_writer

from app.agent.chat_agent.prompts import title_prompt
from app.agent.chat_agent.state import AgentState
from app.system.schemas.conversation import UpdateConversationTitleRequest
from app.system.service.conversation import ConversationService


class UpdateConversationTitleNode:
    def __init__(
        self,
        conversation_service: ConversationService,
        model: ChatGoogleGenerativeAI,
        logger: Logger,
    ):
        self.conversation_service = conversation_service
        self.model = model
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Update title node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        prompt = title_prompt(state["query"], state["response"])
        title_response = await self.model.ainvoke(prompt)
        title = (title_response.text or "").strip().strip("\"'")[:255] or None
        if title is None:
            self.logger.warning(
                "Update title node produced empty title id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {"title": None}

        writer = get_stream_writer()
        writer({
            "type": "chat.title",
            "response": title,
        })

        await self.conversation_service.update_title(
            conversation_id=state["conversation_id"],
            user_id=state["user_id"],
            request=UpdateConversationTitleRequest(
                title=title,
            ),
        )

        self.logger.info(
            "Update title node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {"title": title}
