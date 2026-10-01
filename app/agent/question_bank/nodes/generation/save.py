from logging import Logger

from app.agent.question_bank.state import QuestionBankState
from app.system.question_bank.service import QuestionBankService


class SaveNode:
    def __init__(self, logger: Logger, question_bank_service: QuestionBankService):
        self.logger = logger
        self.question_bank_service = question_bank_service

    async def __call__(self, state: QuestionBankState) -> dict:
        self.logger.info(
            "Save node started document_id=%s user_id=%s for question agent",
            state["document_id"],
            state["user_id"],
        )

        payload = [
            question.model_dump() for chapter in state["final_question_bank"].chapters
            for question in chapter.questions
        ]

        chapter_records = state.get("chapter_records") or {}
        audit = {
            "source": {
                chapter_key: [
                    {
                        "content": record.content,
                        "metadata": record.metadata,
                    }
                    for record in records
                ]
                for chapter_key, records in chapter_records.items()
            }
        }

        try:
            await self.question_bank_service.update_result(
                state["document_id"],
                state["user_id"],
                payload,
                audit=audit,
            )
        except Exception:
            self.logger.exception(
                "Error saving question bank document_id=%s user_id=%s",
                state["document_id"],
                state["user_id"],
            )
            raise

        self.logger.info(
            "Save node completed document_id=%s user_id=%s for question agent",
            state["document_id"],
            state["user_id"],
        )
        return {"saved": True}
