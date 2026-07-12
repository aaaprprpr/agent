from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Any

RECENT_CONTEXT_TURNS = 4
MAX_RECALLED_BLOCKS = 3
MAX_RECALLED_TURNS = 5
MAX_SOURCE_SNIPPET_CHARS = 360
MAX_TOOL_SNIPPET_CHARS = 280
MAX_WORKSPACE_ITEM_CHARS = 420


def _compact_text(value: str, limit: int = 1200) -> str:
    compact = " ".join(str(value).split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _unique_strings(values: list[Any], limit: int | None = None) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if limit is not None and len(result) >= limit:
            break
    return result


def _compact_jsonish(value: Any, limit: int = MAX_WORKSPACE_ITEM_CHARS) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _compact_text(value, limit)
    if isinstance(value, list):
        return [_compact_jsonish(item, limit) for item in value[:8]]
    if isinstance(value, dict):
        return {str(key): _compact_jsonish(item, limit) for key, item in list(value.items())[:16]}
    return _compact_text(str(value), limit)


def _task_query_text(tasks: list[dict]) -> str:
    parts = []
    for task in tasks[:4]:
        parts.extend(
            [
                task.get("title"),
                task.get("objective"),
                task.get("phase"),
                " ".join(_safe_list(task.get("completed_items"))),
                " ".join(_safe_list(task.get("pending_items"))),
                " ".join(_safe_list(task.get("constraints"))),
                " ".join(_safe_list(task.get("active_files"))),
                " ".join(_safe_list(task.get("next_actions"))),
            ]
        )
    return "\n".join(item for item in parts if isinstance(item, str) and item.strip())


def _history_query_text(history_messages: list[dict], message_limit: int = 6) -> str:
    recent = history_messages[-message_limit:]
    return "\n".join(_compact_text(message.get("content", ""), 220) for message in recent)


def _text_similarity(query_text: str, candidate_text: str) -> float:
    query = _compact_text(query_text, 1600).casefold()
    candidate = _compact_text(candidate_text, 1600).casefold()
    if not query or not candidate:
        return 0.0
    return SequenceMatcher(None, query, candidate).ratio()


def _block_search_text(block: dict) -> str:
    return "\n".join(
        str(item)
        for item in [
            block.get("title"),
            block.get("summary"),
            " ".join(_safe_list(block.get("keywords"))),
        ]
        if item
    )


def _turn_search_text(turn: dict) -> str:
    return "\n".join(
        str(item)
        for item in [
            turn.get("summary"),
            " ".join(_safe_list(turn.get("keywords"))),
            " ".join(_safe_list(turn.get("facts"))),
            " ".join(_safe_list(turn.get("decisions"))),
            " ".join(_safe_list(turn.get("corrections"))),
            " ".join(_safe_list(turn.get("labels"))),
        ]
        if item
    )


def _score_block(block: dict, query_text: str, newest_turn_index: int) -> float:
    similarity = _text_similarity(query_text, _block_search_text(block))
    recency = 0.0
    if newest_turn_index > 0:
        recency = min(1.0, max(0.0, float(block.get("end_turn_index") or 0) / newest_turn_index))
    return round(similarity * 2.0 + recency * 0.2, 4)


def _score_turn(turn: dict, query_text: str, newest_turn_index: int) -> float:
    similarity = _text_similarity(query_text, _turn_search_text(turn))
    current_task = float(turn.get("current_task_relevance") or 0.0)
    long_term = float(turn.get("long_term_value") or 0.0)
    signal = 0.0
    if turn.get("has_decision"):
        signal += 0.35
    if turn.get("has_user_correction"):
        signal += 0.3
    if turn.get("has_explicit_fact"):
        signal += 0.2
    recency = 0.0
    if newest_turn_index > 0:
        recency = min(1.0, max(0.0, float(turn.get("turn_index") or 0) / newest_turn_index))
    noise = float(turn.get("noise_score") or 0.0)
    drop_penalty = 0.5 if turn.get("allow_drop") else 0.0
    return round(similarity * 2.0 + current_task * 0.35 + long_term * 0.45 + signal + recency * 0.15 - noise - drop_penalty, 4)


def _list_text(title: str, values: Any, limit: int = 4) -> str | None:
    items = _unique_strings(_safe_list(values), limit)
    if not items:
        return None
    return f"{title}: " + "; ".join(items)


def _clip_source_text(value: Any, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    compact = _compact_text(text, limit)
    return compact


def _source_message_context(messages: list[dict]) -> list[dict]:
    result = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        result.append(
            {
                "message_id": message.get("id"),
                "role": message.get("role"),
                "message_order": message.get("message_order"),
                "created_at": message.get("created_at"),
                "content": _clip_source_text(message.get("content"), MAX_SOURCE_SNIPPET_CHARS),
            }
        )
    return result


def _source_tool_context(tool_steps: list[dict]) -> list[dict]:
    result = []
    for step in tool_steps:
        if not isinstance(step, dict):
            continue
        result.append(
            {
                "tool_step_id": step.get("id"),
                "tool_name": step.get("tool_name"),
                "status": step.get("status"),
                "created_at": step.get("created_at"),
                "input": _compact_jsonish(step.get("input"), MAX_TOOL_SNIPPET_CHARS),
                "output": _compact_jsonish(step.get("output"), MAX_TOOL_SNIPPET_CHARS),
                "error": _compact_jsonish(step.get("error"), MAX_TOOL_SNIPPET_CHARS),
            }
        )
    return result


def _foreground_task(tasks: list[dict]) -> dict | None:
    for task in tasks:
        if isinstance(task, dict) and task.get("status") == "foreground":
            return task
    return None


def _paused_tasks(tasks: list[dict]) -> list[dict]:
    return [task for task in tasks if isinstance(task, dict) and task.get("status") == "paused"]


def _append_budgeted_line(lines: list[str], line: str, budget: dict) -> None:
    if budget["remaining"] <= 0:
        return
    text = str(line).rstrip()
    if not text:
        return
    required = len(text) + 1
    if required > budget["remaining"]:
        if budget["remaining"] <= 8:
            return
        text = text[: budget["remaining"] - 4].rstrip() + "..."
        required = len(text) + 1
        budget["truncated"] = True
    lines.append(text)
    budget["remaining"] -= required


def _build_memory_context_text(
    *,
    tasks: list[dict],
    selected_blocks: list[dict],
    selected_turns: list[dict],
    source_messages: list[dict],
    source_tool_steps: list[dict],
    legacy_docs: list[dict],
    max_chars: int,
) -> tuple[str, bool]:
    has_context = bool(tasks or selected_blocks or selected_turns or source_messages or source_tool_steps or legacy_docs)
    if not has_context:
        return "", False
    lines: list[str] = []
    budget = {"remaining": max(800, int(max_chars)), "truncated": False}
    _append_budgeted_line(lines, "[B5 layered memory context]", budget)
    _append_budgeted_line(
        lines,
        "Use this memory as historical context only. Current user input has priority. Summaries locate sources; exact facts must come from source snippets or current tool results.",
        budget,
    )
    foreground = [task for task in tasks if task.get("status") == "foreground"]
    paused = [task for task in tasks if task.get("status") == "paused"]
    if foreground or paused:
        _append_budgeted_line(lines, "\n[Task memory]", budget)
    for task in foreground[:1]:
        _append_budgeted_line(
            lines,
            f"- foreground task {task.get('id')}: {task.get('title')} | objective={task.get('objective') or ''} | phase={task.get('phase') or ''}",
            budget,
        )
        for optional in (
            _list_text("completed", task.get("completed_items")),
            _list_text("pending", task.get("pending_items")),
            _list_text("constraints", task.get("constraints")),
            _list_text("active files", task.get("active_files")),
            _list_text("next", task.get("next_actions")),
        ):
            if optional:
                _append_budgeted_line(lines, f"  {optional}", budget)
    for task in paused[:3]:
        _append_budgeted_line(
            lines,
            f"- paused task {task.get('id')}: {task.get('title')} | phase={task.get('phase') or ''}",
            budget,
        )

    if selected_blocks:
        _append_budgeted_line(lines, "\n[Recalled blocks]", budget)
    for block in selected_blocks:
        _append_budgeted_line(
            lines,
            f"- block {block.get('id')} turns {block.get('start_turn_index')}-{block.get('end_turn_index')}: {block.get('summary')}",
            budget,
        )

    if selected_turns:
        _append_budgeted_line(lines, "\n[Recalled turns]", budget)
    for turn in selected_turns:
        source_ids = _safe_list(turn.get("source_message_ids"))
        tool_ids = _safe_list(turn.get("source_tool_step_ids"))
        _append_budgeted_line(
            lines,
            f"- turn {turn.get('turn_index')} ({turn.get('turn_id')}): {turn.get('summary')} | source_messages={source_ids} | source_tools={tool_ids}",
            budget,
        )
        details = []
        for field, label in (("decisions", "decisions"), ("corrections", "corrections"), ("facts", "facts")):
            values = _unique_strings(_safe_list(turn.get(field)), 3)
            if values:
                details.append(f"{label}: {'; '.join(values)}")
        if details:
            _append_budgeted_line(lines, "  " + " | ".join(details), budget)

    if source_messages:
        _append_budgeted_line(lines, "\n[Loaded source message snippets]", budget)
    for message in source_messages:
        _append_budgeted_line(
            lines,
            f"- message {message.get('id')} role={message.get('role')} order={message.get('message_order')}: {_clip_source_text(message.get('content'), MAX_SOURCE_SNIPPET_CHARS)}",
            budget,
        )

    if source_tool_steps:
        _append_budgeted_line(lines, "\n[Loaded source tool snippets]", budget)
    for step in source_tool_steps:
        payload = {
            "input": step.get("input"),
            "output": step.get("output"),
            "error": step.get("error"),
        }
        _append_budgeted_line(
            lines,
            f"- tool_step {step.get('id')} name={step.get('tool_name')} status={step.get('status')}: {_clip_source_text(payload, MAX_TOOL_SNIPPET_CHARS)}",
            budget,
        )

    if legacy_docs:
        _append_budgeted_line(lines, "\n[Selected legacy memory documents]", budget)
    for doc in legacy_docs:
        _append_budgeted_line(
            lines,
            f"- {doc.get('memory_id')} {doc.get('title')}: {_clip_source_text(doc.get('content'), MAX_SOURCE_SNIPPET_CHARS)}",
            budget,
        )
    return "\n".join(lines).strip(), bool(budget["truncated"])
