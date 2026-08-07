from logging import Logger

from app.agent.question_bank.state import QuestionBankState


class SaveNode:
    """Marks the run complete. Persistence can be added when a service exists."""

    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: QuestionBankState) -> dict:
        self.logger.info(
            "Save node started document_id=%s user_id=%s for question agent",
            state["document_id"],
            state["user_id"],
        )

        final = state.get("final_question_bank")
        chapter_count = len(final.chapters) if final is not None else 0

        self.logger.info(
            "Save node completed document_id=%s user_id=%s "
            "chapters=%s for question agent",
            state["document_id"],
            state["user_id"],
            chapter_count,
        )
        return {"saved": True}
