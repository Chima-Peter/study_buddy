import csv
import json
from pathlib import Path

from langchain_core.documents import Document


def parse_csv(file_path: str) -> list[Document]:
    """Convert CSV rows into individual documents."""
    documents = []

    with open(file_path, encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for index, row in enumerate(reader):
            content = "\n".join(
                f"{key}: {value}"
                for key, value in row.items()
                if value is not None
            )

            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": Path(file_path).name,
                        "row": index,
                    },
                )
            )

    return documents


def parse_json(file_path: str) -> list[Document]:
    """Convert JSON objects into documents. Handles arrays and single objects."""
    documents = []

    with open(file_path, encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [data]
    else:
        # Top-level primitive (string, number, bool, null)
        items = [{"value": data}]

    for index, item in enumerate(items):
        content = _item_to_text(item, index)
        if not content:
            continue

        documents.append(
            Document(
                page_content=content,
                metadata={
                    "source": Path(file_path).name,
                    "item": index,
                },
            )
        )

    return documents


def _item_to_text(item, index: int) -> str:
    """Convert a single item (dict or primitive) to text."""
    if isinstance(item, dict):
        return _json_to_text(item)
    elif item is None:
        return ""
    else:
        # Primitive in array: wrap with index context
        return f"item[{index}]: {item}"


def _json_to_text(data: dict, prefix: str = "") -> str:
    """Flatten nested JSON dict into readable text."""
    lines = []

    for key, value in data.items():
        field = f"{prefix}{key}"

        if isinstance(value, dict):
            nested = _json_to_text(value, f"{field}.")
            if nested:
                lines.append(nested)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    nested = _json_to_text(item, f"{field}[{idx}].")
                    if nested:
                        lines.append(nested)
                elif item is not None:
                    lines.append(f"{field}[{idx}]: {item}")
        elif value is not None:
            lines.append(f"{field}: {value}")

    return "\n".join(lines)


# Keep public alias for backward compatibility
def json_to_text(data: dict, prefix: str = "") -> str:
    """Flatten nested JSON into readable text."""
    return _json_to_text(data, prefix)
