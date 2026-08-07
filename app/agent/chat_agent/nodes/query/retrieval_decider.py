from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.chat_agent.prompts import retrieval_decider_prompt
from app.agent.chat_agent.schema import DeciderResponse
from app.agent.chat_agent.state import AgentState
from app.utils.llm import is_rate_limit_error


class RetrievalDeciderNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(DeciderResponse)

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Retrieval decider started id=%s user_id=%s first_message=%s",
            state["conversation_id"],
            state["user_id"],
            state["first_message"],
        )
        history = state.get("conversation_history") or []
        context = "\n".join(
            f"User: {message.query}, Assistant: {message.response}"
            for message in history[-3:]
        )

        prompt = retrieval_decider_prompt(state["query"], context)
        
        try:
            decision = await self.model.ainvoke(prompt)
            result = decision.decision
            retrieve_memory = decision.retrieve_memory
            is_academic_discussion = decision.is_academic_discussion
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Retrieval decider rate limited id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            else:
                self.logger.exception(
                    "Retrieval decider failed id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            result = "both" if not state["first_message"] else "rag"
            retrieve_memory = False
            is_academic_discussion = True

        mapping = {
            "rag": (True, False),
            "history": (False, True),
            "both": (True, True),
            "none": (False, False),
        }
        retrieve_rag, retrieve_history = mapping.get(result, (False, False))
        if state["first_message"]:
            retrieve_history = False

        self.logger.info(
            "Retrieval decider completed id=%s user_id=%s decision=%s "
            "retrieve_rag=%s retrieve_history=%s retrieve_memory=%s "
            "is_academic_discussion=%s",
            state["conversation_id"],
            state["user_id"],
            result,
            retrieve_rag,
            retrieve_history,
            retrieve_memory,
            is_academic_discussion,
        )

        if not state.get("document_ids"):
            retrieve_rag = False

        return {
            "retrieve_rag": retrieve_rag,
            "retrieve_conversation_history": retrieve_history,
            "retrieve_memory": retrieve_memory,
            "is_academic_discussion": is_academic_discussion,
            }
