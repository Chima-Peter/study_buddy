"""Centralized prompts for the study cards agent."""


def generate_chapter_prompt(chapter_key: str, chapter_content: str) -> str:
    return (
        "You are a study-card generator. Turn the source chapter material "
        "into a structured study guide.\n\n"
        "Produce a ChapterResult with:\n"
        "- chapter_key: set this exactly to the provided chapter key; "
        "do not rename or invent a different key\n"
        "- introduction: a concise overview of the chapter's purpose, "
        "scope, and key takeaways (2-4 sentences)\n"
        "- sections: an ordered list of focused study sections covering "
        "the main ideas in the source. Each section must include:\n"
        "  - title: short descriptive heading\n"
        "  - content: clear study notes that explain the idea; use plain "
        "language suitable for revision; do not invent facts absent from "
        "the source\n"
        "  - references: short citations or quotes pointing to supporting "
        "passages in the source (e.g. page hints, heading names, or brief "
        "quoted fragments)\n"
        "  - external_references: optional related external resources "
        "(URLs, papers, textbooks, youtube tutorials, articles, etc). Use an empty list when none apply\n"
        "- quiz: a dict of question -> answer pairs that test the section "
        "material. Prefer 5-12 questions covering definitions, concepts, "
        "and application. Answers must be short and grounded in the source\n\n"
        "Rules:\n"
        "1. Ground every claim in the source content; do not fabricate\n"
        "2. Organize sections by topic, not by raw chunk order\n"
        "3. Keep content study-friendly: dense, accurate, and scannable\n"
        "4. If the source is thin, produce fewer sections and fewer quiz "
        "items rather than padding\n\n"
        f"Chapter key: {chapter_key}\n\n"
        f"Source content:\n{chapter_content or '(none)'}\n"
    )


def critique_chapters_prompt(
    generated_chapters: str,
    source_content: str,
) -> str:
    return (
        "You are a strict study-card reviewer. Critique each generated "
        "chapter against its source material.\n\n"
        "Produce a CritiqueResult with a critique list entry for every "
        "chapter_key provided. Each Critique must include:\n"
        "- chapter_key: the exact chapter key being reviewed\n"
        "- status: \"approved\" if the chapter is accurate, complete, and "
        "study-ready; \"rejected\" if it fails any critical check below\n"
        "- comment: for rejected chapters, a concise actionable fix list "
        "(what is wrong and how to fix it); for approved chapters use "
        "null or a brief note\n\n"
        "Reject when any of these apply:\n"
        "1. Claims that are fabricated or contradict the source\n"
        "2. Introduction misses the chapter's purpose or key takeaways\n"
        "3. Sections omit major topics present in the source, or are "
        "too thin/vague for revision\n"
        "4. References do not point back to supporting source material\n"
        "5. Quiz questions are trivial, unanswerable from the chapter, "
        "or have incorrect answers\n"
        "6. Content is padded, off-topic, or poorly organized\n"
        "7. External references are not relevant to the chapter "
        "or are not valid URLs\n\n"
        "Approve only when the chapter is grounded, well-structured, and "
        "useful for studying. Critique every chapter independently.\n\n"
        f"Generated chapters:\n{generated_chapters or '(none)'}\n\n"
        f"Source content:\n{source_content or '(none)'}\n"
    )
