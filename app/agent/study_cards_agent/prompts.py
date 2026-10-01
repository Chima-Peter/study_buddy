"""Centralized prompts for the study cards agent."""

NON_MAIN_CHAPTERS = (
    "references, bibliography, introduction, preface, foreword, conclusion, "
    "appendix, acknowledgements, index, table of contents, glossary, about "
    "the author, dedication, abstract, summary, endnotes, list of "
    "figures/tables, abbreviations, acronyms, or any other auxiliary/meta "
    "chapter"
)

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
    "  - references: short internal citations pointing to supporting "
    "passages in the source. When Source content includes labels like "
    "[Chapter N: … | Page X] or [Page X], include those page (and chapter) "
    "numbers for the passages that support the section. You may also use "
    "heading names or brief quoted fragments alongside page refs. "
    "Use an empty list only when the source has no usable location hints\n"
    "  - external_references: related external resources drawn from "
    "Additional Links when provided (prefer those URLs/titles). "
    "Use an empty list when Additional Links is (none) or none apply. "
    "Every entry must be a real URL from Additional Links or an accurately "
    "named resource tied to that link. Do not invent or guess links\n"
    "- mnemonics: a dict of short memorable memory aids "
    "(key = concept or section title, value = the mnemonic text).\n"
    "  For main/substantive learning chapters: include at least one unique "
    "mnemonic per section. Each mnemonic must be distinct; never reuse the "
    "same mnemonic twice.\n"
    "  For non-main chapters that lack substantive learning content, "
    f"use an empty mnemonics object {{}}. This includes: {NON_MAIN_CHAPTERS}\n"
    "- quiz: a list of multiple-choice questions that test the chapter "
    "material. Prefer 5-12 questions covering definitions, concepts, "
    "and application. Each quiz item must include:\n"
    "  - question: the question text\n"
    "  - options: 3-5 plausible answer choices (strings)\n"
    "  - correct_option_index: 0-based index of the correct choice in "
    "options. Must be in range and grounded in the source.\n"
    "  For non-main chapters that lack substantive learning content, "
    "use an empty quiz list []. "
    f"This includes: {NON_MAIN_CHAPTERS}\n\n"
    "Style rules (main/substantive learning chapters only; "
    "non-main chapters listed above are exempt — keep them plain and "
    "factual, with empty quiz and empty mnemonics):\n"
    "1. Explain concepts in a fun, memorable way throughout section "
    "content and the introduction: light humor, vivid "
    "illustrations/analogies for hard ideas, and the required mnemonics\n"
    "2. Prefer light, playful humor and short everyday analogies "
    "(sports, cooking, traffic, school life, simple games). "
    "Do NOT use heavy historical/empire/colonial metaphors or the same "
    "grand theme repeated across sections\n"
    "3. Each analogy or joke must be unique within the chapter and "
    "tied to its specific concept — do not recycle one metaphor for "
    "multiple topics\n"
    "4. Mnemonics must be easy to catch and stick; one per section "
    "minimum; never duplicate a mnemonic\n\n"
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
    "6. Quiz questions must be answerable from the chapter; each must "
    "have exactly one correct option at correct_option_index; distractors "
    "should be plausible but wrong; avoid trivial questions\n"
    "7. When page labels appear in Source content, section references "
    "must mention those pages where applicable\n"
    "8. External references must come from Additional Links when present; "
    "prefer an empty list over invented or broken links\n"
)


def generate_chapters_prompt(
    chapters: list[dict],
    learning_preferences: list[str] | None = None,
) -> str:
    """Build one prompt that requests a StudyCardsResult for the given chapters.

    Each item in ``chapters`` is a dict with:
    - chapter_key: str
    - content: str
    - tavily_results: str
    - critique_comment: str | None (optional)
    - previous_draft: str | None (optional)
    """
    preferences_section = ""
    if learning_preferences:
        prefs = "\n".join(f"- {pref}" for pref in learning_preferences)
        preferences_section = (
            "User learning preferences (adapt your communication style, "
            "examples, and explanations accordingly):\n"
            f"{prefs}\n\n"
        )

    chapter_blocks: list[str] = []
    keys: list[str] = []
    for chapter in chapters:
        chapter_key = chapter["chapter_key"]
        keys.append(chapter_key)
        revision_section = ""
        critique_comment = chapter.get("critique_comment")
        previous_draft = chapter.get("previous_draft")
        if critique_comment and previous_draft:
            revision_section = (
                "You are revising a rejected draft for this chapter. "
                "Fix the issues below.\n\n"
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

        chapter_blocks.append(
            f"=== Chapter key: {chapter_key} ===\n"
            f"{revision_section}"
            f"Source content:\n{chapter.get('content') or '(none)'}\n\n"
            f"Additional Links:\n{chapter.get('tavily_results') or '(none)'}\n"
        )

    keys_list = ", ".join(keys)
    return (
        "You are a study-card generator. Turn each source chapter below "
        "into a structured study guide.\n\n"
        f"{preferences_section}"
        "Produce a StudyCardsResult whose chapters list has exactly one "
        "ChapterResult for each of these chapter keys "
        f"(and no extras): {keys_list}.\n"
        "Each ChapterResult must meet all of the following.\n\n"
        f"{CHAPTER_REQUIREMENTS}\n"
        + "\n".join(chapter_blocks)
    )


def critique_chapters_prompt(chapters: list[dict]) -> str:
    """Build one prompt that requests a CritiqueResult for the given chapters.

    Each item in ``chapters`` is a dict with:
    - chapter_key: str
    - generated_chapter: str
    - source_content: str
    - tavily_results: str
    """
    keys = [chapter["chapter_key"] for chapter in chapters]
    keys_list = ", ".join(keys)
    chapter_blocks: list[str] = []
    for chapter in chapters:
        chapter_blocks.append(
            f"=== Chapter key: {chapter['chapter_key']} ===\n"
            f"Generated chapter:\n"
            f"{chapter.get('generated_chapter') or '(none)'}\n\n"
            f"Source content:\n{chapter.get('source_content') or '(none)'}\n\n"
            f"Additional Links:\n{chapter.get('tavily_results') or '(none)'}\n"
        )

    return (
        "You are a strict study-card reviewer. Critique each generated "
        "chapter against its source material using the same requirements "
        "the generator was given.\n\n"
        "Produce a CritiqueResult whose critiques list has exactly one "
        "Critique for each of these chapter keys "
        f"(and no extras): {keys_list}.\n"
        "Each Critique must include:\n"
        "- chapter_key: set this exactly to the provided chapter key\n"
        "- status: \"approved\" if the chapter meets every requirement "
        "below; \"rejected\" if it fails any of them\n"
        "- comment: for rejected, a concise actionable fix list keyed to "
        "the failed requirements (what is wrong and how to fix it); "
        "for approved use null or a brief note\n\n"
        f"{CHAPTER_REQUIREMENTS}\n"
        "Reject if any requirement above is violated. Approve only when "
        "all requirements are met. For main chapters, also reject when "
        "style rules fail (missing per-section mnemonics, reused "
        "metaphors/mnemonics, heavy empire/colonial themes, or dry "
        "content with no light humor/analogies). For non-main chapters, "
        "reject if quiz or mnemonics are non-empty. Reject invented "
        "external links that are not in Additional Links. Reject when "
        "Source content has page labels but section references omit them "
        "where they clearly apply.\n\n"
        + "\n".join(chapter_blocks)
    )
