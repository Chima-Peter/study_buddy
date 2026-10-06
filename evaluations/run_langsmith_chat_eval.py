#!/usr/bin/env python3
"""Run a LangSmith dataset against the chat agent graph.

Requires app infra (Postgres, ES, Redis, Gemini, …) plus LANGSMITH_API_KEY.

Examples:
  uv run python evaluations/run_langsmith_chat_eval.py --user-id <uuid> --sync

  uv run python evaluations/run_langsmith_chat_eval.py \\
    --user-id <uuid> --dataset-name chat-agent-dsa --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import uuid_utils
from langchain_core.messages import HumanMessage
from langsmith import Client, aevaluate

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DATASET_FILE = ROOT / "datasets" / "langsmith_chat_dataset.jsonl"
DEFAULT_DATASET_NAME = "chat-agent-dsa"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the chat agent graph on a LangSmith dataset",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="User UUID that owns the dataset document_id",
    )
    parser.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help=f"LangSmith dataset name (default: {DEFAULT_DATASET_NAME})",
    )
    parser.add_argument(
        "--dataset-file",
        type=Path,
        default=DEFAULT_DATASET_FILE,
        help="Local JSONL used when --sync is set",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Create/replace LangSmith dataset examples from --dataset-file",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Upload dataset and exit without running the graph",
    )
    parser.add_argument(
        "--experiment-prefix",
        default="chat-agent",
        help="LangSmith experiment prefix",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max examples to run (default: all)",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Parallel examples (default: 1)",
    )
    parser.add_argument(
        "--fresh-threads",
        action="store_true",
        help="Create a new conversation per example instead of inputs.thread_id",
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "inputs" not in row:
                raise SystemExit(f"Missing 'inputs' at {path}:{line_no}")
            rows.append(row)
    return rows


def sync_dataset(client: Client, name: str, path: Path) -> None:
    rows = load_jsonl(path)
    if client.has_dataset(dataset_name=name):
        dataset = client.read_dataset(dataset_name=name)
        existing = list(client.list_examples(dataset_id=dataset.id))
        if existing:
            client.delete_examples([example.id for example in existing])
            print(f"Deleted {len(existing)} existing examples from '{name}'")
    else:
        dataset = client.create_dataset(
            dataset_name=name,
            description="Chat agent examples. Inputs: query, document_id, thread_id.",
        )
        print(f"Created LangSmith dataset '{name}' id={dataset.id}")

    client.create_examples(
        dataset_id=dataset.id,
        examples=[
            {
                "inputs": row["inputs"],
                "outputs": row.get("outputs") or {},
                "metadata": row.get("metadata") or {},
            }
            for row in rows
        ],
    )
    print(f"Uploaded {len(rows)} examples to '{name}' from {path}")


def last_ai_text(messages: list[Any] | None) -> str:
    if not messages:
        return ""
    for message in reversed(messages):
        if getattr(message, "type", None) != "ai":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        return str(content or "").strip()
    return ""


async def run(args: argparse.Namespace) -> int:
    client = Client()

    if args.sync or args.sync_only:
        if not args.dataset_file.is_file():
            print(f"Dataset file not found: {args.dataset_file}", file=sys.stderr)
            return 1
        sync_dataset(client, args.dataset_name, args.dataset_file)
        if args.sync_only:
            return 0

    if not client.has_dataset(dataset_name=args.dataset_name):
        print(
            f"LangSmith dataset '{args.dataset_name}' not found. "
            "Re-run with --sync.",
            file=sys.stderr,
        )
        return 1

    from app.container import Container
    from app.system.conversation.model import ConversationModel

    container = Container()
    await container.init_resources()
    try:
        await asyncio.to_thread(container.embedding_manager().ensure_loaded)
        agent_graph = await container.agent_graph()
        conversation_repository = await container.conversation_repository()
        ensured_threads: set[str] = set()

        async def run_chat(inputs: dict[str, Any]) -> dict[str, Any]:
            query = (inputs.get("query") or "").strip()
            document_id = (inputs.get("document_id") or "").strip()
            if not query or not document_id:
                raise ValueError("inputs.query and inputs.document_id are required")

            if args.fresh_threads:
                conversation_id = str(uuid_utils.uuid7())
            else:
                conversation_id = (inputs.get("thread_id") or "").strip()
                if not conversation_id:
                    raise ValueError("inputs.thread_id is required")

            if conversation_id not in ensured_threads:
                existing = await conversation_repository.get(
                    conversation_id,
                    args.user_id,
                )
                if existing is None:
                    await conversation_repository.create(
                        ConversationModel(
                            id=conversation_id,
                            user_id=args.user_id,
                            title="LangSmith chat eval",
                        )
                    )
                ensured_threads.add(conversation_id)

            result = await agent_graph.start().ainvoke(
                {
                    "user_id": args.user_id,
                    "conversation_id": conversation_id,
                    "query": query,
                    "document_id": document_id,
                    "turn_type": "chat",
                    "fork_chat_id": None,
                    "messages": [HumanMessage(content=query)],
                },
                config={
                    "configurable": {"thread_id": conversation_id},
                    "metadata": {"thread_id": conversation_id},
                },
            )
            return {
                "response": last_ai_text(result.get("messages")),
                "conversation_id": conversation_id,
            }

        data: Any = args.dataset_name
        if args.limit is not None:
            data = list(
                client.list_examples(
                    dataset_name=args.dataset_name,
                    limit=args.limit,
                )
            )

        print(
            f"Running dataset='{args.dataset_name}' "
            f"user_id={args.user_id} concurrency={args.max_concurrency}"
        )
        results = await aevaluate(
            run_chat,
            data=data,
            experiment_prefix=args.experiment_prefix,
            max_concurrency=args.max_concurrency,
            client=client,
            blocking=True,
        )
        print(f"Experiment: {getattr(results, 'url', results)}")
        return 0
    finally:
        await container.shutdown_resources()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
