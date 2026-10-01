from app.agent.question_bank.schema import (
    ChapterQuestionBank,
    QuestionBankCritique,
)


def critique_comment(
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


def previous_draft(
    generated_chapters: dict[str, ChapterQuestionBank],
    chapter_key: str,
) -> str | None:
    chapter = generated_chapters.get(chapter_key)
    if chapter is None:
        return None
    return chapter.model_dump_json()


def is_critique_approved(result: QuestionBankCritique) -> bool:
    return all(not item.critique for item in result.questions)


def has_rejection(entry: QuestionBankCritique | None) -> bool:
    if entry is None:
        return False
    return any(item.critique for item in entry.questions)
