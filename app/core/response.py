from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


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
