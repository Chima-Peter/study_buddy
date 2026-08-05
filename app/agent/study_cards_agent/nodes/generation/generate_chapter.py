from asyncio import TaskGroup
from logging import Logger

from app.agent.study_cards_agent.prompts import generate_chapter_prompt
from app.agent.study_cards_agent.schema import ChapterResult, Critique
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
        critique = state.get("critique")

        if not pending_chapters and not missing_chapters:
            self.logger.info(
                "No pending or missing chapters to generate "
                "for document_id=%s user_id=%s",
                state["document_id"],
                state["user_id"],
            )
            return state

        self.logger.info(
            "Generate chapter node started document_id=%s user_id=%s "
            "missing_chapters=%s pending_chapters=%s retry_count=%s",
            state["document_id"],
            state["user_id"],
            len(missing_chapters),
            len(pending_chapters),
            retry_count["generate"],
        )

        generated_chapters = state["generated_chapters"]
        undone_critique_chapters = set(state.get("undone_critique_chapters", []))
        chapter_keys_to_generate = [
            chapter_key
            for chapter_key in sections
            if (chapter_key in pending_chapters or chapter_key in missing_chapters)
            and chapter_key not in undone_critique_chapters
        ]

        if not chapter_keys_to_generate:
            self.logger.info(
                "Nothing to generate after excluding undone critiques "
                "document_id=%s user_id=%s undone=%s",
                state["document_id"],
                state["user_id"],
                len(undone_critique_chapters),
            )
            return state

        async with TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self.generate_chapter(
                        chapter_key,
                        sections[chapter_key],
                        self._critique_comment(critique, chapter_key),
                        self._previous_draft(generated_chapters, chapter_key),
                    )
                )
                for chapter_key in chapter_keys_to_generate
            ]

        for task in tasks:
            result = task.result()
            if result is not None:
                generated_chapters[result.chapter_key] = result

        self.logger.info(
            "Generated chapters for document_id=%s user_id=%s generated_chapters=%s",
            state["document_id"],
            state["user_id"],
            len(generated_chapters),
        )

        return {
            "generated_chapters": generated_chapters,
            "retry_count": {
                "generate": retry_count["generate"] + 1,
                "critique": retry_count["critique"],
            },
        }

    async def generate_chapter(
        self,
        chapter_key: str,
        section: list[IndexedRecord],
        critique_comment: str | None = None,
        previous_draft: str | None = None,
    ) -> ChapterResult | None:
        content = "\n".join([record.content for record in section])
        self.logger.info(
            "Generating chapter for section chapter_key=%s content_len=%s "
            "has_critique=%s has_previous_draft=%s",
            chapter_key,
            len(content),
            bool(critique_comment),
            bool(previous_draft),
        )

        try:
            response = await self.model.ainvoke(
                generate_chapter_prompt(
                    chapter_key, content, critique_comment, previous_draft
                )
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

    @staticmethod
    def _critique_comment(
        critique: dict[str, Critique] | None, chapter_key: str
    ) -> str | None:
        if critique is None:
            return None
        entry = critique.get(chapter_key)
        if entry is None or entry.status != "rejected":
            return None
        return (
            entry.comment
            or "Rejected without detailed feedback. Revise against all "
            "ChapterResult requirements and quality rules."
        )

    @staticmethod
    def _previous_draft(
        generated_chapters: dict[str, ChapterResult], chapter_key: str
    ) -> str | None:
        chapter = generated_chapters.get(chapter_key)
        if chapter is None:
            return None
        return chapter.model_dump_json()
