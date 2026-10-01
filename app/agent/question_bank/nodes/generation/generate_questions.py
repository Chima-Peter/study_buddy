from logging import Logger

from app.agent.question_bank.edges import chapters_needing_generation
from app.agent.question_bank.prompts import generate_chapters_questions_prompt
from app.agent.question_bank.schema import (
    ChapterQuestionBank,
    QuestionBankCritique,
    QuestionBankResult,
)
from app.agent.question_bank.state import QuestionBankState
from app.utils.llm import is_rate_limit_error, with_rate_limit_retry
from langchain_google_genai import ChatGoogleGenerativeAI


class GenerateQuestionsNode:
    def __init__(self, logger: Logger, model: ChatGoogleGenerativeAI):
        self.logger = logger
        self.model = model.with_structured_output(QuestionBankResult)

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

        chapter_inputs = [
            {
                "chapter_key": chapter_key,
                "content": "\n".join(
                    record.content for record in chapter_records[chapter_key]
                ),
                "critique_comment": self._critique_comment(critique, chapter_key),
                "previous_draft": self._previous_draft(
                    generated_chapters, chapter_key
                ),
            }
            for chapter_key in chapter_keys_to_generate
        ]

        expected_keys = set(chapter_keys_to_generate)
        result = await self.generate_questions(chapter_inputs, expected_keys)
        newly_skipped = [
            chapter_key
            for chapter_key in chapter_keys_to_generate
            if result is None
            or chapter_key not in {c.chapter_key for c in result.chapters}
        ]
        if result is not None:
            for chapter in result.chapters:
                generated_chapters[chapter.chapter_key] = chapter

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
        chapters: list[dict],
        expected_keys: set[str] | None = None,
    ) -> QuestionBankResult | None:
        keys = [chapter["chapter_key"] for chapter in chapters]
        self.logger.info(
            "Generating questions chapter_keys=%s count=%s for question agent",
            keys,
            len(chapters),
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(
                    generate_chapters_questions_prompt(chapters)
                ),
                logger=self.logger,
                label=f"question bank generate chapters={keys}",
            )
            if expected_keys is not None:
                response = QuestionBankResult(
                    chapters=[
                        chapter
                        for chapter in response.chapters
                        if chapter.chapter_key in expected_keys
                    ]
                )

            self.logger.info(
                "Generated questions returned=%s expected=%s "
                "for question agent",
                [c.chapter_key for c in response.chapters],
                keys,
            )
            return response
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rate limit error generating questions "
                    "chapter_keys=%s for question agent",
                    keys,
                )
                raise
            self.logger.exception(
                "Error generating questions chapter_keys=%s "
                "for question agent",
                keys,
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
