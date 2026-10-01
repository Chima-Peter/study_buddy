from logging import Logger

from langchain_google_genai import ChatGoogleGenerativeAI
from tavily import TavilyClient

from app.agent.chat_agent.utils import format_history
from app.agent.chat_agent.prompts import tavily_query_rewriter_prompt
from app.agent.chat_agent.schema import SUMMARY_EVERY, TavilyQueryRewriteResponse
from app.agent.chat_agent.state import AgentState
from app.utils.llm import is_rate_limit_error


class TavilyRetrieverNode:
    def __init__(
        self,
        tavily: TavilyClient,
        logger: Logger,
        query_model: ChatGoogleGenerativeAI,
    ):
        self.tavily = tavily
        self.logger = logger
        self.model = query_model.with_structured_output(TavilyQueryRewriteResponse)

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Tavily retriever node started id=%s user_id=%s",
            state.get("conversation_id"),
            state.get("user_id"),
        )
        query = (state.get("query") or "").strip()
        if not query:
            return {"tavily_results": []}

        recent_history = format_history(
            state.get("messages"),
            limit=SUMMARY_EVERY,
        )
        summary = state.get("conversation_summary") or ""

        try:
            rewritten: TavilyQueryRewriteResponse = await self.model.ainvoke(
                tavily_query_rewriter_prompt(
                    query,
                    recent_history=recent_history or "(none)",
                    summary=summary,
                )
            )
            search_query = (rewritten.search_query or "").strip() or None
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Tavily query rewrite rate limited id=%s user_id=%s",
                    state.get("conversation_id"),
                    state.get("user_id"),
                )
            else:
                self.logger.exception(
                    "Tavily query rewrite failed id=%s user_id=%s",
                    state.get("conversation_id"),
                    state.get("user_id"),
                )
            return {"tavily_results": []}

        if not search_query:
            self.logger.info(
                "Tavily search skipped id=%s user_id=%s reason=insufficient_query",
                state.get("conversation_id"),
                state.get("user_id"),
            )
            return {"tavily_results": []}

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
            results,
        )
        return {"tavily_results": results}
