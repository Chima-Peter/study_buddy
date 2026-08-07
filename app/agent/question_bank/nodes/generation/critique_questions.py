from asyncio import TaskGroup
from logging import Logger

from app.agent.question_bank.prompts import critique_chapter_questions_prompt
from app.agent.question_bank.schema import ChapterQuestionBank, QuestionBankCritique
from app.agent.question_bank.state import QuestionBankState
from app.core.elasticsearch_schema import IndexedRecord
from app.utils.llm import is_rate_limit_error
from langchain_google_genai import ChatGoogleGenerativeAI


class CritiqueQuestionsNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(QuestionBankCritique)

    async def __call__(self, state: QuestionBankState) -> dict:
        generated_chapters = state.get("generated_chapters") or {}
        chapter_records = state.get("chapter_records") or {}
        approved = set(state.get("approved_chapters") or [])
        critique = dict(state.get("critique") or {})

        chapter_keys_to_critique = [
            chapter_key
            for chapter_key in generated_chapters
            if chapter_key not in approved
        ]

        if not generated_chapters:
            self.logger.info(
                "No generated questions to critique document_id=%s "
                "user_id=%s for question agent",
                state["document_id"],
                state["user_id"],
            )
            return {}

        if not chapter_keys_to_critique:
            self.logger.info(
                "No pending questions to critique document_id=%s "
                "user_id=%s for question agent",
                state["document_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Critique questions node started document_id=%s user_id=%s "
            "chapters=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(chapter_keys_to_critique),
        )

        async with TaskGroup() as tg:
            tasks = {
                chapter_key: tg.create_task(
                    self.critique_questions(
                        chapter_key,
                        generated_chapters[chapter_key],
                        chapter_records.get(chapter_key, []),
                    )
                )
                for chapter_key in chapter_keys_to_critique
            }

        newly_approved: list[str] = []
        newly_skipped: list[str] = []
        for chapter_key, task in tasks.items():
            result = task.result()
            if result is None:
                newly_skipped.append(chapter_key)
                continue
            critique[chapter_key] = result
            if self._is_approved(result):
                newly_approved.append(chapter_key)

        self.logger.info(
            "Critique questions node completed document_id=%s user_id=%s "
            "approved=%s skipped=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(newly_approved),
            len(newly_skipped),
        )

        return {
            "critique": critique,
            "approved_chapters": [newly_approved],
            "skipped_critique_chapters": newly_skipped,
        }

    async def critique_questions(
        self,
        chapter_key: str,
        chapter: ChapterQuestionBank,
        source_records: list[IndexedRecord],
    ) -> QuestionBankCritique | None:
        generated_chapter = chapter.model_dump_json()
        source_content = "\n".join(record.content for record in source_records)
        self.logger.info(
            "Critiquing questions chapter_key=%s generated_len=%s "
            "source_len=%s for question agent",
            chapter_key,
            len(generated_chapter),
            len(source_content),
        )

        try:
            result = await self.model.ainvoke(
                critique_chapter_questions_prompt(
                    chapter_key,
                    generated_chapter,
                    source_content,
                )
            )
            return result
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error critiquing questions "
                    "chapter_key=%s for question agent",
                    chapter_key,
                )
                raise
            self.logger.exception(
                "Error critiquing questions chapter_key=%s "
                "for question agent",
                chapter_key,
            )
            return None

    @staticmethod
    def _is_approved(result: QuestionBankCritique) -> bool:
        return all(not item.critique for item in result.questions)
