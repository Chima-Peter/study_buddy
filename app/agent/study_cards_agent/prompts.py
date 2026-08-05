"""Centralized prompts for the study cards agent."""

CHAPTER_REQUIREMENTS = (
    "ChapterResult requirements:\n"
    "- chapter_key: must match the provided chapter key exactly; "
    "do not rename or invent a different key\n"
    "- introduction: a concise overview of the chapter's purpose, "
    "scope, and key takeaways (2-4 sentences)\n"
    "- sections: an ordered list of focused study sections covering "
    "the main ideas in the source. Each section must include:\n"
    "  - title: short descriptive heading\n"
    "  - content: clear study notes in rich Markdown suitable for revision. "
    "Use headings (## / ###), bullet/numbered lists, bold/italic emphasis, "
    "fenced code blocks when useful, and Markdown tables for comparisons, "
    "definitions, formulas, or structured facts. Do not invent facts absent "
    "from the source\n"
    "  - references: short citations or quotes pointing to supporting "
    "passages in the source (e.g. page hints, heading names, or brief "
    "quoted fragments)\n"
    "  - external_references: optional related external resources "
    "(URLs, papers, textbooks, youtube tutorials, articles, etc). "
    "Use an empty list when none apply. Every link or resource must be "
    "correct, directly related to the chapter material, and valid "
    "(real, working URLs or accurately named resources). Do not invent "
    "or guess links\n"
    "- quiz: a dict of question -> answer pairs that test the section "
    "material. Prefer 5-12 questions covering definitions, concepts, "
    "and application. Answers must be short and grounded in the source\n\n"
    "Quality rules:\n"
    "1. Ground every claim in the source content; do not fabricate or "
    "contradict the source\n"
    "2. Organize sections by topic, not by raw chunk order\n"
    "3. Keep content study-friendly and richly formatted in Markdown: "
    "dense, accurate, scannable, with headings and tables where they aid "
    "understanding; avoid bare plain-text walls\n"
    "4. Cover major topics present in the source; do not omit them\n"
    "5. If the source is thin, produce fewer sections and fewer quiz "
    "items rather than padding, off-topic, or vague content\n"
    "6. Quiz questions must be answerable from the chapter and have "
    "correct answers; avoid trivial questions\n"
    "7. External references must be correct, related to the material, "
    "and valid; prefer an empty list over invented or broken links\n"
)


def generate_chapter_prompt(
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
        "You are a study-card generator. Turn the source chapter material "
        "into a structured study guide.\n\n"
        f"{revision_section}"
        f"Produce a ChapterResult that meets all of the following.\n\n"
        f"{CHAPTER_REQUIREMENTS}\n"
        f"Chapter key: {chapter_key}\n\n"
        f"Source content:\n{chapter_content or '(none)'}\n"
    )


def critique_chapter_prompt(
    chapter_key: str,
    generated_chapter: str,
    source_content: str,
) -> str:
    return (
        "You are a strict study-card reviewer. Critique the generated "
        "chapter against its source material using the same requirements "
        "the generator was given.\n\n"
        "Produce a Critique with:\n"
        "- chapter_key: set this exactly to the provided chapter key\n"
        "- status: \"approved\" if the chapter meets every requirement "
        "below; \"rejected\" if it fails any of them\n"
        "- comment: for rejected, a concise actionable fix list keyed to "
        "the failed requirements (what is wrong and how to fix it); "
        "for approved use null or a brief note\n\n"
        f"{CHAPTER_REQUIREMENTS}\n"
        "Reject if any requirement above is violated. Approve only when "
        "all requirements are met.\n\n"
        f"Chapter key: {chapter_key}\n\n"
        f"Generated chapter:\n{generated_chapter or '(none)'}\n\n"
        f"Source content:\n{source_content or '(none)'}\n"
    )
