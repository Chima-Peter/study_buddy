from logging import Logger

from app.agent.state import AgentState
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
            "Retrieve documents node started user_id=%s",
            state["user_id"],
        )
        results = await self.retriever.retrieve(
            user_id=state["user_id"],
            query=state["rewritten_query"],
            document_id=state.get("document_id"),
        )

        self.logger.info(
            "Retrieve documents node completed user_id=%s count=%s",
            state["user_id"],
            len(results),
        )
        return {"rag_documents": results}
