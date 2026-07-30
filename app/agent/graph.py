from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph.state import CompiledStateGraph
from app.agent.edges import (
    create_conversation_router,
    update_summary_router,
    update_title_router,
)
from app.agent.nodes import (
    CreateConversationNode,
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
from app.rag.retriever import RAGRetriever
from app.system.service.chat import ChatService
from app.system.service.conversation import ConversationService

class AgentGraph:
    def __init__(
        self,
        retriever: RAGRetriever,
        conversation_service: ConversationService,
        query_model: ChatGoogleGenerativeAI,
        chat_service: ChatService,
        logger: Logger,
    ):
        self.retriever = retriever
        self.conversation_service = conversation_service
        self.chat_service = chat_service
        self.logger = logger
        self.query_model = query_model
        graph = StateGraph(AgentState)

        graph.add_node("create_conversation", CreateConversationNode(
            conversation_service=self.conversation_service,
            logger=self.logger,
        ))
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
            retriever=self.retriever,
            logger=self.logger,
        ))
        graph.add_node("save_chat", SaveChatNode(
            chat_service=self.chat_service,
            logger=self.logger,
        ))
        graph.add_node("update_conversation_title", UpdateConversationTitleNode(
            conversation_service=self.conversation_service,
            model=self.query_model,
            logger=self.logger,
        ))
        graph.add_node("update_conversation_summary", UpdateConversationSummaryNode(
            conversation_service=self.conversation_service,
            model=self.query_model,
            logger=self.logger,
        ))

        graph.add_conditional_edges(
            START,
            create_conversation_router,
            {
                "create_conversation": "create_conversation",
                "retrieval_decider": "retrieval_decider",
            },
        )
        graph.add_edge("create_conversation", "retrieval_decider")
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
                "END": END,
            },
        )
        graph.add_conditional_edges(
            "save_chat",
            update_summary_router,
            {
                "update_summary": "update_conversation_summary",
                "END": END,
            },
        )
        graph.add_edge("update_conversation_summary", END)
        graph.add_edge("update_conversation_title", END)

        self.graph = graph.compile()

    def start(self) -> CompiledStateGraph:
        return self.graph