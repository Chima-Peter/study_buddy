from asyncio import TaskGroup, to_thread
from logging import Logger

from tavily import TavilyClient

from app.agent.study_cards_agent.state import StudyCardsState
from app.utils.llm import is_rate_limit_error


class TavilyRetrieverNode:
    """Fetch external article/YouTube links per chapter for study cards."""

    def __init__(self, tavily: TavilyClient, logger: Logger):
        self.tavily = tavily
        self.logger = logger

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        if state.get("tavily_results") is not None:
            self.logger.info(
                "Tavily retriever skipped document_id=%s "
                "reason=already_loaded for study cards agent",
                state["document_id"],
            )
            return {}

        chapter_keys = [
            key.strip()
            for key in (state.get("chapter_keys") or [])
            if key and key.strip()
        ]
        if not chapter_keys:
            self.logger.info(
                "Tavily retriever skipped document_id=%s "
                "reason=no_chapter_keys for study cards agent",
                state["document_id"],
            )
            return {"tavily_results": {}}

        self.logger.info(
            "Tavily retriever started document_id=%s user_id=%s "
            "chapters=%s for study cards agent",
            state["document_id"],
            state["user_id"],
            len(chapter_keys),
        )

        results_by_chapter: dict[str, list[dict]] = {}

        async with TaskGroup() as tg:
            tasks = {
                chapter_key: tg.create_task(self._search_chapter(chapter_key))
                for chapter_key in chapter_keys
            }

        for chapter_key, task in tasks.items():
            results_by_chapter[chapter_key] = task.result()

        self.logger.info(
            "Tavily retriever completed document_id=%s user_id=%s "
            "chapters_with_results=%s for study cards agent",
            state["document_id"],
            state["user_id"],
            sum(1 for hits in results_by_chapter.values() if hits),
        )
        return {"tavily_results": results_by_chapter}

    async def _search_chapter(self, chapter_key: str) -> list[dict]:
        search_query = (
            "provide some articles and youtube videos on this: "
            f"{chapter_key}. stick only to youtube and google website urls"
        )
        try:
            raw = await to_thread(
                self.tavily.search,
                search_query,
                search_depth="advanced",
            )
            results = raw.get("results", []) if isinstance(raw, dict) else (raw or [])
            if not isinstance(results, list):
                return []
            return [hit for hit in results if isinstance(hit, dict)]
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Tavily search rate limited chapter_key=%s "
                    "for study cards agent",
                    chapter_key,
                )
            else:
                self.logger.exception(
                    "Tavily search failed chapter_key=%s for study cards agent",
                    chapter_key,
                )
            return []
