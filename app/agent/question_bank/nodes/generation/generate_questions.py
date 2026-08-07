from asyncio import TaskGroup
from logging import Logger

from app.agent.question_bank.edges import chapters_needing_generation
from app.agent.question_bank.prompts import generate_chapter_questions_prompt
from app.agent.question_bank.schema import ChapterQuestionBank, QuestionBankCritique
from app.agent.question_bank.state import QuestionBankState
from app.core.elasticsearch_schema import IndexedRecord
from app.utils.llm import is_rate_limit_error
from langchain_google_genai import ChatGoogleGenerativeAI


class GenerateQuestionsNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(ChapterQuestionBank)

    async def __call__(self, state: QuestionBankState) -> dict:
        chapter_records = state.get("chapter_records") or {}
        generated_chapters = dict(state.get("generated_chapters") or {})
        skipped_critique = set(state.get("skipped_critique_chapters") or [])
        critique = state.get("critique") or {}
        retry_count = state.get("retry_count") or {"generate": 0, "critique": 0}

        chapter_keys_to_generate = [
            chapter_key
            for chapter_key in chapters_needing_generation(state)
            if chapter_key not in skipped_critique
            and chapter_key in chapter_records
        ]

        if not chapter_keys_to_generate:
            self.logger.info(
                "No chapters to generate questions for document_id=%s "
                "user_id=%s for question agent",
                state["document_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Generate questions node started document_id=%s user_id=%s "
            "chapters=%s retry_count=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(chapter_keys_to_generate),
            retry_count["generate"],
        )

        async with TaskGroup() as tg:
            tasks = {
                chapter_key: tg.create_task(
                    self.generate_questions(
                        chapter_key,
                        chapter_records[chapter_key],
                        self._critique_comment(critique, chapter_key),
                        self._previous_draft(generated_chapters, chapter_key),
                    )
                )
                for chapter_key in chapter_keys_to_generate
            }

        newly_skipped: list[str] = []
        for chapter_key, task in tasks.items():
            result = task.result()
            if result is None:
                newly_skipped.append(chapter_key)
            else:
                generated_chapters[result.chapter_key] = result

        self.logger.info(
            "Generate questions node completed document_id=%s user_id=%s "
            "generated_chapters=%s skipped=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(generated_chapters),
            len(newly_skipped),
        )

        return {
            "generated_chapters": generated_chapters,
            "skipped_generated_chapters": newly_skipped,
            "retry_count": {
                "generate": retry_count["generate"] + 1,
                "critique": retry_count["critique"],
            },
        }

    async def generate_questions(
        self,
        chapter_key: str,
        section: list[IndexedRecord],
        critique_comment: str | None = None,
        previous_draft: str | None = None,
    ) -> ChapterQuestionBank | None:
        content = "\n".join(record.content for record in section)
        self.logger.info(
            "Generating questions chapter_key=%s content_len=%s "
            "has_critique=%s has_previous_draft=%s for question agent",
            chapter_key,
            len(content),
            bool(critique_comment),
            bool(previous_draft),
        )

        try:
            response = await self.model.ainvoke(
                generate_chapter_questions_prompt(
                    chapter_key,
                    content,
                    critique_comment,
                    previous_draft,
                )
            )
            result = response.model_copy(update={"chapter_key": chapter_key})
            self.logger.info(
                "Generated questions chapter_key=%s count=%s "
                "for question agent",
                chapter_key,
                len(result.questions),
            )
            return result
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error generating questions "
                    "chapter_key=%s for question agent",
                    chapter_key,
                )
                raise
            self.logger.exception(
                "Error generating questions chapter_key=%s "
                "for question agent",
                chapter_key,
            )
            return None

    @staticmethod
    def _critique_comment(
        critique: dict[str, QuestionBankCritique],
        chapter_key: str,
    ) -> str | None:
        entry = critique.get(chapter_key)
        if entry is None:
            return None
        comments = [
            f"Q{i + 1}: {item.critique}"
            for i, item in enumerate(entry.questions)
            if item.critique
        ]
        if not comments:
            return None
        return "\n".join(comments)

    @staticmethod
    def _previous_draft(
        generated_chapters: dict[str, ChapterQuestionBank],
        chapter_key: str,
    ) -> str | None:
        chapter = generated_chapters.get(chapter_key)
        if chapter is None:
            return None
        return chapter.model_dump_json()
