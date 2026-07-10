from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from common.logging_utils import now_iso


SCHEMA_VERSION = 1


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def init_store(db_path: str | Path) -> dict:
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                is_trivial INTEGER NOT NULL DEFAULT 0,
                trivial_reason TEXT,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_message_at TEXT
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
                content TEXT NOT NULL,
                message_order INTEGER NOT NULL,
                run_id TEXT,
                is_trivial INTEGER NOT NULL DEFAULT 0,
                token_count INTEGER,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                UNIQUE (conversation_id, message_order)
            );

            CREATE TABLE IF NOT EXISTS tool_steps (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                assistant_message_id TEXT NOT NULL,
                run_id TEXT,
                step_index INTEGER NOT NULL,
                tool_call_id TEXT,
                tool_name TEXT NOT NULL,
                input_json TEXT,
                output_json TEXT,
                status TEXT NOT NULL,
                error_json TEXT,
                latency_ms REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (assistant_message_id) REFERENCES conversation_messages(id) ON DELETE CASCADE,
                UNIQUE (assistant_message_id, step_index)
            );

            CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_order
                ON conversation_messages(conversation_id, message_order);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_role
                ON conversation_messages(role);
            CREATE INDEX IF NOT EXISTS idx_tool_steps_message_order
                ON tool_steps(assistant_message_id, step_index);
            CREATE INDEX IF NOT EXISTS idx_tool_steps_conversation
                ON tool_steps(conversation_id, step_index);
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
    return {"status": "success", "db_path": str(Path(db_path).resolve()), "schema_version": SCHEMA_VERSION}


def upsert_conversation(
    db_path: str | Path,
    conversation_id: str,
    title: str,
    *,
    is_trivial: bool = False,
    trivial_reason: str | None = None,
    summary: str | None = None,
    status: str = "active",
) -> dict:
    init_store(db_path)
    now = now_iso()
    with _connect(db_path) as connection:
        existing = connection.execute(
            "SELECT created_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        connection.execute(
            """
            INSERT INTO conversations(
                id, title, is_trivial, trivial_reason, summary, status, created_at, updated_at, last_message_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT last_message_at FROM conversations WHERE id = ?), NULL))
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                is_trivial = excluded.is_trivial,
                trivial_reason = excluded.trivial_reason,
                summary = excluded.summary,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                title,
                int(is_trivial),
                trivial_reason,
                summary,
                status,
                created_at,
                now,
                conversation_id,
            ),
        )
    return {
        "status": "success",
        "conversation_id": conversation_id,
        "created_at": created_at,
        "updated_at": now,
    }


def append_message(
    db_path: str | Path,
    conversation_id: str,
    role: str,
    content: str,
    *,
    message_id: str | None = None,
    run_id: str | None = None,
    message_order: int | None = None,
    is_trivial: bool = False,
    token_count: int | None = None,
    metadata: dict | None = None,
) -> dict:
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("role must be system, user, assistant, or tool")
    if not isinstance(content, str) or not content:
        raise ValueError("content must be a non-empty string")
    init_store(db_path)
    now = now_iso()
    message_id = message_id or _new_id("msg")
    with _connect(db_path) as connection:
        if message_order is None:
            row = connection.execute(
                "SELECT COALESCE(MAX(message_order), 0) + 1 AS next_order FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            message_order = int(row["next_order"])
        connection.execute(
            """
            INSERT INTO conversation_messages(
                id, conversation_id, role, content, message_order, run_id, is_trivial,
                token_count, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                role,
                content,
                message_order,
                run_id,
                int(is_trivial),
                token_count,
                _json_dumps(metadata),
                now,
            ),
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ?, last_message_at = ? WHERE id = ?",
            (now, now, conversation_id),
        )
    return {
        "status": "success",
        "message_id": message_id,
        "conversation_id": conversation_id,
        "message_order": message_order,
        "created_at": now,
    }


def update_message(
    db_path: str | Path,
    message_id: str,
    *,
    content: str | None = None,
    token_count: int | None = None,
    metadata: dict | None = None,
) -> dict:
    if content is not None and (not isinstance(content, str) or not content):
        raise ValueError("content must be a non-empty string")
    init_store(db_path)
    now = now_iso()
    assignments = []
    values: list[Any] = []
    if content is not None:
        assignments.append("content = ?")
        values.append(content)
    if token_count is not None:
        assignments.append("token_count = ?")
        values.append(token_count)
    if metadata is not None:
        assignments.append("metadata_json = ?")
        values.append(_json_dumps(metadata))
    if not assignments:
        raise ValueError("update_message requires at least one field to update")
    values.append(message_id)
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT conversation_id FROM conversation_messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise ValueError("message_id does not exist")
        connection.execute(
            f"UPDATE conversation_messages SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ?, last_message_at = ? WHERE id = ?",
            (now, now, row["conversation_id"]),
        )
    return {"status": "success", "message_id": message_id, "updated_at": now}


def record_tool_step(
    db_path: str | Path,
    conversation_id: str,
    assistant_message_id: str,
    tool_name: str,
    *,
    step_id: str | None = None,
    run_id: str | None = None,
    step_index: int,
    tool_call_id: str | None = None,
    input_data: Any = None,
    output_data: Any = None,
    status: str,
    error: Any = None,
    latency_ms: float | None = None,
) -> dict:
    if step_index < 1:
        raise ValueError("step_index must be positive")
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name must be a non-empty string")
    if not isinstance(status, str) or not status:
        raise ValueError("status must be a non-empty string")
    init_store(db_path)
    now = now_iso()
    step_id = step_id or _new_id("tool_step")
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO tool_steps(
                id, conversation_id, assistant_message_id, run_id, step_index, tool_call_id,
                tool_name, input_json, output_json, status, error_json, latency_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                conversation_id,
                assistant_message_id,
                run_id,
                step_index,
                tool_call_id,
                tool_name,
                _json_dumps(input_data),
                _json_dumps(output_data),
                status,
                _json_dumps(error),
                latency_ms,
                now,
            ),
        )
    return {
        "status": "success",
        "tool_step_id": step_id,
        "conversation_id": conversation_id,
        "assistant_message_id": assistant_message_id,
        "step_index": step_index,
        "created_at": now,
    }


def list_conversations(db_path: str | Path, limit: int = 50) -> list[dict]:
    init_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, title, is_trivial, trivial_reason, summary, status,
                   created_at, updated_at, last_message_at
            FROM conversations
            ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_messages(db_path: str | Path, conversation_id: str) -> list[dict]:
    init_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, conversation_id, role, content, message_order, run_id,
                   is_trivial, token_count, metadata_json, created_at
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY message_order ASC
            """,
            (conversation_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _json_loads(item.get("metadata_json"))
        result.append(item)
    return result


def list_tool_steps(db_path: str | Path, assistant_message_id: str) -> list[dict]:
    init_store(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, conversation_id, assistant_message_id, run_id, step_index,
                   tool_call_id, tool_name, input_json, output_json, status,
                   error_json, latency_ms, created_at
            FROM tool_steps
            WHERE assistant_message_id = ?
            ORDER BY step_index ASC
            """,
            (assistant_message_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["input"] = _json_loads(item.get("input_json"))
        item["output"] = _json_loads(item.get("output_json"))
        item["error"] = _json_loads(item.get("error_json"))
        result.append(item)
    return result
