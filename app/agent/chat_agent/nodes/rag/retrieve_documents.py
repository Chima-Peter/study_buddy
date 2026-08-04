from logging import Logger

from app.agent.chat_agent.state import AgentState
from app.rag.rag_retriever import RAGRetriever


class RetrieveDocumentsNode:
    def __init__(self, retriever: RAGRetriever, logger: Logger):
        self.retriever = retriever
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["retrieve_rag"]:
            self.logger.info(
                "Retrieve documents node skipped user_id=%s",
                state["user_id"],
            )
            return {"rag_documents": []}

        self.logger.info(
            "Retrieve documents node started user_id=%s chapter_keys=%s",
            state["user_id"],
            state.get("chapter_keys"),
        )
        results = await self.retriever.retrieve(
            user_id=state["user_id"],
            query=state["rewritten_query"],
            document_ids=state.get("document_ids"),
            chapter_keys=state.get("chapter_keys"),
        )

        self.logger.info(
            "Retrieve documents node completed user_id=%s count=%s",
            state["user_id"],
            len(results),
        )
        return {"rag_documents": results}
