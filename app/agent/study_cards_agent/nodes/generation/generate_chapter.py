import asyncio
from logging import Logger

from app.agent.study_cards_agent.prompts import generate_chapter_prompt
from app.agent.study_cards_agent.schema import ChapterResult
from app.agent.study_cards_agent.state import StudyCardsState
from app.agent.study_cards_agent.utils import (
    critique_comment,
    extract_learning_preferences,
    format_source_content,
    format_tavily_results,
    previous_draft,
)
from app.utils.llm import is_rate_limit_error, with_rate_limit_retry
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
                "for document_id=%s user_id=%s for study cards agent",
                state["document_id"],
                state["user_id"],
            )
            return state

        self.logger.info(
            "Generate chapter node started document_id=%s user_id=%s "
            "missing_chapters=%s pending_chapters=%s retry_count=%s "
            "for study cards agent",
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
                "document_id=%s user_id=%s undone=%s for study cards agent",
                state["document_id"],
                state["user_id"],
                len(undone_critique_chapters),
            )
            return state

        memories = state.get("memories", [])
        learning_preferences = extract_learning_preferences(memories)
        tavily_by_chapter = state.get("tavily_results") or {}

        chapter_inputs = [
            {
                "chapter_key": chapter_key,
                "content": format_source_content(sections[chapter_key]),
                "tavily_results": format_tavily_results(
                    tavily_by_chapter.get(chapter_key) or []
                ),
                "critique_comment": critique_comment(critique, chapter_key),
                "previous_draft": previous_draft(generated_chapters, chapter_key),
            }
            for chapter_key in chapter_keys_to_generate
        ]

        results = await asyncio.gather(
            *[
                self.generate_chapter(chapter, learning_preferences)
                for chapter in chapter_inputs
            ],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                if is_rate_limit_error(result):
                    raise result
                continue
            if result is not None:
                generated_chapters[result.chapter_key] = result

        self.logger.info(
            "Generated chapters for document_id=%s user_id=%s "
            "generated_chapters=%s for study cards agent",
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
        chapter: dict,
        learning_preferences: list[str] | None = None,
    ) -> ChapterResult | None:
        chapter_key = chapter["chapter_key"]
        self.logger.info(
            "Generating chapter chapter_key=%s has_preferences=%s "
            "for study cards agent",
            chapter_key,
            bool(learning_preferences),
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(
                    generate_chapter_prompt(chapter, learning_preferences)
                ),
                logger=self.logger,
                label=f"study cards generate chapter={chapter_key}",
            )
            if response.chapter_key != chapter_key:
                self.logger.warning(
                    "Generated chapter key mismatch expected=%s got=%s "
                    "for study cards agent",
                    chapter_key,
                    response.chapter_key,
                )
                return None

            self.logger.info(
                "Generated chapter chapter_key=%s for study cards agent",
                chapter_key,
            )
            return response
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error generating chapter chapter_key=%s "
                    "for study cards agent",
                    chapter_key,
                )
                raise
            self.logger.exception(
                "Error generating chapter chapter_key=%s "
                "for study cards agent",
                chapter_key,
            )
            return None
