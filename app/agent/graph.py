from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from app.agent.edges import (
    update_summary_router,
    update_title_router,
)
from app.agent.nodes import (
    CleanupNode,
    GenerateResponseNode,
    RetrievalDeciderNode,
    RetrieveConversationHistoryNode,
    RetrieveDocumentsNode,
    RewriteQueryNode,
    SaveChatNode,
    UpdateConversationSummaryNode,
    UpdateConversationTitleNode,
)
from app.agent.state import AgentState
from langgraph.graph import START, StateGraph, END
from logging import Logger
from app.rag.rag_retriever import RAGRetriever
from app.system.service.chat import ChatService
from app.system.service.conversation import ConversationService

class AgentGraph:
    def __init__(
        self,
        retriever: RAGRetriever,
        conversation_service: ConversationService,
        chat_model: ChatGoogleGenerativeAI,
        query_model: ChatGoogleGenerativeAI,
        summarizer_model: ChatGoogleGenerativeAI,
        chat_service: ChatService,
        logger: Logger,
        checkpointer: AsyncPostgresSaver,
    ):
        self.retriever = retriever
        self.conversation_service = conversation_service
        self.chat_service = chat_service
        self.logger = logger
        self.chat_model = chat_model
        self.query_model = query_model
        self.summarizer_model = summarizer_model
        self.checkpointer = checkpointer
        graph = StateGraph(AgentState)

        graph.add_node("retrieval_decider", RetrievalDeciderNode(
            model=self.query_model,
            logger=self.logger,
        ))
        graph.add_node("rewrite_query", RewriteQueryNode(
            model=self.query_model,
            logger=self.logger,
        ))
        graph.add_node("retrieve_documents", RetrieveDocumentsNode(
            retriever=self.retriever,
            logger=self.logger,
        ))
        graph.add_node("retrieve_conversation_history", RetrieveConversationHistoryNode(
            conversation_service=self.conversation_service,
            logger=self.logger,
        ))
        graph.add_node("generate_response", GenerateResponseNode(
            model=self.chat_model,
            logger=self.logger,
        ))
        graph.add_node("save_chat", SaveChatNode(
            chat_service=self.chat_service,
            logger=self.logger,
        ))
        graph.add_node("update_conversation_title", UpdateConversationTitleNode(
            conversation_service=self.conversation_service,
            model=self.summarizer_model,
            logger=self.logger,
        ))
        graph.add_node("update_conversation_summary", UpdateConversationSummaryNode(
            conversation_service=self.conversation_service,
            model=self.summarizer_model,
            logger=self.logger,
        ))
        graph.add_node("cleanup", CleanupNode(logger=self.logger))

        graph.add_edge(START, "retrieval_decider")
        graph.add_edge("retrieval_decider", "rewrite_query")
        graph.add_edge("retrieval_decider", "retrieve_conversation_history")
        graph.add_edge("rewrite_query", "retrieve_documents")
        graph.add_edge(
            ["retrieve_documents", "retrieve_conversation_history"],
            "generate_response",
        )
        graph.add_edge("generate_response", "save_chat")
        graph.add_conditional_edges(
            "generate_response",
            update_title_router,
            {
                "update_title": "update_conversation_title",
                "cleanup": "cleanup",
            },
        )
        graph.add_conditional_edges(
            "save_chat",
            update_summary_router,
            {
                "update_summary": "update_conversation_summary",
                "cleanup": "cleanup",
            },
        )
        graph.add_edge("update_conversation_summary", "cleanup")
        graph.add_edge("update_conversation_title", "cleanup")
        graph.add_edge("cleanup", END)

        self.graph = graph.compile(checkpointer=self.checkpointer)

    def start(self) -> CompiledStateGraph:
        return self.graph