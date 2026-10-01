from logging import Logger

from app.agent.study_cards_agent.prompts import generate_chapters_prompt
from app.agent.study_cards_agent.schema import ChapterResult, Critique, StudyCardsResult
from app.agent.study_cards_agent.state import StudyCardsState
from app.agent.study_cards_agent.utils import (
    format_source_content,
    format_tavily_results,
)
from app.memory.schema import Memory
from app.utils.llm import is_rate_limit_error, with_rate_limit_retry
from langchain_google_genai import ChatGoogleGenerativeAI


class GenerateChapterNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(StudyCardsResult)

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
        learning_preferences = self._extract_learning_preferences(memories)
        tavily_by_chapter = state.get("tavily_results") or {}

        chapter_inputs = [
            {
                "chapter_key": chapter_key,
                "content": format_source_content(sections[chapter_key]),
                "tavily_results": format_tavily_results(
                    tavily_by_chapter.get(chapter_key) or []
                ),
                "critique_comment": self._critique_comment(critique, chapter_key),
                "previous_draft": self._previous_draft(
                    generated_chapters, chapter_key
                ),
            }
            for chapter_key in chapter_keys_to_generate
        ]

        result = await self.generate_chapters(
            chapter_inputs,
            learning_preferences,
            expected_keys=set(chapter_keys_to_generate),
        )
        if result is not None:
            for chapter in result.chapters:
                generated_chapters[chapter.chapter_key] = chapter

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

    async def generate_chapters(
        self,
        chapters: list[dict],
        learning_preferences: list[str] | None = None,
        expected_keys: set[str] | None = None,
    ) -> StudyCardsResult | None:
        keys = [chapter["chapter_key"] for chapter in chapters]
        self.logger.info(
            "Generating chapters chapter_keys=%s count=%s "
            "has_preferences=%s for study cards agent",
            keys,
            len(chapters),
            bool(learning_preferences),
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(
                    generate_chapters_prompt(chapters, learning_preferences)
                ),
                logger=self.logger,
                label=f"study cards generate chapters={keys}",
            )
            if expected_keys is not None:
                response = StudyCardsResult(
                    chapters=[
                        chapter
                        for chapter in response.chapters
                        if chapter.chapter_key in expected_keys
                    ]
                )

            self.logger.info(
                "Generated chapters returned=%s expected=%s "
                "for study cards agent",
                [c.chapter_key for c in response.chapters],
                keys,
            )
            return response
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error generating chapters chapter_keys=%s "
                    "for study cards agent",
                    keys,
                )
                raise
            self.logger.exception(
                "Error generating chapters chapter_keys=%s "
                "for study cards agent",
                keys,
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

    @staticmethod
    def _extract_learning_preferences(
        memories: list[Memory] | list[dict] | None,
    ) -> list[str] | None:
        if not memories:
            return None
        prefs: list[str] = []
        for memory in memories:
            if isinstance(memory, dict):
                content = (memory.get("content") or "").strip()
            else:
                content = (getattr(memory, "content", None) or "").strip()
            if content:
                prefs.append(content)
        return prefs or None
