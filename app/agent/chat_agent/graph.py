from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from app.agent.chat_agent.edges import (
    update_summary_router,
    update_title_router,
)
from app.agent.chat_agent.nodes import (
    CleanupNode,
    GenerateResponseNode,
    RetrievalDeciderNode,
    RetrieveConversationHistoryNode,
    RetrieveDocumentsNode,
    RetrieveMemoryNode,
    RewriteQueryNode,
    SaveChatNode,
    StoreMemoryNode,
    UpdateConversationSummaryNode,
    UpdateConversationTitleNode,
)
from app.agent.chat_agent.state import AgentState
from langgraph.graph import START, StateGraph, END
from logging import Logger
from app.authentication.repository.user_repository import UserRepository
from app.core.rabbitmq import RabbitMQ
from app.memory.service import MemoryService
from app.rag.rag_retriever import RAGRetriever
from app.system.chat.service import ChatService
from app.system.conversation.service import ConversationService
from app.system.document.service import DocumentService

class AgentGraph:
    def __init__(
        self,
        retriever: RAGRetriever,
        memory_service: MemoryService,
        conversation_service: ConversationService,
        document_service: DocumentService,
        chat_model: ChatGoogleGenerativeAI,
        query_model: ChatGoogleGenerativeAI,
        summarizer_model: ChatGoogleGenerativeAI,
        chat_service: ChatService,
        user_repository: UserRepository,
        logger: Logger,
        checkpointer: AsyncPostgresSaver,
        rabbitmq: RabbitMQ,
    ):
        self.retriever = retriever
        self.memory_service = memory_service
        self.conversation_service = conversation_service
        self.document_service = document_service
        self.chat_service = chat_service
        self.user_repository = user_repository
        self.logger = logger
        self.chat_model = chat_model
        self.query_model = query_model
        self.summarizer_model = summarizer_model
        self.checkpointer = checkpointer
        self.rabbitmq = rabbitmq
        graph = StateGraph(AgentState)

        self._raw_graph = graph

        nodes = {
            "retrieval_decider": RetrievalDeciderNode(
                model=self.query_model,
                logger=self.logger,
            ),
            "rewrite_query": RewriteQueryNode(
                model=self.query_model,
                logger=self.logger,
                document_service=self.document_service,
            ),
            "retrieve_documents": RetrieveDocumentsNode(
                retriever=self.retriever,
                logger=self.logger,
            ),
            "retrieve_memory": RetrieveMemoryNode(
                memory_service=self.memory_service,
                user_repository=self.user_repository,
                logger=self.logger,
            ),
            "retrieve_conversation_history": RetrieveConversationHistoryNode(
                conversation_service=self.conversation_service,
                logger=self.logger,
            ),
            "generate_response": GenerateResponseNode(
                model=self.chat_model,
                logger=self.logger,
            ),
            "save_chat": SaveChatNode(
                chat_service=self.chat_service,
                logger=self.logger,
            ),
            "update_conversation_title": UpdateConversationTitleNode(
                conversation_service=self.conversation_service,
                model=self.summarizer_model,
                logger=self.logger,
            ),
            "update_conversation_summary": UpdateConversationSummaryNode(
                conversation_service=self.conversation_service,
                model=self.summarizer_model,
                logger=self.logger,
            ),
            "store_memory": StoreMemoryNode(
                rabbitmq=self.rabbitmq,
                logger=self.logger,
            ),
            "cleanup": CleanupNode(
                logger=self.logger,
                document_service=self.document_service,
            ),
        }

        for node_name, node in nodes.items():
            self._add_node(node_name, node)

        graph.add_edge(START, "retrieval_decider")
        graph.add_edge("retrieval_decider", "rewrite_query")
        graph.add_edge("retrieval_decider", "retrieve_conversation_history")
        graph.add_edge("rewrite_query", "retrieve_documents")
        graph.add_edge("rewrite_query", "retrieve_memory")
        graph.add_edge(
            [
                "retrieve_documents",
                "retrieve_conversation_history",
                "retrieve_memory",
            ],
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
                "store_memory": "store_memory",
            },
        )
        graph.add_edge(
            ["update_conversation_summary", "store_memory"],
            "cleanup",
        )
        graph.add_edge("store_memory", "cleanup")
        graph.add_edge("update_conversation_title", "cleanup")
        graph.add_edge("cleanup", END)

        self.graph = graph.compile(checkpointer=self.checkpointer)

    def start(self) -> CompiledStateGraph:
        return self.graph

    def _add_node(self, node_name: str, node):
        self._raw_graph.add_node(node_name, node)

