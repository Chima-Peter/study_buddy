from asyncio import TaskGroup
from logging import Logger

from app.agent.study_cards_agent.prompts import critique_chapter_prompt
from app.agent.study_cards_agent.schema import ChapterResult, Critique
from app.agent.study_cards_agent.state import StudyCardsState
from app.core.elasticsearch_schema import IndexedRecord
from app.utils.llm import is_rate_limit_error
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
                "missing_chapters=%s for quiz bank agent",
                state["document_id"],
                state["user_id"],
                missing_chapters,
            )

        if not generated_chapters:
            self.logger.info(
                "No generated chapters to critique document_id=%s user_id=%s "
                "for quiz bank agent",
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
            "chapters=%s retry_count=%s for quiz bank agent",
            state["document_id"],
            state["user_id"],
            len(generated_chapters),
            retry_count["critique"],
        )

        async with TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self.critique_chapter(
                        chapter_key,
                        chapter,
                        document_sections.get(chapter_key, []),
                    )
                )
                for chapter_key, chapter in generated_chapters.items()
                if chapter_key in chapter_keys_to_critique
            ]

        for task in tasks:
            result = task.result()
            if result is None:
                continue
            critique[result.chapter_key] = result
            if result.status == "approved":
                newly_approved_chapters.append(result.chapter_key)
            else:
                pending_chapters.append(result.chapter_key)

        completed_keys = [
            task.result().chapter_key
            for task in tasks
            if task.result() is not None
        ]
        for chapter_key in chapter_keys_to_critique:
            if chapter_key not in completed_keys:
                undone_critique_chapters.append(chapter_key)

        self.logger.info(
            "Critique node completed document_id=%s user_id=%s "
            "approved=%s pending=%s missing=%s for quiz bank agent",
            state["document_id"],
            state["user_id"],
            len(newly_approved_chapters),
            len(pending_chapters),
            len(missing_chapters),
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

    async def critique_chapter(
        self,
        chapter_key: str,
        chapter: ChapterResult,
        source_records: list[IndexedRecord],
    ) -> Critique | None:
        generated_chapter = chapter.model_dump_json()
        source_content = "\n".join(record.content for record in source_records)
        self.logger.info(
            "Critiquing chapter chapter_key=%s generated_len=%s source_len=%s "
            "for quiz bank agent",
            chapter_key,
            len(generated_chapter),
            len(source_content),
        )

        try:
            response = await self.model.ainvoke(
                critique_chapter_prompt(
                    chapter_key,
                    generated_chapter,
                    source_content,
                )
            )
            result = response.model_copy(update={"chapter_key": chapter_key})
            self.logger.info(
                "Critiqued chapter chapter_key=%s status=%s for quiz bank agent",
                chapter_key,
                result.status,
            )
            return result
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error critiquing chapter chapter_key=%s "
                    "for quiz bank agent",
                    chapter_key,
                )
                raise e
            self.logger.exception(
                "Error critiquing chapter chapter_key=%s for quiz bank agent",
                chapter_key,
            )
            return None
