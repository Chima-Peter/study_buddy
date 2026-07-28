from logging import Logger

from app.system.models.conversation import ConversationModel
from app.system.repository.conversation import ConversationRepository
from app.system.schemas.chat import ChatResponse
from app.system.schemas.conversation import (
    ConversationDetailResponse,
    ConversationResponse,
    CreateConversationRequest,
    UpdateConversationTitleRequest,
)


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        logger: Logger,
    ):
        self.repository = repository
        self.logger = logger

    async def create(
        self,
        request: CreateConversationRequest,
        user_id: str,
    ) -> ConversationResponse:
        conversation = ConversationModel(
            title=request.title,
            user_id=user_id,
        )
        result = await self.repository.create(conversation)
        return ConversationResponse(id=result.id, title=result.title)

    async def list_by_user(self, user_id: str) -> list[ConversationResponse]:
        conversations = await self.repository.list_by_user(user_id)
        return [
            ConversationResponse(id=item.id, title=item.title)
            for item in conversations
        ]

    async def get(
        self,
        conversation_id: str,
        user_id: str,
    ) -> ConversationDetailResponse:
        result = await self.repository.get_with_chats(
            conversation_id,
            user_id,
        )
        if result is None:
            raise ValueError("Conversation not found")

        conversation, chats = result
        return ConversationDetailResponse(
            id=conversation.id,
            title=conversation.title,
            chats=[
                ChatResponse(
                    id=chat.id,
                    conversation_id=chat.conversation_id,
                    query=chat.query,
                    response=chat.chat,
                    created_at=chat.created_at,
                )
                for chat in chats
            ],
        )

    async def update_title(
        self,
        conversation_id: str,
        request: UpdateConversationTitleRequest,
        user_id: str,
    ) -> ConversationResponse:
        conversation = await self.repository.update_title(
            conversation_id,
            user_id,
            request.title,
        )
        if conversation is None:
            raise ValueError("Conversation not found")
        return ConversationResponse(
            id=conversation.id,
            title=conversation.title,
        )
