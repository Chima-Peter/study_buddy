"""Helpers for talking to the self-hosted Unstructured API."""

from __future__ import annotations

from typing import Any

from unstructured.documents.elements import Element
from unstructured.partition.api import partition_via_api


def normalize_unstructured_base_url(url: str) -> str:
    """Return the API base URL without a trailing slash or /general path."""
    base = (url or "").strip().rstrip("/")
    suffix = "/general/v0/general"
    if base.endswith(suffix):
        return base[: -len(suffix)]
    return base


def unstructured_general_url(url: str) -> str:
    """Return the full partition endpoint expected by partition_via_api."""
    base = normalize_unstructured_base_url(url)
    return f"{base}/general/v0/general"


def partition_file_via_api(
    filepath: str,
    *,
    api_url: str,
    api_key: str = "",
    **request_kwargs: Any,
) -> list[Element]:
    """Partition a local file through the Unstructured REST API."""
    return list(
        partition_via_api(
            filename=filepath,
            api_url=unstructured_general_url(api_url),
            api_key=api_key or "",
            **request_kwargs,
        )
    )
