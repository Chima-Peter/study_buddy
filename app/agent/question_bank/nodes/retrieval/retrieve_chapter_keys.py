from logging import Logger

from app.agent.question_bank.state import QuestionBankState
from app.system.document.service import DocumentService


class RetrieveChaptersNode:
    def __init__(self, logger: Logger, document_service: DocumentService):
        self.logger = logger
        self.document_service = document_service

    async def __call__(self, state: QuestionBankState) -> QuestionBankState:
        if state.get("chapter_keys") is not None:
            self.logger.info(
                "Retrieve chapters node skipped document_id=%s reason=already_loaded",
                state["document_id"],
            )
            return {}

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
            "chapter_records": {},
            "generated_chapters": {},
            "approved_chapters": [],
            "skipped_generated_chapters": [],
            "skipped_critique_chapters": [],
            "critique": {},
            "final_question_bank": None,
            "saved": False,
        }
