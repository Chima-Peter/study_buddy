from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from app.authentication.schemas import UserResponse
from app.container import Container
from app.core.security import get_current_user
from app.system.schemas.conversation import (
    ConversationDetailResponse,
    ConversationResponse,
    # CreateConversationRequest,
    # UpdateConversationTitleRequest,
)
from app.system.service.conversation import ConversationService

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
) -> list[ConversationResponse]:
    return await service.list_by_user(user.id)


@conversation_router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
)
@inject
async def get_conversation(
    conversation_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: ConversationService = Depends(
        Provide[Container.conversation_service]
    ),
) -> ConversationDetailResponse:
    try:
        return await service.get(conversation_id, user.id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error


# @conversation_router.post(
#     "",
#     response_model=ConversationResponse,
#     status_code=status.HTTP_201_CREATED,
# )
# @inject
# async def create_conversation(
#     request: CreateConversationRequest,
#     user: Annotated[UserResponse, Depends(get_current_user)],
#     service: ConversationService = Depends(
#         Provide[Container.conversation_service]
#     ),
# ) -> ConversationResponse:
#     return await service.create(request, user.id)


# @conversation_router.patch(
#     "/{conversation_id}",
#     response_model=ConversationResponse,
# )
# @inject
# async def update_conversation_title(
#     conversation_id: str,
#     request: UpdateConversationTitleRequest,
#     user: Annotated[UserResponse, Depends(get_current_user)],
#     service: ConversationService = Depends(
#         Provide[Container.conversation_service]
#     ),
# ) -> ConversationResponse:
#     try:
#         return await service.update_title(conversation_id, request, user.id)
#     except ValueError as error:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=str(error),
#         ) from error
