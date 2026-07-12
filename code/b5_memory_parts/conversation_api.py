from __future__ import annotations

from common.conversation_store import (
    append_message,
    delete_conversation,
    init_store,
    list_conversations,
    list_messages,
    list_task_memories,
    list_tool_steps,
    record_tool_step,
    update_message,
    upsert_conversation,
)
from common.schemas import normalize_history_messages

from b5_memory_parts.paths import _conversation_db_path, _safe_conversation_id


def init_conversation_db(config_path: str) -> dict:
    return init_store(_conversation_db_path(config_path))

def upsert_conversation_record(
    config_path: str,
    conversation_id: str,
    title: str,
    is_trivial: bool = False,
    trivial_reason: str | None = None,
    summary: str | None = None,
    status: str = "active",
) -> dict:
    _safe_conversation_id(conversation_id)
    return upsert_conversation(
        _conversation_db_path(config_path),
        conversation_id,
        title,
        is_trivial=is_trivial,
        trivial_reason=trivial_reason,
        summary=summary,
        status=status,
    )

def append_conversation_message(
    config_path: str,
    conversation_id: str,
    role: str,
    content: str,
    message_id: str | None = None,
    run_id: str | None = None,
    message_order: int | None = None,
    is_trivial: bool = False,
    token_count: int | None = None,
    metadata: dict | None = None,
) -> dict:
    _safe_conversation_id(conversation_id)
    return append_message(
        _conversation_db_path(config_path),
        conversation_id,
        role,
        content,
        message_id=message_id,
        run_id=run_id,
        message_order=message_order,
        is_trivial=is_trivial,
        token_count=token_count,
        metadata=metadata,
    )

def update_conversation_message(
    config_path: str,
    message_id: str,
    content: str | None = None,
    token_count: int | None = None,
    metadata: dict | None = None,
) -> dict:
    return update_message(
        _conversation_db_path(config_path),
        message_id,
        content=content,
        token_count=token_count,
        metadata=metadata,
    )

def record_conversation_tool_step(
    config_path: str,
    conversation_id: str,
    assistant_message_id: str,
    tool_name: str,
    step_index: int,
    step_id: str | None = None,
    run_id: str | None = None,
    tool_call_id: str | None = None,
    input_data: object = None,
    output_data: object = None,
    status: str = "success",
    error: object = None,
    latency_ms: float | None = None,
) -> dict:
    _safe_conversation_id(conversation_id)
    return record_tool_step(
        _conversation_db_path(config_path),
        conversation_id,
        assistant_message_id,
        tool_name,
        step_id=step_id,
        run_id=run_id,
        step_index=step_index,
        tool_call_id=tool_call_id,
        input_data=input_data,
        output_data=output_data,
        status=status,
        error=error,
        latency_ms=latency_ms,
    )

def list_conversation_records(config_path: str, limit: int = 50) -> list[dict]:
    return list_conversations(_conversation_db_path(config_path), limit)

def delete_conversation_record(config_path: str, conversation_id: str) -> dict:
    _safe_conversation_id(conversation_id)
    return delete_conversation(_conversation_db_path(config_path), conversation_id)

def list_conversation_messages(config_path: str, conversation_id: str) -> list[dict]:
    _safe_conversation_id(conversation_id)
    return list_messages(_conversation_db_path(config_path), conversation_id)

def list_conversation_history(config_path: str, conversation_id: str) -> list[dict]:
    """Expose completed SQLite history using the runtime message protocol."""
    messages = list_conversation_messages(config_path, conversation_id)
    history = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if metadata.get("ui_status") in {"pending", "error", "cancelled"}:
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            history.append({"role": message["role"], "content": content})
    return normalize_history_messages(history)

def list_message_tool_steps(config_path: str, assistant_message_id: str) -> list[dict]:
    return list_tool_steps(_conversation_db_path(config_path), assistant_message_id)

def list_conversation_tasks(config_path: str, conversation_id: str, status: str | None = None) -> list[dict]:
    _safe_conversation_id(conversation_id)
    return list_task_memories(_conversation_db_path(config_path), conversation_id, status)
