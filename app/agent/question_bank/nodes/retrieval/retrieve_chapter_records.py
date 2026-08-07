from logging import Logger

from app.agent.question_bank.state import QuestionBankState
from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import IndexedRecord


class RetrieveChapterRecordsNode:
    def __init__(self, logger: Logger, elasticsearch: Elasticsearch):
        self.logger = logger
        self.elasticsearch = elasticsearch

    async def __call__(self, state: QuestionBankState) -> QuestionBankState:
        if state.get("chapter_records") is not None:
            self.logger.info(
                "Retrieve chapter records node skipped document_id=%s "
                "reason=already_loaded for question agent",
                state["document_id"],
            )
            return {}

        chapter_keys = state.get("chapter_keys") or []
        if not chapter_keys:
            self.logger.warning(
                "Retrieve chapter records node skipped document_id=%s "
                "reason=no_chapter_keys for question agent",
                state["document_id"],
            )
            return {"chapter_records": {}}

        self.logger.info(
            "Retrieve chapter records node started document_id=%s "
            "user_id=%s for question agent",
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
            "Retrieve chapter records node completed document_id=%s "
            "user_id=%s sessions_by_chapter=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(sessions_by_chapter),
        )

        return {
            "chapter_records": sessions_by_chapter,
        }
