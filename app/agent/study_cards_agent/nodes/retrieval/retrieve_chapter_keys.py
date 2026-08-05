from logging import Logger

from app.agent.study_cards_agent.state import StudyCardsState
from app.system.document.service import DocumentService


class RetrieveChaptersNode:
    def __init__(self, logger: Logger, document_service: DocumentService):
        self.logger = logger
        self.document_service = document_service

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        self.logger.info(
            "Retrieve chapters node started document_id=%s user_id=%s",
            state["document_id"],
            state["user_id"],
        )
        document = await self.document_service.get_document_by_id(
            state["document_id"],
            state["user_id"],
        )
        return {
            "chapter_keys": document.sections.split(","),
            "pending_chapters": document.sections.split(","),
            "missing_chapters": [],
            "approved_chapters": [],
            "retry_count": {
                "generate": 0,
                "critique": 0,
            },
            "generated_chapters": {},
        }
