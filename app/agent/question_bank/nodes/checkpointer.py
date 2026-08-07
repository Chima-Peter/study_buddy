from logging import Logger

from app.agent.question_bank.state import QuestionBankState


class CheckpointerNode:
    """Hub node; routing is decided by the outgoing conditional edge."""

    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: QuestionBankState) -> dict:
        self.logger.info(
            "Checkpointer called document_id=%s user_id=%s for question agent",
            state["document_id"],
            state["user_id"],
        )
        return {}
