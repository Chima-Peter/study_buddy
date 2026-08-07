from logging import Logger

from app.agent.question_bank.schema import QuestionBankResult
from app.agent.question_bank.state import QuestionBankState


class ConsolidateNode:
    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: QuestionBankState) -> dict:
        self.logger.info(
            "Consolidate node started document_id=%s user_id=%s "
            "for question agent",
            state["document_id"],
            state["user_id"],
        )

        final_document = list((state.get("generated_chapters") or {}).values())

        self.logger.info(
            "Consolidate node completed document_id=%s user_id=%s "
            "chapters=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(final_document),
        )
        return {
            "final_question_bank": QuestionBankResult(chapters=final_document),
        }
