from asyncio import TaskGroup
from logging import Logger

from app.agent.study_cards_agent.prompts import generate_chapter_prompt
from app.agent.study_cards_agent.schema import ChapterResult
from app.agent.study_cards_agent.state import StudyCardsState
from app.core.elasticsearch_schema import IndexedRecord
from app.utils.llm import is_rate_limit_error
from langchain_google_genai import ChatGoogleGenerativeAI


class GenerateChapterNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(ChapterResult)

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        sections = state["document_sections"]
        pending_chapters = state["pending_chapters"]
        retry_count = state["retry_count"]
        missing_chapters = state["missing_chapters"]

        if not pending_chapters:
            self.logger.info(
                "No pending chapters to generate for document_id=%s user_id=%s",
                state["document_id"],
                state["user_id"],
            )
            return state

        self.logger.info(
            "Generate chapter node started document_id=%s user_id=%s pending_chapters=%s retry_count=%s",
            state["document_id"],
            state["user_id"],
            len(pending_chapters),
            retry_count,
        )

        results: dict[str, ChapterResult] = state["generated_chapters"]
        chapter_keys_to_generate = [
            chapter_key
            for chapter_key in sections
            if chapter_key in pending_chapters or chapter_key in missing_chapters
        ]

        async with TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self.generate_chapter(
                        chapter_key,
                        sections[chapter_key],
                    )
                )
                for chapter_key in chapter_keys_to_generate
            ]

        for task in tasks:
            result = task.result()
            if result is not None:
                results[result.chapter_key] = result

        self.logger.info(
            "Generated chapters for document_id=%s user_id=%s generated_chapters=%s",
            state["document_id"],
            state["user_id"],
            len(results),
        )

        return {
            "generated_chapters": results,
            "retry_count": {
                "generate": retry_count["generate"] + 1,
                "critique": retry_count["critique"],
            },
        }

    async def generate_chapter(
        self, chapter_key: str, section: list[IndexedRecord]
    ) -> ChapterResult | None:
        content = "\n".join([record.content for record in section])
        self.logger.info(
            "Generating chapter for section chapter_key=%s content_len=%s",
            chapter_key,
            len(content),
        )

        try:
            response = await self.model.ainvoke(
                generate_chapter_prompt(chapter_key, content)
            )
            result = response.model_copy(update={"chapter_key": chapter_key})

            self.logger.info(
                "Generated chapter for section chapter_key=%s", chapter_key
            )
            return result
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error generating chapter for section chapter_key=%s",
                    chapter_key,
                )
            self.logger.exception(
                "Error generating chapter for section chapter_key=%s", chapter_key
            )
            return None