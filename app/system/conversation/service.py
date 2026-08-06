from logging import Logger

from app.system.conversation.model import ConversationModel
from app.system.conversation.repository import ConversationRepository
from app.system.chat.schema import ChatResponse
from app.system.conversation.schema import (
    ConversationDetailResponse,
    ConversationPatchRequest,
    ConversationResponse,
    CreateConversationRequest,
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

    async def list_by_user(self, user_id: str) -> list[ConversationResponse]:
        self.logger.info("Listing conversations user_id=%s", user_id)
        conversations = await self.repository.list_by_user(user_id)
        if not conversations:
            self.logger.info(
                "No conversations found user_id=%s",
                user_id,
            )
            return []
        response = [
            ConversationResponse(
                id=item.id,
                title=item.title,
                status=item.status,
            )
            for item in conversations
        ]
        self.logger.info(
            "Conversation listing completed user_id=%s count=%s",
            user_id,
            len(response),
        )
        return response

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
        if payload.status is not None:
            updates["status"] = payload.status

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

    async def verify_ownership(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:
        conversation = await self.repository.get(conversation_id, user_id)
        if conversation is None:
            return False
        return conversation
