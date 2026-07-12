from __future__ import annotations

from b5_memory_parts.cli import build_parser, main, parse_bool
from b5_memory_parts.conversation_api import (
    append_conversation_message,
    delete_conversation_record,
    init_conversation_db,
    list_conversation_history,
    list_conversation_messages,
    list_conversation_records,
    list_conversation_tasks,
    list_message_tool_steps,
    record_conversation_tool_step,
    update_conversation_message,
    upsert_conversation_record,
)
from b5_memory_parts.layered import (
    build_layered_memory_context,
    prepare_workspace_memory_context,
    record_completed_turn_memory,
)
from b5_memory_parts.legacy import load_memory, save_memory

__all__ = [
    "append_conversation_message",
    "build_layered_memory_context",
    "build_parser",
    "delete_conversation_record",
    "init_conversation_db",
    "list_conversation_history",
    "list_conversation_messages",
    "list_conversation_records",
    "list_conversation_tasks",
    "list_message_tool_steps",
    "load_memory",
    "main",
    "parse_bool",
    "prepare_workspace_memory_context",
    "record_completed_turn_memory",
    "record_conversation_tool_step",
    "save_memory",
    "update_conversation_message",
    "upsert_conversation_record",
]


if __name__ == "__main__":
    raise SystemExit(main())
