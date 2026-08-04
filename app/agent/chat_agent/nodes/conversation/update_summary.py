from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.chat_agent.prompts import summary_prompt
from app.agent.chat_agent.schema import SUMMARY_EVERY, SUMMARY_MAX_CHARS
from app.agent.chat_agent.state import AgentState
from app.utils.llm import is_rate_limit_error
from app.system.conversation.service import ConversationService


class UpdateConversationSummaryNode:
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
        conversation_history = state["conversation_history"]
        recent_exchanges = [
            f"User: {chat.query}\nAssistant: {chat.response[:200]}"
            for chat in conversation_history[-SUMMARY_EVERY:]
        ]

        self.logger.info(
            "Update summary node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        prompt = summary_prompt(state["conversation_summary"], recent_exchanges)
        try:
            summary_response = await self.model.ainvoke(prompt)
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Update summary node rate limited id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            else:
                self.logger.exception(
                    "Update summary node failed id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            return {}

        summary = (
            (summary_response.text or "").strip().strip("\"'")[:SUMMARY_MAX_CHARS]
            or state["conversation_summary"]
        )

        await self.conversation_service.update_summary(
            conversation_id=state["conversation_id"],
            user_id=state["user_id"],
            summary=summary,
        )
        self.logger.info(
            "Update summary node completed id=%s user_id=%s summary_chars=%s",
            state["conversation_id"],
            state["user_id"],
            len(summary),
        )
        return {"conversation_summary": summary}
