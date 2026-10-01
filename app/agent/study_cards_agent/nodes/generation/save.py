from logging import Logger

from app.agent.study_cards_agent.state import StudyCardsState
from app.system.study_cards import StudyCardsService


class SaveNode:
    def __init__(self, logger: Logger, study_card_service: StudyCardsService):
        self.logger = logger
        self.study_card_service = study_card_service

    async def __call__(self, state: StudyCardsState) -> dict:
        self.logger.info(
            "Save node started document_id=%s user_id=%s for study cards agent",
            state["document_id"],
            state["user_id"],
        )

        if not state.get("final_result") or len(state.get("final_result").chapters) == 0:
            self.logger.warning(
                "No final result found for document_id=%s user_id=%s",
                state["document_id"],
                state["user_id"],
            )
            return {"saved": False}

        sections = state.get("document_sections") or {}
        source = {
            chapter_key: [
                {
                    "content": record.content,
                    "metadata": record.metadata,
                }
                for record in records
            ]
            for chapter_key, records in sections.items()
        }
        audit = {
            "source": source,
            "tavily": state.get("tavily_results") or {},
        }

        try:
            await self.study_card_service.update_result(
                state["document_id"],
                state["user_id"],
                state["final_result"].model_dump(),
                reason="Study cards generated successfully",
                audit=audit,
            )
        except Exception:
            self.logger.exception(
                "Error saving study cards document_id=%s user_id=%s",
                state["document_id"],
                state["user_id"],
            )
            raise

        self.logger.info(
            "Save node completed document_id=%s user_id=%s for study cards agent",
            state["document_id"],
            state["user_id"],
        )
        return {"saved": True}
