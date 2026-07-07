from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


class BasicResponse(JSONResponse):
    """Standardized JSON response with data, success, message, error fields."""

    def __init__(
        self,
        data: Any = None,
        success: bool = True,
        message: str | None = None,
        error: str | None = None,
        status_code: int = status.HTTP_200_OK,
        **kwargs,
    ):
        content = {
            "data": data,
            "success": success,
            "message": message,
            "error": error,
        }
        super().__init__(content=content, status_code=status_code, **kwargs)


def success_response(
    data: Any = None,
    message: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> BasicResponse:
    """Return a success response."""
    return BasicResponse(
        data=data,
        success=True,
        message=message,
        error=None,
        status_code=status_code,
    )


def error_response(
    error: str,
    message: str | None = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> BasicResponse:
    """Return an error response."""
    return BasicResponse(
        data=None,
        success=False,
        message=message,
        error=error,
        status_code=status_code,
    )
