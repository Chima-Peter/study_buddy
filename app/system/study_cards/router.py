from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.system.user.schema import UserResponse
from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.study_cards.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    StudyCardsAlreadyAttemptedAndFailedError,
    StudyCardsAlreadyExistsError,
    StudyCardsGenerateApiResponse,
    StudyCardsGetApiResponse,
    StudyCardsInProgressError,
    StudyCardsListApiResponse,
    StudyCardsNotRetryableError,
    StudyCardsStatus,
)
from app.system.study_cards.service import StudyCardsService

study_cards_router = APIRouter(prefix="/study-cards", tags=["study-cards"])


@study_cards_router.get(
    "",
    response_model=StudyCardsListApiResponse,
    summary="List study cards",
    description=(
        "List study cards for the authenticated user with optional status filter "
        f"and cursor-based pagination (max {MAX_LIST_LIMIT} per page)."
    ),
)
@inject
async def list_study_cards(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: StudyCardsService = Depends(Provide[Container.study_cards_service]),
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
    ] = None,
    status_filter: Annotated[
        StudyCardsStatus | None,
        Query(alias="status", description="Filter by study cards status"),
    ] = None,
) -> BasicResponse:
    try:
        result = await service.list_by_user(
            user.id,
            limit=limit,
            cursor=cursor,
            status=status_filter,
        )
    except Exception:
        logger.exception(
            "Unexpected error listing study cards user_id=%s",
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Study cards retrieved successfully",
    )


@study_cards_router.post(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StudyCardsGenerateApiResponse,
    summary="Generate study cards",
    description=(
        "Queues study-card generation for an owned document. "
        "Results are written asynchronously to study_cards. "
        "Successful or in-progress cards cannot be regenerated."
    ),
    responses={
        409: {
            "description": (
                "Study cards generation is already in progress or successful"
            )
        },
    },
)
@inject
async def generate_study_cards(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: StudyCardsService = Depends(Provide[Container.study_cards_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.enqueue_generate(document_id, user.id)
    except StudyCardsAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except StudyCardsInProgressError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except StudyCardsAlreadyAttemptedAndFailedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error queueing study cards generate "
            "document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while queuing study cards generation. Please try again later.",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Study cards generation started successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )

@study_cards_router.post(
    "/{document_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=StudyCardsGenerateApiResponse,
    summary="Retry study cards generation",
    description=(
        "Queues study-card generation for an owned document that has already been generated. "
        "Results are written asynchronously to study_cards. "
        "Successful or in-progress cards cannot be regenerated."
    ),
    responses={
        409: {
            "description": (
                "Study cards generation is already in progress or successful"
            )
        },
    },
)
@inject
async def retry_study_cards_generation(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: StudyCardsService = Depends(Provide[Container.study_cards_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.retry_generation(document_id, user.id)
    except StudyCardsNotRetryableError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except StudyCardsInProgressError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Study cards not found. "
                "You can only attempt to regenerate study cards that have already been generated."
            )
        )
    except Exception:
        logger.exception(
            "Unexpected error queueing study cards retry "
            "document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while queuing study cards regeneration. Please try again later.",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Study cards regeneration queued successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )


@study_cards_router.get(
    "/{document_id}",
    response_model=StudyCardsGetApiResponse,
    summary="Get study cards",
    description="Retrieve study cards for an owned document, including status and result.",
)
@inject
async def get_study_cards(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: StudyCardsService = Depends(Provide[Container.study_cards_service]),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        study_card = await service.get_by_document(document_id, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Study cards not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error getting study cards "
            "document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while getting study cards. Please try again later.",
        )

    return BasicResponse(
        data=study_card.to_response().model_dump(mode="json"),
        message="Study cards retrieved successfully",
    )
