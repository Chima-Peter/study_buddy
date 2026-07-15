from typing import Any, Optional

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ApiResponse(BaseModel):
    """OpenAPI schema for the standard API envelope."""

    data: Any = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None


class BasicResponse(JSONResponse):
    """Standardized JSON response with data, success, message, error fields.

    Success is automatically determined from status_code:
    - 2xx/3xx -> success=True, error=None
    - 4xx/5xx -> success=False, data=None
    """

    def __init__(
        self,
        data: Any = None,
        message: str | None = None,
        error: str | None = None,
        status_code: int = status.HTTP_200_OK,
        **kwargs,
    ):
        is_success = 200 <= status_code < 400

        if is_success:
            content = {
                "data": data,
                "success": True,
                "message": message,
                "error": None,
            }
        else:
            content = {
                "data": None,
                "success": False,
                "message": message,
                "error": error,
            }

        super().__init__(content=content, status_code=status_code, **kwargs)


def basic_response_from_http_exception(exc: HTTPException) -> BasicResponse:
    detail = exc.detail
    if isinstance(detail, str):
        error = detail
    elif isinstance(detail, list):
        error = "; ".join(
            item.get("msg", str(item)) if isinstance(item, dict) else str(item)
            for item in detail
        )
    else:
        error = str(detail)
    return BasicResponse(error=error, status_code=exc.status_code)
