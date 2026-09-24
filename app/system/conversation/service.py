from logging import Logger

from langgraph.graph.state import CompiledStateGraph

from app.system.chat.schema import ChatResponse
from app.system.chat.service import ChatService
from app.system.conversation.model import ConversationModel
from app.system.conversation.repository import ConversationRepository
from app.system.conversation.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    BranchConversationRequest,
    BranchConversationResponse,
    ConversationDetailResponse,
    ConversationListResponseData,
    ConversationPatchRequest,
    ConversationResponse,
    CreateConversationRequest,
)
from app.utils.continuation_key import verify_continuation_key


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        logger: Logger,
        chat_service: ChatService,
        continuation_secret: str,
    ):
        self.repository = repository
        self.logger = logger
        self.chat_service = chat_service
        self.continuation_secret = continuation_secret

    async def create(
        self,
        request: CreateConversationRequest,
        user_id: str,
    ) -> ConversationResponse:
        self.logger.info("Creating conversation user_id=%s", user_id)
        conversation = ConversationModel(
            title=request.title,
            user_id=user_id,
        )
        result = await self.repository.create(conversation)
        self.logger.info(
            "Conversation creation completed id=%s user_id=%s",
            result.id,
            user_id,
        )
        return ConversationResponse(
            id=result.id,
            title=result.title,
            status=result.status,
        )

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
    ) -> ConversationListResponseData:
        self.logger.info(
            "Listing conversations user_id=%s limit=%s cursor=%s",
            user_id,
            limit,
            cursor,
        )
        conversations, next_cursor, has_more = await self.repository.list_by_user(
            user_id,
            limit=limit,
            cursor=cursor,
        )
        return ConversationListResponseData(
            items=[
                ConversationResponse(
                    id=item.id,
                    title=item.title,
                    status=item.status,
                )
                for item in conversations
            ],
            next_cursor=next_cursor,
            has_more=has_more,
            limit=min(max(limit, 1), MAX_LIST_LIMIT),
        )

    async def get(
        self,
        conversation_id: str,
        user_id: str,
    ) -> ConversationDetailResponse | None:
        self.logger.info(
            "Getting conversation id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        result = await self.repository.get_with_chats(
            conversation_id,
            user_id,
        )
        if result is None:
            self.logger.warning(
                "Conversation unavailable id=%s user_id=%s",
                conversation_id,
                user_id,
            )
            return None

        conversation, chats = result
        self.logger.info(
            "Conversation retrieval completed id=%s user_id=%s chat_count=%s",
            conversation_id,
            user_id,
            len(chats),
        )
        return ConversationDetailResponse(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            summary=conversation.summary,
            chats=[
                ChatResponse(
                    id=chat.id,
                    conversation_id=chat.conversation_id,
                    query=chat.query,
                    response=chat.chat,
                    continuation_key=chat.continuation_key,
                    created_at=chat.created_at,
                )
                for chat in chats
            ],
        )

    async def update_summary(
        self,
        conversation_id: str,
        summary: str,
        user_id: str,
    ) -> None:
        self.logger.info(
            "Updating conversation summary id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        conversation = await self.repository.get(conversation_id, user_id)
        if conversation is None:
            self.logger.warning(
                "Conversation unavailable for summary update id=%s user_id=%s",
                conversation_id,
                user_id,
            )
            raise ValueError("Conversation not found")
        conversation.patch_model({"summary": summary})
        conversation = await self.repository.update(conversation)
        if conversation is None:
            raise ValueError("Conversation not found")
        self.logger.info(
            "Conversation summary update completed id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        return ConversationResponse(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
        )

    async def update(
        self,
        conversation_id: str,
        payload: ConversationPatchRequest,
        user_id: str,
    ) -> ConversationResponse:
        self.logger.info(
            "Updating conversation id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        conversation = await self.repository.get(conversation_id, user_id)
        if conversation is None:
            self.logger.warning(
                "Conversation unavailable for update id=%s user_id=%s",
                conversation_id,
                user_id,
            )
            raise ValueError("Conversation not found")

        updates: dict = {}
        if payload.title is not None:
            updates["title"] = payload.title

        conversation.patch_model(updates)
        conversation = await self.repository.update(conversation)
        if conversation is None:
            raise ValueError("Conversation not found")
        self.logger.info(
            "Conversation update completed id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        return ConversationResponse(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
        )

    async def branch(
        self,
        graph: CompiledStateGraph,
        user_id: str,
        request: BranchConversationRequest,
    ) -> BranchConversationResponse:
        verified = verify_continuation_key(
            request.continuation_key,
            self.continuation_secret,
        )
        if verified is None:
            raise ValueError("Invalid continuation key")

        source_thread_id = verified["thread_id"]
        self.logger.info(
            "Branching conversation id=%s user_id=%s",
            source_thread_id,
            user_id,
        )
        source = await self.repository.get(source_thread_id, user_id)
        if source is None:
            raise ValueError("Conversation not found")

        source_title = (source.title or "Conversation").strip() or "Conversation"
        branch_title = (
            source_title
            if source_title.startswith("Branch · ")
            else f"Branch · {source_title}"
        )

        conversation = await self.create(
            CreateConversationRequest(title=branch_title),
            user_id=user_id,
        )
        chat = await self.chat_service.branch(
            graph,
            user_id=user_id,
            payload=verified,
            new_conversation_id=conversation.id,
        )
        if not chat.continuation_key:
            raise ValueError("Failed to create branched chat")

        self.logger.info(
            "Conversation branch completed source_id=%s new_id=%s user_id=%s",
            source_thread_id,
            conversation.id,
            user_id,
        )
        return BranchConversationResponse(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            continuation_key=chat.continuation_key,
            chat_id=chat.id,
        )

    async def verify_ownership(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:
        conversation = await self.repository.get(conversation_id, user_id)
        if conversation is None:
            return False
        return conversation
