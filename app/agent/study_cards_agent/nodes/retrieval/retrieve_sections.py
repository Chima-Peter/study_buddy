from logging import Logger

from app.agent.study_cards_agent.state import StudyCardsState
from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import IndexedRecord


class RetrieveSectionsNode:
    def __init__(self, logger: Logger, elasticsearch: Elasticsearch):
        self.logger = logger
        self.elasticsearch = elasticsearch

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        if state.get("document_sections") is not None:
            self.logger.info(
                "Retrieve sections node skipped document_id=%s "
                "reason=already_loaded for study cards agent",
                state["document_id"],
            )
            return {}

        chapter_keys = state.get("chapter_keys") or []
        if not chapter_keys:
            self.logger.warning(
                "Retrieve sections node skipped document_id=%s "
                "reason=no_chapter_keys for study cards agent",
                state["document_id"],
            )
            return {"document_sections": {}}

        self.logger.info(
            "Retrieve sections node started document_id=%s user_id=%s "
            "for study cards agent",
            state["document_id"],
            state["user_id"],
        )

        records = await self.elasticsearch.search_by_metadata(
            state["user_id"],
            "documents",
            document_id=state["document_id"],
            chapter_key=chapter_keys,
        )

        sections_by_chapter: dict[str, list[IndexedRecord]] = {}
        for record in records:
            chapter_key = record.metadata.get("chapter_key")
            if chapter_key:
                sections_by_chapter.setdefault(chapter_key, []).append(record)

        self.logger.info(
            "Retrieve sections node completed document_id=%s user_id=%s "
            "sections_by_chapter=%s for study cards agent",
            state["document_id"],
            state["user_id"],
            len(sections_by_chapter),
        )

        return {
            "document_sections": sections_by_chapter,
        }
