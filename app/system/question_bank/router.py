from logging import Logger
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.container import Container
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.question_bank.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    QuestionBankAlreadyExistsError,
    QuestionBankGenerateApiResponse,
    QuestionBankGetApiResponse,
    QuestionBankInProgressError,
    QuestionBankListApiResponse,
    QuestionBankStatus,
)
from app.system.question_bank.service import QuestionBankService
from app.system.user.schema import UserResponse

question_bank_router = APIRouter(
    prefix="/question-bank", tags=["question-bank"]
)


@question_bank_router.get(
    "",
    response_model=QuestionBankListApiResponse,
    summary="List question banks",
    description=(
        "List question banks for the authenticated user with optional status "
        f"filter and cursor-based pagination (max {MAX_LIST_LIMIT} per page)."
    ),
)
@inject
async def list_question_banks(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: QuestionBankService = Depends(
        Provide[Container.question_bank_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_LIST_LIMIT,
            description=(
                f"Page size (1–{MAX_LIST_LIMIT}, default {DEFAULT_LIST_LIMIT})"
            ),
        ),
    ] = DEFAULT_LIST_LIMIT,
    cursor: Annotated[
        str | None,
        Query(description="Cursor from previous page's next_cursor"),
    ] = None,
    status_filter: Annotated[
        QuestionBankStatus | None,
        Query(alias="status", description="Filter by question bank status"),
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
            "Unexpected error listing question banks user_id=%s",
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Question banks retrieved successfully",
    )


@question_bank_router.post(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=QuestionBankGenerateApiResponse,
    summary="Generate question bank",
    description=(
        "Queues question-bank generation for an owned document. "
        "Results are written asynchronously to question_banks. "
        "Failed banks can be regenerated; successful or in-progress cannot."
    ),
    responses={
        409: {
            "description": (
                "Question bank already exists (success) or generation "
                "is in progress"
            )
        },
    },
)
@inject
async def generate_question_bank(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: QuestionBankService = Depends(
        Provide[Container.question_bank_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.enqueue_generate(document_id, user.id)
    except QuestionBankAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except QuestionBankInProgressError as e:
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
            "Unexpected error queueing question bank generate "
            "document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Question bank generation started successfully",
        status_code=status.HTTP_202_ACCEPTED,
    )


@question_bank_router.get(
    "/{document_id}",
    response_model=QuestionBankGetApiResponse,
    summary="Get question bank",
    description=(
        "Retrieve the question bank for an owned document, "
        "including status and result."
    ),
)
@inject
async def get_question_bank(
    document_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: QuestionBankService = Depends(
        Provide[Container.question_bank_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        question_bank = await service.get_by_document(document_id, user.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question bank not found",
        )
    except Exception:
        logger.exception(
            "Unexpected error getting question bank "
            "document_id=%s user_id=%s",
            document_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=question_bank.to_response().model_dump(mode="json"),
        message="Question bank retrieved successfully",
    )
