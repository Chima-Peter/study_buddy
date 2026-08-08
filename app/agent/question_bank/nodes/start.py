from logging import Logger

from app.agent.question_bank.state import QuestionBankState



class StartNode:
    """Reset local generate/critique retries on a fresh consumer attempt."""

    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: QuestionBankState) -> dict:
        self.logger.info(
            "Start node called document_id=%s user_id=%s "
            "consumer_retry_count=%s for question bank agent",
            state["document_id"],
            state["user_id"],
            state.get("consumer_retry_count", 0),
        )

        if state.get("consumer_retry_count", 0) == 0:
            self.logger.info(
                "Consumer retry count is 0, resetting local retry counts "
                "document_id=%s for question bank agent",
                state["document_id"],
            )
            return {
                "retry_count": {
                    "generate": 0,
                    "critique": 0,
                }
            }

        return {}
