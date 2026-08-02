from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.prompts import retrieval_decider_prompt
from app.agent.schema import DeciderResponse
from app.agent.state import AgentState


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
        prompt = retrieval_decider_prompt(state["query"])
        try:
            decision = await self.model.ainvoke(prompt)
            result = decision.decision
            retrieve_memory = decision.retrieve_memory
        except Exception:
            self.logger.exception(
                "Retrieval decider failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            result = "both" if not state["first_message"] else "rag"
            retrieve_memory = False

        mapping = {
            "rag": (True, False),
            "history": (False, True),
            "both": (True, True),
            "none": (False, False),
        }
        retrieve_rag, retrieve_history = mapping.get(result, (False, False))
        # First turn has no history worth loading.
        if state["first_message"]:
            retrieve_history = False

        self.logger.info(
            "Retrieval decider completed id=%s user_id=%s decision=%s "
            "retrieve_rag=%s retrieve_history=%s retrieve_memory=%s",
            state["conversation_id"],
            state["user_id"],
            result,
            retrieve_rag,
            retrieve_history,
            retrieve_memory,
        )

        if not state.get("document_id"):
            retrieve_rag = False

        return {
            "retrieve_rag": retrieve_rag,
            "retrieve_conversation_history": retrieve_history,
            "retrieve_memory": retrieve_memory,
        }
