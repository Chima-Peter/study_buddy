from logging import Logger

from app.agent.study_cards_agent.state import StudyCardsState
from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import IndexedRecord


class RetrieveSessionsNode:
    def __init__(self, logger: Logger, elasticsearch: Elasticsearch):
        self.logger = logger
        self.elasticsearch = elasticsearch

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        if state.get("document_sections") is not None:
            self.logger.info(
                "Retrieve sessions node skipped document_id=%s reason=already_loaded",
                state["document_id"],
            )
            return {}

        chapter_keys = state.get("chapter_keys") or []
        if not chapter_keys:
            self.logger.warning(
                "Retrieve sessions node skipped document_id=%s reason=no_chapter_keys",
                state["document_id"],
            )
            return {"document_sections": {}}

        self.logger.info(
            "Retrieve sessions node started document_id=%s user_id=%s",
            state["document_id"],
            state["user_id"],
        )

        sessions = await self.elasticsearch.search_by_metadata(
            state["user_id"],
            "documents",
            document_id=state["document_id"],
            chapter_key=chapter_keys,
        )

        sessions_by_chapter: dict[str, list[IndexedRecord]] = {}
        for session in sessions:
            chapter_key = session.metadata.get("chapter_key")
            if chapter_key:
                sessions_by_chapter.setdefault(chapter_key, []).append(session)

        self.logger.info(
            "Retrieve sessions node completed document_id=%s user_id=%s "
            "sessions_by_chapter=%s",
            state["document_id"],
            state["user_id"],
            len(sessions_by_chapter),
        )

        return {
            "document_sections": sessions_by_chapter,
        }
