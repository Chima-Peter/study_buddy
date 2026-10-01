import asyncio
from logging import Logger

from app.agent.question_bank.prompts import critique_chapter_questions_prompt
from app.agent.question_bank.schema import QuestionBankCritique
from app.agent.question_bank.state import QuestionBankState
from app.agent.question_bank.utils import is_critique_approved
from app.utils.llm import is_rate_limit_error, with_rate_limit_retry
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
        retry_count = state.get("retry_count") or {"generate": 0, "critique": 0}

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
            return {
                "skipped_critique_chapters": [],
                "retry_count": {
                    "critique": retry_count["critique"] + 1,
                    "generate": retry_count["generate"],
                },
            }

        if not chapter_keys_to_critique:
            self.logger.info(
                "No pending questions to critique document_id=%s "
                "user_id=%s for question agent",
                state["document_id"],
                state["user_id"],
            )
            return {
                "skipped_critique_chapters": [],
                "retry_count": {
                    "critique": retry_count["critique"] + 1,
                    "generate": retry_count["generate"],
                },
            }

        self.logger.info(
            "Critique questions node started document_id=%s user_id=%s "
            "chapters=%s retry_count=%s for question agent",
            state["document_id"],
            state["user_id"],
            len(chapter_keys_to_critique),
            retry_count["critique"],
        )

        chapter_inputs = [
            {
                "chapter_key": chapter_key,
                "generated_chapter": generated_chapters[
                    chapter_key
                ].model_dump_json(),
                "source_content": "\n".join(
                    record.content
                    for record in chapter_records.get(chapter_key, [])
                ),
            }
            for chapter_key in chapter_keys_to_critique
        ]

        results = await asyncio.gather(
            *[self.critique_questions(chapter) for chapter in chapter_inputs],
            return_exceptions=True,
        )

        newly_approved: list[str] = []
        newly_skipped: list[str] = []
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
            if is_critique_approved(entry):
                newly_approved.append(entry.chapter_key)

        for chapter_key in chapter_keys_to_critique:
            if chapter_key not in completed_keys:
                newly_skipped.append(chapter_key)

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
            "approved_chapters": newly_approved,
            "skipped_critique_chapters": newly_skipped,
            "retry_count": {
                "critique": retry_count["critique"] + 1,
                "generate": retry_count["generate"],
            },
        }

    async def critique_questions(
        self,
        chapter: dict,
    ) -> QuestionBankCritique | None:
        chapter_key = chapter["chapter_key"]
        self.logger.info(
            "Critiquing questions chapter_key=%s for question agent",
            chapter_key,
        )

        try:
            response = await with_rate_limit_retry(
                lambda: self.model.ainvoke(
                    critique_chapter_questions_prompt(chapter)
                ),
                logger=self.logger,
                label=f"question bank critique chapter={chapter_key}",
            )
            if response.chapter_key != chapter_key:
                self.logger.warning(
                    "Critique questions key mismatch expected=%s got=%s "
                    "for question agent",
                    chapter_key,
                    response.chapter_key,
                )
                return None

            self.logger.info(
                "Critiqued questions chapter_key=%s for question agent",
                chapter_key,
            )
            return response
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
