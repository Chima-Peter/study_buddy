from logging import Logger

from app.agent.quiz_agent.state import QuizState
from langchain_google_genai import ChatGoogleGenerativeAI


class GenerateChapterNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model

    async def __call__(self, state: QuizState) -> QuizState:
        self.logger.info(
            "Generate chapter node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        return state