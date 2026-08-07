from logging import Logger

from app.agent.study_cards_agent.state import StudyCardsState


class CheckpointerNode:
    """Hub node; routing is decided by the outgoing conditional edge."""

    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: StudyCardsState) -> dict:
        self.logger.info(
            "Checkpointer called document_id=%s user_id=%s for quiz bank agent",
            state["document_id"],
            state["user_id"],
        )

        return {}
