from typing import Literal

from pydantic import BaseModel, Field

SUMMARY_EVERY = 5


class DeciderResponse(BaseModel):
    decision: Literal["rag", "history", "both"] = Field(
        description=(
            "rag: retrieve study documents only; "
            "history: use conversation memory only; "
            "both: retrieve documents and conversation memory"
        ),
    )
