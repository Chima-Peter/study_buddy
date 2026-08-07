from logging import Logger
from app.agent.study_cards_agent.state import StudyCardsState
from app.memory.schema import MemoryRetrievalQuery
from app.memory.service import MemoryService


class RetrieveMemoriesNode:
    def __init__(self, memory_service: MemoryService, logger: Logger):
        self.memory_service = memory_service
        self.logger = logger

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        if state.get("memories") is not None:
            self.logger.info(
                "Retrieve memories node skipped document_id=%s "
                "reason=already_loaded for quiz bank agent",
                state["document_id"],
            )
            return {}

        self.logger.info(
            "Retrieving memories for document_id=%s for quiz bank agent",
            state["document_id"],
        )

        memories = await self.memory_service.retrieve_for_queries(
            user_id=state["user_id"],
            queries=[
                MemoryRetrievalQuery(content="The user's learning style"),
                MemoryRetrievalQuery(content="The user's study preferences"),
            ],
        )

        if not memories:
            self.logger.warning(
                "No memories found for document_id=%s for quiz bank agent",
                state["document_id"],
            )
            return {"memories": []}

        self.logger.info(
            "Retrieved %d memories for document_id=%s for quiz bank agent",
            len(memories),
            state["document_id"],
        )
        return {"memories": memories}
