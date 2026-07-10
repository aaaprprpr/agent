from __future__ import annotations

import json
import re
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


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _search_terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query.lower())
    terms: list[str] = []
    for item in raw_terms:
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            if len(item) >= 2:
                terms.append(item)
                terms.extend(item[index : index + 2] for index in range(len(item) - 1))
            else:
                terms.append(item)
        elif len(item) >= 2:
            terms.append(item)
    seen: set[str] = set()
    unique_terms = []
    for term in terms:
        if term not in seen:
            unique_terms.append(term)
            seen.add(term)
    return unique_terms[:12]


def _fts_query(terms: list[str]) -> str:
    safe_terms = [term.replace('"', '""') for term in terms if term.strip()]
    return " OR ".join(f'"{term}"' for term in safe_terms)


def _ensure_message_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS conversation_messages_fts
            USING fts5(
                message_id UNINDEXED,
                conversation_id UNINDEXED,
                role UNINDEXED,
                content,
                tokenize = 'unicode61'
            )
            """
        )
        row = connection.execute("SELECT COUNT(*) AS count FROM conversation_messages_fts").fetchone()
        if row and int(row["count"]) == 0:
            connection.execute(
                """
                INSERT INTO conversation_messages_fts(message_id, conversation_id, role, content)
                SELECT id, conversation_id, role, content
                FROM conversation_messages
                """
            )
        return True
    except sqlite3.OperationalError:
        return False


def _index_message_fts(
    connection: sqlite3.Connection,
    message_id: str,
    conversation_id: str,
    role: str,
    content: str,
) -> None:
    if not _ensure_message_fts(connection):
        return
    try:
        connection.execute("DELETE FROM conversation_messages_fts WHERE message_id = ?", (message_id,))
        connection.execute(
            """
            INSERT INTO conversation_messages_fts(message_id, conversation_id, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content),
        )
    except sqlite3.OperationalError:
        return


def _keyword_score(row: dict, terms: list[str], current_conversation_id: str | None = None) -> float:
    content = str(row.get("content", "")).lower()
    title = str(row.get("conversation_title", "")).lower()
    summary = str(row.get("conversation_summary") or "").lower()
    score = 0.0
    for term in terms:
        score += content.count(term)
        score += title.count(term) * 3
        score += summary.count(term) * 2
    role = row.get("role")
    if role == "assistant":
        score *= 1.15
    elif role == "tool":
        score *= 0.4
    elif role == "system":
        score *= 0.3
    if current_conversation_id and row.get("conversation_id") == current_conversation_id:
        score += 2.0
    return round(score, 4)


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
        fts_enabled = _ensure_message_fts(connection)
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
    return {
        "status": "success",
        "db_path": str(Path(db_path).resolve()),
        "schema_version": SCHEMA_VERSION,
        "fts_enabled": fts_enabled,
    }


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
        _index_message_fts(connection, message_id, conversation_id, role, content)
    return {
        "status": "success",
        "message_id": message_id,
        "conversation_id": conversation_id,
        "message_order": message_order,
        "created_at": now,
    }


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
    return [dict(row) for row in rows]


def search_messages(
    db_path: str | Path,
    query: str,
    *,
    limit: int = 8,
    conversation_id: str | None = None,
    exclude_conversation_id: str | None = None,
    include_trivial: bool = False,
    roles: tuple[str, ...] = ("user", "assistant"),
) -> list[dict]:
    if not isinstance(query, str) or not query.strip():
        return []
    terms = _search_terms(query)
    if not terms:
        return []
    limit = max(1, int(limit))
    init_store(db_path)

    role_values = tuple(role for role in roles if role in {"system", "user", "assistant", "tool"})
    if not role_values:
        role_values = ("user", "assistant")

    rows_by_id: dict[str, dict] = {}
    with _connect(db_path) as connection:
        conditions = [f"m.role IN ({','.join('?' for _ in role_values)})"]
        params: list[Any] = list(role_values)
        if conversation_id:
            conditions.append("m.conversation_id = ?")
            params.append(conversation_id)
        if exclude_conversation_id:
            conditions.append("m.conversation_id != ?")
            params.append(exclude_conversation_id)
        if not include_trivial:
            conditions.append("m.is_trivial = 0")
            conditions.append("c.is_trivial = 0")
        where_sql = " AND ".join(conditions)
        select_sql = """
            SELECT m.id, m.conversation_id, m.role, m.content, m.message_order, m.run_id,
                   m.is_trivial, m.token_count, m.metadata_json, m.created_at,
                   c.title AS conversation_title, c.summary AS conversation_summary,
                   c.is_trivial AS conversation_is_trivial,
                   c.updated_at AS conversation_updated_at,
                   c.last_message_at AS conversation_last_message_at
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
        """

        fts_enabled = _ensure_message_fts(connection)
        fts_query = _fts_query(terms)
        if fts_enabled and fts_query:
            try:
                fts_rows = connection.execute(
                    f"""
                    {select_sql}
                    JOIN conversation_messages_fts ON conversation_messages_fts.message_id = m.id
                    WHERE conversation_messages_fts MATCH ? AND {where_sql}
                    ORDER BY m.created_at DESC
                    LIMIT ?
                    """,
                    [fts_query, *params, limit * 3],
                ).fetchall()
                for row in fts_rows:
                    data = dict(row)
                    data["search_backend"] = "fts5"
                    rows_by_id[data["id"]] = data
            except sqlite3.OperationalError:
                pass

        like_terms = terms[:8]
        like_clauses = []
        like_params: list[str] = []
        for term in like_terms:
            like_clauses.append(
                "(LOWER(m.content) LIKE ? OR LOWER(c.title) LIKE ? OR LOWER(COALESCE(c.summary, '')) LIKE ?)"
            )
            pattern = f"%{term}%"
            like_params.extend([pattern, pattern, pattern])
        if like_clauses:
            like_rows = connection.execute(
                f"""
                {select_sql}
                WHERE {where_sql} AND ({' OR '.join(like_clauses)})
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                [*params, *like_params, limit * 3],
            ).fetchall()
            for row in like_rows:
                data = dict(row)
                data["search_backend"] = rows_by_id.get(data["id"], {}).get("search_backend", "like")
                rows_by_id[data["id"]] = data

    ranked = []
    for row in rows_by_id.values():
        row["search_terms"] = terms
        row["search_score"] = _keyword_score(row, terms, conversation_id)
        ranked.append(row)
    ranked.sort(key=lambda item: (float(item.get("search_score", 0.0)), str(item.get("created_at", ""))), reverse=True)
    return ranked[:limit]


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
    return [dict(row) for row in rows]
