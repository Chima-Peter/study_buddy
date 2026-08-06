from logging import Logger

from app.agent.study_cards_agent.state import StudyCardsState
from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import IndexedRecord


class RetrieveSessionsNode:
    def __init__(self, logger: Logger, elasticsearch: Elasticsearch):
        self.logger = logger
        self.elasticsearch = elasticsearch

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        self.logger.info(
            "Retrieve sessions node started document_id=%s user_id=%s",
            state["document_id"],
            state["user_id"],
        )

        sessions = await self.elasticsearch.search_by_metadata(
            state["user_id"],
            "documents",
            document_id=state["document_id"],
            chapter_key=state["chapter_keys"],
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
