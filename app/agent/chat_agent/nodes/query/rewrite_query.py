from logging import Logger
import re
from typing import TYPE_CHECKING

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.chat_agent.prompts import rewrite_query_prompt
from app.agent.chat_agent.schema import RewriteQueryResponse
from app.agent.chat_agent.state import AgentState
from app.rag.schema import normalize_chapter_key
from app.utils.llm import is_rate_limit_error

if TYPE_CHECKING:
    from app.system.document.service import DocumentService

_CH_ABBREV_RE = re.compile(
    r"^ch(?:apter)?\.?\s*([0-9]+|[ivxlcdm]+)\b(.*)$",
    re.IGNORECASE,
)


def _coerce_chapter_mention(raw: str) -> str:
    text = (raw or "").strip()
    match = _CH_ABBREV_RE.match(text)
    if match:
        rest = (match.group(2) or "").strip(" :.-—–")
        base = f"chapter {match.group(1)}"
        return f"{base}: {rest}" if rest else base
    return text


def _match_section_keys(
    mentions: list[str] | None,
    available: list[str],
) -> list[str] | None:
    """Map model mentions onto chapter_splitter section keys only."""
    if not mentions or not available:
        return None

    by_lower = {key.lower(): key for key in available}
    matched: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key not in seen:
            seen.add(key)
            matched.append(key)

    for raw in mentions:
        text = (raw or "").strip()
        if not text:
            continue

        exact = by_lower.get(text.lower())
        if exact is not None:
            _add(exact)
            continue

        normalized = normalize_chapter_key(_coerce_chapter_mention(text))
        if normalized in by_lower:
            _add(by_lower[normalized])

    return matched or None


def _flatten_section_keys(
    document_ids: list[str],
    document_sections: dict[str, list[str]],
) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for document_id in document_ids:
        for key in document_sections.get(document_id, []):
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


class RewriteQueryNode:
    def __init__(
        self,
        logger: Logger,
        model: ChatGoogleGenerativeAI,
        document_service: "DocumentService",
    ):
        self.logger = logger
        self.model = model
        self.document_service = document_service

    async def __call__(self, state: AgentState) -> AgentState:
        retrieve_rag = state["retrieve_rag"]
        retrieve_memory = state["retrieve_memory"]

        if not retrieve_rag and not retrieve_memory:
            self.logger.info(
                "Rewrite query node skipped id=%s user_id=%s "
                "reason=no_retrieval",
                state["conversation_id"],
                state["user_id"],
            )
            return {
                "rewritten_query": state["query"],
                "memory_query": None,
                "chapter_keys": None,
            }

        document_sections = dict(state.get("document_sections") or {})
        if retrieve_rag:
            document_ids = state.get("document_ids") or []
            missing_ids = [
                document_id
                for document_id in document_ids
                if document_id not in document_sections
            ]
            if missing_ids:
                try:
                    fetched = await self.document_service.get_sections_by_document(
                        missing_ids,
                        state["user_id"],
                    )
                    document_sections.update(fetched)
                except Exception:
                    self.logger.exception(
                        "Failed loading section keys id=%s user_id=%s",
                        state["conversation_id"],
                        state["user_id"],
                    )
            section_keys = _flatten_section_keys(document_ids, document_sections)
        else:
            section_keys = []

        self.logger.info(
            "Rewrite query node started id=%s user_id=%s "
            "retrieve_rag=%s retrieve_memory=%s section_keys=%s",
            state["conversation_id"],
            state["user_id"],
            retrieve_rag,
            retrieve_memory,
            section_keys,
        )
        recent_history = state["conversation_history"][-3:]
        prompt = rewrite_query_prompt(
            query=state["query"],
            conversation_summary=state["conversation_summary"],
            recent_history=recent_history,
            retrieve_rag=retrieve_rag,
            retrieve_memory=retrieve_memory,
            section_keys=section_keys or None,
        )
        try:
            result: RewriteQueryResponse = (
                await self.model.with_structured_output(
                    RewriteQueryResponse
                ).ainvoke(prompt)
            )
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rewrite query node rate limited id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            else:
                self.logger.exception(
                    "Rewrite query node failed id=%s user_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                )
            return {
                "rewritten_query": state["query"],
                "memory_query": state["query"] if retrieve_memory else None,
                "chapter_keys": None,
                "document_sections": document_sections,
            }

        rewritten = state["query"]
        chapter_keys = None
        if retrieve_rag:
            rewritten = (result.rag_query or "").strip() or state["query"]
            chapter_keys = _match_section_keys(result.chapters, section_keys)

        memory_query = None
        if retrieve_memory:
            memory_query = (result.memory_query or "").strip() or state["query"]

        self.logger.info(
            "Rewrite query node completed id=%s user_id=%s original=%r "
            "rewritten=%r chapter_keys=%s memory_query=%r",
            state["conversation_id"],
            state["user_id"],
            state["query"],
            rewritten,
            chapter_keys,
            memory_query,
        )
        return {
            "rewritten_query": rewritten,
            "memory_query": memory_query,
            "chapter_keys": chapter_keys,
            "document_sections": document_sections,
        }
