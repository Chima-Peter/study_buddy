from logging import Logger

from app.agent.study_cards_agent.prompts import critique_chapters_prompt
from app.agent.study_cards_agent.schema import CritiqueResult
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
        self.model = model.with_structured_output(CritiqueResult)

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
            result = await self.critique_chapters(
                chapter_inputs,
                expected_keys=set(chapter_keys_to_critique),
            )
            completed_keys: set[str] = set()
            if result is not None:
                for entry in result.critiques:
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

    async def critique_chapters(
        self,
        chapters: list[dict],
        expected_keys: set[str] | None = None,
    ) -> CritiqueResult | None:
        keys = [chapter["chapter_key"] for chapter in chapters]
        self.logger.info(
            "Critiquing chapters chapter_keys=%s count=%s for study cards agent",
            keys,
            len(chapters),
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(critique_chapters_prompt(chapters)),
                logger=self.logger,
                label=f"study cards critique chapters={keys}",
            )
            if expected_keys is not None:
                response = CritiqueResult(
                    critiques=[
                        entry
                        for entry in response.critiques
                        if entry.chapter_key in expected_keys
                    ]
                )

            self.logger.info(
                "Critiqued chapters returned=%s expected=%s "
                "for study cards agent",
                [c.chapter_key for c in response.critiques],
                keys,
            )
            return response
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error critiquing chapters chapter_keys=%s "
                    "for study cards agent",
                    keys,
                )
                raise
            self.logger.exception(
                "Error critiquing chapters chapter_keys=%s "
                "for study cards agent",
                keys,
            )
            return None
