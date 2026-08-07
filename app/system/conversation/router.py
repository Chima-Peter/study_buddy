from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.authentication.schemas.user import UserResponse
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.conversation.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    ConversationApiResponse,
    ConversationHistoryApiResponse,
    ConversationHistoryResponse,
    ConversationListApiResponse,
    ConversationPatchRequest,
    STATUS_LITERAL,
)
from app.system.conversation.service import ConversationService

conversation_router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
)


@conversation_router.get("", response_model=ConversationListApiResponse)
@inject
async def list_conversations(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ConversationService = Depends(
        Provide[Container.conversation_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_LIST_LIMIT,
            description=f"Page size (1–{MAX_LIST_LIMIT}, default {DEFAULT_LIST_LIMIT})",
        ),
    ] = DEFAULT_LIST_LIMIT,
    cursor: Annotated[
        str | None,
        Query(description="Cursor from previous page's next_cursor"),
    ] = None
) -> BasicResponse:
    logger.info("List conversations request user_id=%s", user.id)
    try:
        result = await service.list_by_user(
            user.id,
            limit=limit,
            cursor=cursor,
        )
        logger.info(
            "List conversations request completed user_id=%s count=%s",
            user.id,
            len(result.items),
        )
        return BasicResponse(
            data=result.model_dump(mode="json"),
            message="Conversations retrieved successfully",
        )
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
    response_model=ConversationHistoryApiResponse,
)
@inject
async def get_conversation(
    conversation_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ConversationService = Depends(
        Provide[Container.conversation_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    logger.info(
        "Get conversation request id=%s user_id=%s",
        conversation_id,
        user.id,
    )
    try:
        conversation = await service.get(conversation_id, user.id)
        if conversation is None:
            raise ValueError("Conversation not found")
        logger.info(
            "Get conversation request completed id=%s user_id=%s",
            conversation_id,
            user.id,
        )
        return BasicResponse(
            data=ConversationHistoryResponse(
                id=conversation.id,
                title=conversation.title,
                status=conversation.status,
                chats=conversation.chats,
            ).model_dump(mode="json"),
            message="Conversation retrieved successfully",
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
    response_model=ConversationApiResponse,
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
) -> BasicResponse:
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
        return BasicResponse(
            data=conversation.model_dump(mode="json"),
            message="Conversation updated successfully",
        )
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
