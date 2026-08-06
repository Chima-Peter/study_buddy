from logging import Logger

from app.agent.study_cards_agent.schema import StudyCardsResult
from app.agent.study_cards_agent.state import StudyCardsState


class ConsolidateNode:
    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        self.logger.info(
            "Consolidate node started document_id=%s user_id=%s",
            state["document_id"],
            state["user_id"],
        )
        
        generated_chapters = state["generated_chapters"]
        final_document = [
            chapter for chapter in generated_chapters.values()
        ]

        self.logger.info(
            "Consolidate node completed document_id=%s user_id=%s",
            state["document_id"],
            state["user_id"],
        )
        return {
            "final_result": StudyCardsResult(chapters=final_document),
        }