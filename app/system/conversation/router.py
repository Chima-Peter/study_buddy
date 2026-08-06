from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.security import get_current_user
from app.system.conversation.schema import (
    ConversationHistoryResponse,
    ConversationPatchRequest,
    ConversationResponse,
)
from app.system.conversation.service import ConversationService

conversation_router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
)


@conversation_router.get("", response_model=list[ConversationResponse])
@inject
async def list_conversations(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ConversationService = Depends(
        Provide[Container.conversation_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> list[ConversationResponse]:
    logger.info("List conversations request user_id=%s", user.id)
    try:
        conversations = await service.list_by_user(user.id)
        logger.info(
            "List conversations request completed user_id=%s count=%s",
            user.id,
            len(conversations),
        )
        return conversations
    except Exception:
        logger.exception(
            "Unexpected error listing conversations user_id=%s",
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@conversation_router.get(
    "/{conversation_id}",
    response_model=ConversationHistoryResponse,
)
@inject
async def get_conversation(
    conversation_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ConversationService = Depends(
        Provide[Container.conversation_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> ConversationHistoryResponse:
    logger.info(
        "Get conversation request id=%s user_id=%s",
        conversation_id,
        user.id,
    )
    try:        
        conversation = await service.get(conversation_id, user.id)
        logger.info(
            "Get conversation request completed id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        return ConversationHistoryResponse(
            id=conversation_id,
            title=conversation.title,
            status=conversation.status,
            chats=conversation.chats,
        )
    except ValueError as error:
        logger.warning(
            "Get conversation request not found id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except Exception:
        logger.exception(
            "Unexpected error getting conversation id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )



@conversation_router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
@inject
async def patch_conversation(
    conversation_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    request: ConversationPatchRequest,
    service: ConversationService = Depends(
        Provide[Container.conversation_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> ConversationResponse:
    logger.info(
        "Update conversation request id=%s user_id=%s",
        conversation_id,
        user.id,
    )
    try:
        conversation = await service.update(
            conversation_id=conversation_id,
            user_id=user.id,
            payload=request,
        )
        logger.info(
            "Update conversation request completed id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        return conversation
    except ValueError as error:
        logger.warning(
            "Update conversation request not found id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except Exception:
        logger.exception(
            "Unexpected error updating conversation id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

