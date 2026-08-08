import asyncio
import json
from datetime import datetime
from logging import Logger
from typing import Annotated, AsyncIterator

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.system.user.schema import UserResponse
from app.container import Container
from app.core.redis import RedisClient
from app.core.response import BasicResponse
from app.core.security import get_current_user
from app.system.notification.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MarkNotificationsReadApiResponse,
    MarkNotificationsReadRequest,
    NotificationApiResponse,
    NotificationListApiResponse,
)
from app.system.notification.service import NotificationService
from app.utils.errors import NotificationNotFoundError

notification_router = APIRouter(
    prefix="/notifications", tags=["notifications"])


@notification_router.get(
    "",
    response_model=NotificationListApiResponse,
    summary="List notifications",
    description=(
        "List notifications with optional created_at filters "
        f"and cursor-based pagination (max {MAX_LIST_LIMIT} per page)."
    ),
)
@inject
async def list_notifications(
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: NotificationService = Depends(
        Provide[Container.notification_service]
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
    ] = None,
    created_after: Annotated[
        datetime | None,
        Query(
            description="Include notifications created at or after this timestamp (ISO 8601)"
        ),
    ] = None,
    created_before: Annotated[
        datetime | None,
        Query(
            description="Include notifications created at or before this timestamp (ISO 8601)"
        ),
    ] = None,
    unread_only: Annotated[
        bool,
        Query(description="If true, only return notifications that have not been read"),
    ] = False,
) -> BasicResponse:
    if (
        created_after is not None
        and created_before is not None
        and created_after > created_before
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="created_after must be less than or equal to created_before",
        )

    try:
        result = await service.list_notifications(
            user.id,
            limit=limit,
            cursor=cursor,
            created_after=created_after,
            created_before=created_before,
            unread_only=unread_only,
        )
    except Exception:
        logger.exception(
            "Unexpected error listing notifications user_id=%s", user.id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Notifications retrieved successfully",
    )


@notification_router.patch(
    "/read",
    response_model=MarkNotificationsReadApiResponse,
    summary="Mark notifications as read",
    description="Marks one or more notifications as read for the current user.",
)
@inject
async def mark_notifications_read(
    request: MarkNotificationsReadRequest,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: NotificationService = Depends(
        Provide[Container.notification_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.mark_many_as_read(request.ids, user.id)
    except NotificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception:
        logger.exception(
            "Unexpected error marking notifications read user_id=%s count=%s",
            user.id,
            len(request.ids),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Notifications marked as read",
    )


@notification_router.patch(
    "/{notification_id}/read",
    response_model=NotificationApiResponse,
    summary="Mark notification as read",
    description="Sets read_at to the current time if the notification is unread.",
)
@inject
async def mark_notification_read(
    notification_id: str,
    user: Annotated[UserResponse, Depends(get_current_user)],
    service: NotificationService = Depends(
        Provide[Container.notification_service]
    ),
    logger: Logger = Depends(Provide[Container.logger]),
) -> BasicResponse:
    try:
        result = await service.mark_as_read(notification_id, user.id)
    except NotificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception:
        logger.exception(
            "Unexpected error marking notification read id=%s user_id=%s",
            notification_id,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    return BasicResponse(
        data=result.model_dump(mode="json"),
        message="Notification marked as read",
    )


@notification_router.get(
    "/stream",
    summary="Live notification stream",
    description=(
        "Server-Sent Events stream for the current user. "
        "Reconnect with Last-Event-ID to resume from the last received message."
    ),
)
@inject
async def live_stream(
    user: Annotated[UserResponse, Depends(get_current_user)],
    request: Request,
    redis_service: RedisClient = Depends(Provide[Container.redis_client]),
    logger: Logger = Depends(Provide[Container.logger]),
    last_event_id: Annotated[
        str | None, Header(alias="Last-Event-ID")
    ] = None,
) -> StreamingResponse:
    cursor = last_event_id or "0"
    stream_name = await redis_service.orchestrate_stream(user.id)

    async def event_generator() -> AsyncIterator[str]:
        nonlocal cursor
        try:
            while True:
                if await request.is_disconnected():
                    logger.info(
                        "SSE client disconnected user_id=%s stream=%s",
                        user.id,
                        stream_name,
                    )
                    break

                messages = await redis_service.read_stream(stream_name, cursor)
                if await request.is_disconnected():
                    logger.info(
                        "SSE client disconnected user_id=%s stream=%s",
                        user.id,
                        stream_name,
                    )
                    break

                if not messages:
                    yield (
                        f"event: ping\n"
                        f"data: {json.dumps({})}\n\n"
                    )
                    continue

                logout = next(
                    (
                        (message_id, fields)
                        for message_id, fields in messages
                        if fields.get("type") == "auth.logout"
                    ),
                    None,
                )
                if logout is not None:
                    message_id, fields = logout
                    cursor = message_id
                    raw_data = fields.get("data", "{}")
                    try:
                        payload_data = json.loads(raw_data)
                    except (TypeError, json.JSONDecodeError):
                        payload_data = raw_data

                    logger.info(
                        "SSE client logged out user_id=%s stream=%s",
                        user.id,
                        stream_name,
                    )
                    payload = json.dumps(
                        {"type": "auth.logout", "data": payload_data}
                    )
                    yield (
                        f"id: {message_id}\n"
                        f"event: auth.logout\n"
                        f"data: {payload}\n\n"
                    )
                    for mid, _ in messages:
                        await redis_service.delete_message_from_stream(
                            stream_name, mid
                        )
                    return

                for message_id, fields in messages:
                    cursor = message_id
                    event_type = fields.get("type", "message")
                    raw_data = fields.get("data", "{}")
                    try:
                        payload_data = json.loads(raw_data)
                    except (TypeError, json.JSONDecodeError):
                        payload_data = raw_data

                    payload = json.dumps(
                        {"type": event_type, "data": payload_data}
                    )
                    yield (
                        f"id: {message_id}\n"
                        f"event: {event_type}\n"
                        f"data: {payload}\n\n"
                    )
                    await redis_service.delete_message_from_stream(
                        stream_name, message_id
                    )
        except asyncio.CancelledError:
            logger.info(
                "SSE cancelled user_id=%s stream=%s",
                user.id,
                stream_name,
            )
            raise
        finally:
            await redis_service.expire_connection(user.id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )