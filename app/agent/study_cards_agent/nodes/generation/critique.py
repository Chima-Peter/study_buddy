import asyncio
from logging import Logger

from app.agent.study_cards_agent.prompts import critique_chapter_prompt
from app.agent.study_cards_agent.schema import Critique
from app.agent.study_cards_agent.state import StudyCardsState
from app.agent.study_cards_agent.utils import (
    format_source_content,
    format_tavily_results,
)
from app.utils.llm import is_rate_limit_error, with_rate_limit_retry
from langchain_google_genai import ChatGoogleGenerativeAI


class CritiqueNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(Critique)

    async def __call__(self, state: StudyCardsState) -> StudyCardsState:
        generated_chapters = state["generated_chapters"]
        chapter_keys = state["chapter_keys"]
        retry_count = state["retry_count"]
        document_sections = state["document_sections"]
        tavily_by_chapter = state.get("tavily_results") or {}
        approved_chapters = set(state["approved_chapters"])
        missing_chapters = [
            chapter_key
            for chapter_key in chapter_keys
            if chapter_key not in generated_chapters
        ]

        pending_chapters: list[str] = []
        newly_approved_chapters: list[str] = []
        undone_critique_chapters: list[str] = []
        critique = dict(state.get("critique", {}))
        chapter_keys_to_critique = [
            chapter_key
            for chapter_key in generated_chapters
            if chapter_key not in approved_chapters
        ]

        if missing_chapters:
            self.logger.info(
                "Missing chapters before critique document_id=%s user_id=%s "
                "missing_chapters=%s for study cards agent",
                state["document_id"],
                state["user_id"],
                len(missing_chapters),
            )

        if not generated_chapters:
            self.logger.info(
                "No generated chapters to critique document_id=%s user_id=%s "
                "for study cards agent",
                state["document_id"],
                state["user_id"],
            )
            return {
                "missing_chapters": missing_chapters,
                "pending_chapters": missing_chapters,
                "approved_chapters": [],
                "critique": critique,
                "undone_critique_chapters": [],
                "retry_count": {
                    "critique": retry_count["critique"] + 1,
                    "generate": retry_count["generate"],
                },
            }

        self.logger.info(
            "Critique node started document_id=%s user_id=%s "
            "chapters=%s retry_count=%s for study cards agent",
            state["document_id"],
            state["user_id"],
            len(chapter_keys_to_critique),
            retry_count["critique"],
        )

        if chapter_keys_to_critique:
            chapter_inputs = [
                {
                    "chapter_key": chapter_key,
                    "generated_chapter": generated_chapters[
                        chapter_key
                    ].model_dump_json(),
                    "source_content": format_source_content(
                        document_sections.get(chapter_key, [])
                    ),
                    "tavily_results": format_tavily_results(
                        tavily_by_chapter.get(chapter_key) or []
                    ),
                }
                for chapter_key in chapter_keys_to_critique
            ]
            results = await asyncio.gather(
                *[self.critique_chapter(chapter) for chapter in chapter_inputs],
                return_exceptions=True,
            )
            completed_keys: set[str] = set()
            for entry in results:
                if isinstance(entry, Exception):
                    if is_rate_limit_error(entry):
                        raise entry
                    continue
                if entry is None:
                    continue
                critique[entry.chapter_key] = entry
                completed_keys.add(entry.chapter_key)
                if entry.status == "approved":
                    newly_approved_chapters.append(entry.chapter_key)
                else:
                    pending_chapters.append(entry.chapter_key)

            for chapter_key in chapter_keys_to_critique:
                if chapter_key not in completed_keys:
                    undone_critique_chapters.append(chapter_key)

        self.logger.info(
            "Critique node completed document_id=%s user_id=%s "
            "approved=%s pending=%s missing=%s undone=%s for study cards agent",
            state["document_id"],
            state["user_id"],
            len(newly_approved_chapters),
            len(pending_chapters),
            len(missing_chapters),
            len(undone_critique_chapters),
        )

        return {
            "missing_chapters": missing_chapters,
            "pending_chapters": pending_chapters,
            "approved_chapters": newly_approved_chapters,
            "critique": critique,
            "undone_critique_chapters": undone_critique_chapters,
            "retry_count": {
                "critique": retry_count["critique"] + 1,
                "generate": retry_count["generate"],
            },
        }

    async def critique_chapter(self, chapter: dict) -> Critique | None:
        chapter_key = chapter["chapter_key"]
        self.logger.info(
            "Critiquing chapter chapter_key=%s for study cards agent",
            chapter_key,
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(critique_chapter_prompt(chapter)),
                logger=self.logger,
                label=f"study cards critique chapter={chapter_key}",
            )
            if response.chapter_key != chapter_key:
                self.logger.warning(
                    "Critique chapter key mismatch expected=%s got=%s "
                    "for study cards agent",
                    chapter_key,
                    response.chapter_key,
                )
                return None

            self.logger.info(
                "Critiqued chapter chapter_key=%s status=%s "
                "for study cards agent",
                chapter_key,
                response.status,
            )
            return response
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error critiquing chapter chapter_key=%s "
                    "for study cards agent",
                    chapter_key,
                )
                raise
            self.logger.exception(
                "Error critiquing chapter chapter_key=%s "
                "for study cards agent",
                chapter_key,
            )
            return None
