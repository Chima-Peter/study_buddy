"""Centralized prompts for the question bank agent."""

NON_MAIN_CHAPTERS = (
    "references, bibliography, introduction, preface, foreword, conclusion, "
    "appendix, acknowledgements, index, table of contents, glossary, about "
    "the author, dedication, abstract, summary, endnotes, list of "
    "figures/tables, abbreviations, acronyms, or any other auxiliary/meta "
    "chapter"
)

CHAPTER_QUESTION_REQUIREMENTS = (
    "ChapterQuestionBank requirements:\n"
    "- chapter_key: must match the provided chapter key exactly; "
    "do not rename or invent a different key\n"
    "- questions: a list of multiple-choice QuestionSchema items that "
    "assess the chapter material. For main/substantive learning "
    "chapters produce at least 10 and at most 150 questions, covering "
    "definitions, concepts, comparisons, and application. Mix "
    "difficulties. Scale toward the upper end only when the source is "
    "rich enough; never pad to hit a count. "
    "For non-main chapters that lack substantive learning content, "
    "use an empty questions list []. "
    f"This includes: {NON_MAIN_CHAPTERS}\n\n"
    "Each QuestionSchema item must include:\n"
    "- question: clear, unambiguous stem answerable from the source; "
    "avoid trick wording and trivia unrelated to the chapter\n"
    "- options: 3–5 plausible answer choices (strings). Exactly one "
    "option must be correct; distractors must be wrong but believable\n"
    "- correct_option_index: 0-based index of the correct choice in "
    "options; must be in range and grounded in the source\n"
    "- explanation: a short, accurate rationale for why the correct "
    "option is right (and briefly why common distractors fail when "
    "helpful). Must not invent facts absent from the source\n"
    "- difficulty: one of \"easy\", \"medium\", or \"hard\". "
    "Across the chapter, include a mix (roughly easy / medium / hard)\n"
    "- internal_references: short citations or quotes pointing to "
    "supporting passages in the source (e.g. page hints, heading "
    "names, or brief quoted fragments). Prefer at least one when the "
    "source supports it; use [] only if truly none apply\n"
    "- external_references: optional related external resources "
    "(URLs, papers, textbooks, articles, etc). Use [] when none "
    "apply. Every link or resource must be correct, directly related "
    "to the tested material, and valid. Do not invent or guess links\n\n"
    "Quality rules:\n"
    "1. Ground every question, correct answer, and explanation in the "
    "source; do not fabricate or contradict the source\n"
    "2. Cover major topics present in the source; do not cluster all "
    "questions on a single minor detail\n"
    "3. Each question must have exactly one correct option at "
    "correct_option_index; distractors must be plausible but wrong\n"
    "4. Prefer application and understanding over rote recall when the "
    "source supports it; avoid trivial yes/no or pure wording tricks\n"
    "5. Stay within 10–150 questions for main chapters. If the source "
    "is thin, stay near the minimum of 10 rather than padding, "
    "off-topic, or vague items; never exceed 150 questions\n"
    "6. Questions within a chapter must be distinct; do not paraphrase "
    "the same stem repeatedly\n"
    "7. External references must be correct, related, and valid; "
    "prefer an empty list over invented or broken links\n"
)


def generate_chapter_questions_prompt(
    chapter_key: str,
    chapter_content: str,
    critique_comment: str | None = None,
    previous_draft: str | None = None,
) -> str:
    revision_section = ""
    if critique_comment and previous_draft:
        revision_section = (
            "You are revising a rejected draft. Fix the issues below.\n\n"
            "Previous draft:\n"
            f"{previous_draft}\n\n"
            "Critique (fix these issues):\n"
            f"{critique_comment}\n\n"
            "Address every point in the critique. Keep what was correct, "
            "fix what was wrong.\n\n"
        )
    elif critique_comment:
        revision_section = (
            "Previous critique (fix these issues in the new draft):\n"
            f"{critique_comment}\n\n"
            "Address every point in the critique while still obeying the "
            "requirements below. Do not ignore the feedback.\n\n"
        )

    return (
        "You are a question-bank generator. Turn the source chapter "
        "material into a structured multiple-choice question bank.\n\n"
        f"{revision_section}"
        "Produce a ChapterQuestionBank that meets all of the following.\n\n"
        f"{CHAPTER_QUESTION_REQUIREMENTS}\n"
        f"Chapter key: {chapter_key}\n\n"
        f"Source content:\n{chapter_content or '(none)'}\n"
    )


def critique_chapter_questions_prompt(
    chapter_key: str,
    generated_chapter: str,
    source_content: str,
) -> str:
    return (
        "You are a strict question-bank reviewer. Critique the generated "
        "chapter question bank against its source material using the same "
        "requirements the generator was given.\n\n"
        "Produce a QuestionBankCritique with:\n"
        "- questions: one QuestionCritique entry per generated question, "
        "in the same order as the draft. Each entry must include:\n"
        "  - question: the QuestionSchema under review, copied as-is "
        "(do not silently rewrite it here)\n"
        "  - critique: empty string \"\" if that question meets every "
        "requirement; otherwise a concise actionable fix describing what "
        "is wrong and how to fix it (keyed to failed requirements)\n\n"
        "Chapter-level failures (wrong chapter_key, fewer than 10 "
        "or more than 150 questions on a main/substantive chapter, empty "
        "questions on a main chapter, non-empty questions on a non-main "
        "chapter, severe coverage gaps, or duplicate stems across the "
        "set) must be stated in the critique string of the first "
        "QuestionCritique entry. If the draft has no questions but "
        "should for a main chapter, return a single QuestionCritique "
        "with a minimal placeholder question (empty options, "
        "correct_option_index 0, empty explanation/refs, difficulty "
        "\"easy\") and put the chapter-level rejection in critique.\n\n"
        "Approve a question only when its critique string is empty. "
        "Reject (non-empty critique) when any requirement fails — "
        "including wrong correct_option_index, invented facts, invalid "
        "difficulty, missing/bogus references, or weak distractors.\n\n"
        f"{CHAPTER_QUESTION_REQUIREMENTS}\n"
        "Reject any question that violates a requirement above. Approve "
        "only when all of its requirements are met. For non-main "
        "chapters, reject if questions is non-empty.\n\n"
        f"Chapter key: {chapter_key}\n\n"
        f"Generated chapter question bank:\n"
        f"{generated_chapter or '(none)'}\n\n"
        f"Source content:\n{source_content or '(none)'}\n"
    )

