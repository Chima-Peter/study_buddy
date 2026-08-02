from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.chat_agent.prompts import rewrite_query_prompt
from app.agent.chat_agent.schema import RewriteQueryResponse
from app.agent.chat_agent.state import AgentState


class RewriteQueryNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model

    async def __call__(self, state: AgentState) -> AgentState:
        retrieve_rag = state["retrieve_rag"]
        retrieve_memory = state["retrieve_memory"]

        if not retrieve_rag and not retrieve_memory:
            self.logger.info(
                "Rewrite query node skipped id=%s user_id=%s "
                "reason=no_retrieval",
                state["conversation_id"],
                state["user_id"],
            )
            return {
                "rewritten_query": state["query"],
                "memory_query": None,
            }

        self.logger.info(
            "Rewrite query node started id=%s user_id=%s "
            "retrieve_rag=%s retrieve_memory=%s",
            state["conversation_id"],
            state["user_id"],
            retrieve_rag,
            retrieve_memory,
        )
        recent_history = state["conversation_history"][-3:]
        prompt = rewrite_query_prompt(
            query=state["query"],
            conversation_summary=state["conversation_summary"],
            recent_history=recent_history,
            retrieve_rag=retrieve_rag,
            retrieve_memory=retrieve_memory,
        )
        try:
            result: RewriteQueryResponse = (
                await self.model.with_structured_output(
                    RewriteQueryResponse
                ).ainvoke(prompt)
            )
        except Exception:
            self.logger.exception(
                "Rewrite query node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {
                "rewritten_query": state["query"],
                "memory_query": state["query"] if retrieve_memory else None,
            }

        rewritten = state["query"]
        if retrieve_rag:
            rewritten = (result.rag_query or "").strip() or state["query"]

        memory_query = None
        if retrieve_memory:
            memory_query = (result.memory_query or "").strip() or state["query"]

        self.logger.info(
            "Rewrite query node completed id=%s user_id=%s original=%r "
            "rewritten=%r memory_query=%r",
            state["conversation_id"],
            state["user_id"],
            state["query"],
            rewritten,
            memory_query,
        )
        return {
            "rewritten_query": rewritten,
            "memory_query": memory_query,
        }
