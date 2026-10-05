from logging import Logger

from langgraph.config import get_stream_writer
from tavily import TavilyClient

from app.agent.chat_agent.state import AgentState
from app.agent.chat_agent.utils import pick_progress
from app.utils.llm import is_rate_limit_error


class TavilyRetrieverNode:
    def __init__(
        self,
        tavily: TavilyClient,
        logger: Logger,
    ):
        self.tavily = tavily
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Tavily retriever node started id=%s user_id=%s",
            state.get("conversation_id"),
            state.get("user_id"),
        )
        search_query = (state.get("tavily_query") or "").strip()
        if not search_query:
            self.logger.info(
                "Tavily search skipped id=%s user_id=%s reason=insufficient_query",
                state.get("conversation_id"),
                state.get("user_id"),
            )
            return {"tavily_results": []}

        get_stream_writer()({
            "type": "chat.progress",
            "message": pick_progress("tavily"),
            "conversation_id": state.get("conversation_id"),
        })

        try:
            raw = self.tavily.search(
                search_query,
                search_depth="advanced",
            )
            results = raw.get("results", []) if isinstance(raw, dict) else (raw or [])
            if not isinstance(results, list):
                results = []
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Tavily search rate limited id=%s user_id=%s",
                    state.get("conversation_id"),
                    state.get("user_id"),
                )
            else:
                self.logger.exception(
                    "Tavily search failed id=%s user_id=%s",
                    state.get("conversation_id"),
                    state.get("user_id"),
                )
            return {"tavily_results": []}

        self.logger.info(
            "Tavily retriever node completed id=%s user_id=%s "
            "search_query=%r results=%s",
            state.get("conversation_id"),
            state.get("user_id"),
            search_query,
            len(results),
        )
        return {"tavily_results": results}
