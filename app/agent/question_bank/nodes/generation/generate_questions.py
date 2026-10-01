import asyncio
from logging import Logger

from app.agent.question_bank.edges import chapters_needing_generation
from app.agent.question_bank.prompts import generate_chapter_questions_prompt
from app.agent.question_bank.schema import ChapterQuestionBank
from app.agent.question_bank.state import QuestionBankState
from app.agent.question_bank.utils import critique_comment, previous_draft
from app.utils.llm import is_rate_limit_error, with_rate_limit_retry
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

        chapter_inputs = [
            {
                "chapter_key": chapter_key,
                "content": "\n".join(
                    record.content for record in chapter_records[chapter_key]
                ),
                "critique_comment": critique_comment(critique, chapter_key),
                "previous_draft": previous_draft(generated_chapters, chapter_key),
            }
            for chapter_key in chapter_keys_to_generate
        ]

        results = await asyncio.gather(
            *[self.generate_questions(chapter) for chapter in chapter_inputs],
            return_exceptions=True,
        )
        completed_keys: set[str] = set()
        for result in results:
            if isinstance(result, Exception):
                if is_rate_limit_error(result):
                    raise result
                continue
            if result is None:
                continue
            generated_chapters[result.chapter_key] = result
            completed_keys.add(result.chapter_key)

        newly_skipped = [
            chapter_key
            for chapter_key in chapter_keys_to_generate
            if chapter_key not in completed_keys
        ]

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
        chapter: dict,
    ) -> ChapterQuestionBank | None:
        chapter_key = chapter["chapter_key"]
        self.logger.info(
            "Generating questions chapter_key=%s for question agent",
            chapter_key,
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(
                    generate_chapter_questions_prompt(chapter)
                ),
                logger=self.logger,
                label=f"question bank generate chapter={chapter_key}",
            )
            if response.chapter_key != chapter_key:
                self.logger.warning(
                    "Generated questions key mismatch expected=%s got=%s "
                    "for question agent",
                    chapter_key,
                    response.chapter_key,
                )
                return None

            self.logger.info(
                "Generated questions chapter_key=%s for question agent",
                chapter_key,
            )
            return response
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
