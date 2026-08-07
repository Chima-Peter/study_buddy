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

        await self.question_bank_service.update_result(
            state["document_id"],
            state["user_id"],
            state["final_question_bank"].model_dump(),
            reason="Question bank generated successfully",
        )

        self.logger.info(
            "Save node completed document_id=%s user_id=%s for question agent",
            state["document_id"],
            state["user_id"],
        )
        return {"saved": True}
