from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from common.io_utils import append_jsonl, read_json, read_text, read_yaml, write_json, write_text
from common.conversation_store import (
    append_message,
    delete_conversation,
    init_store,
    list_conversations,
    list_conversation_turns,
    list_unblocked_conversation_turns,
    list_messages,
    list_memory_blocks,
    list_messages_by_ids,
    list_task_memories,
    list_tool_steps,
    list_tool_steps_by_ids,
    list_turn_summaries,
    record_memory_retrieval,
    record_tool_step,
    upsert_conversation_turn,
    upsert_memory_block,
    upsert_task_memory,
    upsert_turn_memory_tags,
    upsert_turn_summary,
    update_message,
    upsert_conversation,
)
from common.logging_utils import now_iso
from common.identifiers import validate_conversation_id
from common.path_utils import resolve_cli_path, resolve_from_file
from common.schemas import normalize_history_messages


RECENT_CONTEXT_TURNS = 4
MAX_RECALLED_BLOCKS = 3
MAX_RECALLED_TURNS = 5
MAX_SOURCE_SNIPPET_CHARS = 360
MAX_TOOL_SNIPPET_CHARS = 280


def _memory_paths(config_path: str | Path) -> dict[str, Path | int]:
    path = Path(config_path).resolve()
    config = read_yaml(path)
    if not isinstance(config, dict) or not isinstance(config.get("memory"), dict):
        raise ValueError("memory.yaml must define a memory object")
    memory = config["memory"]
    required = ["root_dir", "global_memory_dir", "conversation_memory_dir", "index_path", "max_memory_chars"]
    missing = [name for name in required if name not in memory]
    if missing:
        raise ValueError(f"memory.yaml missing: {', '.join(missing)}")
    root = resolve_from_file(memory["root_dir"], path)
    max_chars = memory["max_memory_chars"]
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_memory_chars must be a positive integer")
    return {
        "root": root,
        "global": root / memory["global_memory_dir"],
        "conversations": root / memory["conversation_memory_dir"],
        "index": root / memory["index_path"],
        "conversation_db": root / memory.get("conversation_db_path", "conversation_store.sqlite3"),
        "max_chars": max_chars,
    }


def _conversation_db_path(config_path: str | Path) -> Path:
    return Path(_memory_paths(config_path)["conversation_db"])


def _read_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {}
    index = read_json(index_path)
    if not isinstance(index, dict):
        raise ValueError("memory_index.json must be an object")
    return index


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
        if metadata.get("ui_status") in {"pending", "error"}:
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


def _neutral_locator_summary() -> str:
    return (
        "Memory reflection was unavailable for this turn. "
        "Use the linked source messages and tool steps for all facts, paths, commands, code, errors, and outputs."
    )


def _safe_summary_items(value: Any) -> list:
    items = []
    if not isinstance(value, list):
        return items
    for item in value:
        if not isinstance(item, str):
            continue
        compact = _compact_text(item, 180)
        if compact:
            items.append(compact)
    return items


def _tool_refs_from_steps(tool_steps: list[dict]) -> list[dict]:
    refs = []
    for step in tool_steps:
        if not isinstance(step, dict):
            continue
        refs.append(
            {
                "tool_step_id": step.get("id"),
                "tool_call_id": step.get("tool_call_id"),
                "tool_name": step.get("tool_name"),
                "status": step.get("status"),
            }
        )
    return refs


def _artifact_refs_from_steps(tool_steps: list[dict]) -> list[dict]:
    refs = []
    for step in tool_steps:
        if not isinstance(step, dict):
            continue
        output = step.get("output") if isinstance(step.get("output"), dict) else {}
        if not isinstance(output, dict):
            continue
        if "relative_output_path" in output or "generated_file_path" in output:
            refs.append(
                {
                    "tool_step_id": step.get("id"),
                    "tool_name": step.get("tool_name"),
                    "artifact_type": "generated_file",
                }
            )
    return refs


def _neutral_memory_decision(
    raw_user_input: str,
    final_answer: str,
    trace: dict,
    source_message_ids: list[str],
    source_tool_step_ids: list[str],
    tool_steps: list[dict],
) -> dict:
    tags = {
        "current_task_relevance": 0.5,
        "long_term_value": 0.5,
        "has_explicit_fact": False,
        "has_decision": False,
        "has_user_correction": False,
        "allow_compress": True,
        "allow_drop": False,
        "noise_score": 0.0,
        "labels": ["model_reflection_unavailable"],
    }
    summary = {
        "summary": _neutral_locator_summary(),
        "keywords": [],
        "facts": [],
        "decisions": [],
        "corrections": [],
        "tool_refs": _tool_refs_from_steps(tool_steps),
        "artifact_refs": _artifact_refs_from_steps(tool_steps),
        "source_message_ids": source_message_ids,
        "source_tool_step_ids": source_tool_step_ids,
    }
    task_memory = {
        "action": "no_change",
        "status": "foreground",
        "title": "",
        "objective": "",
        "phase": "",
        "completed_items": [],
        "pending_items": [],
        "constraints": [],
        "key_results": [],
        "active_files": [],
        "blocked_items": [],
        "next_actions": [],
        "source_turn_ids": [],
        "confidence": 0.35,
    }
    return {
        "source": "neutral_fallback",
        "turn_tags": tags,
        "turn_summary": summary,
        "task_memory": task_memory,
        "trace_status": trace.get("status") if isinstance(trace, dict) else None,
    }


def _memory_reflection_messages(
    raw_user_input: str,
    final_answer: str,
    trace: dict,
    tool_steps: list[dict],
    existing_tasks: list[dict],
) -> list[dict]:
    compact_trace = {
        "status": trace.get("status"),
        "tool_rounds_used": trace.get("tool_rounds_used"),
        "llm_call_count": trace.get("llm_call_count"),
        "final_state": trace.get("final_state"),
        "finish_reason": trace.get("finish_reason"),
    } if isinstance(trace, dict) else {}
    compact_tools = []
    for step in tool_steps:
        compact_tools.append(
            {
                "tool_step_id": step.get("id"),
                "tool_call_id": step.get("tool_call_id"),
                "tool_name": step.get("tool_name"),
                "status": step.get("status"),
                "has_error": bool(step.get("error")),
                "latency_ms": step.get("latency_ms"),
            }
        )
    observation = {
        "user_input": _compact_text(raw_user_input, 1800),
        "final_answer": _compact_text(final_answer, 1800),
        "trace": compact_trace,
        "tool_steps": compact_tools,
        "existing_tasks": [
            {
                "task_id": task.get("id"),
                "status": task.get("status"),
                "title": task.get("title"),
                "objective": task.get("objective"),
                "phase": task.get("phase"),
            }
            for task in existing_tasks[:8]
        ],
    }
    schema_hint = {
        "turn_tags": {
            "current_task_relevance": "0..1",
            "long_term_value": "0..1",
            "has_explicit_fact": "boolean",
            "has_decision": "boolean",
            "has_user_correction": "boolean",
            "allow_compress": "boolean",
            "allow_drop": "boolean",
            "noise_score": "0..1",
            "labels": ["short labels"],
        },
        "turn_summary": {
            "summary": "short locator summary; never include exact paths, commands, code, parameters, or error text",
            "keywords": [],
            "facts": [],
            "decisions": [],
            "corrections": [],
        },
        "task_memory": {
            "action": "no_change | update_foreground | switch_task | resume_task | pause_task | complete_task",
            "target_task_id": "optional existing task id",
            "status": "foreground | paused | completed | abandoned",
            "title": "task title",
            "objective": "task objective",
            "phase": "task phase",
            "completed_items": [],
            "pending_items": [],
            "constraints": [],
            "key_results": [],
            "active_files": [],
            "blocked_items": [],
            "next_actions": [],
            "confidence": "0..1",
        },
    }
    system = (
        "You are the B5 memory reflector. Decide what should be remembered from one completed Agent turn. "
        "Return exactly one AIMessage JSON object. The AIMessage content must itself be a valid JSON object string "
        "matching the requested memory schema. Do not call tools. "
        "Summaries are only locators: do not copy exact file paths, commands, code, parameters, traceback text, or tool output values. "
        "When exact facts are needed later, the system will load source messages and tool steps."
    )
    user = (
        "Memory schema:\n"
        + json.dumps(schema_hint, ensure_ascii=False, indent=2)
        + "\n\nCompleted turn observation:\n"
        + json.dumps(observation, ensure_ascii=False, indent=2)
        + "\n\nReturn AIMessage JSON now. Use tool_calls=[] and control.action=finish."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _coerce_memory_decision(
    candidate: dict,
    source_message_ids: list[str],
    source_tool_step_ids: list[str],
    tool_steps: list[dict],
) -> dict:
    if not isinstance(candidate, dict):
        raise ValueError("memory decision must be an object")
    tags = candidate.get("turn_tags")
    summary = candidate.get("turn_summary")
    task = candidate.get("task_memory")
    if not isinstance(tags, dict) or not isinstance(summary, dict) or not isinstance(task, dict):
        raise ValueError("memory decision missing turn_tags, turn_summary, or task_memory")
    summary = dict(summary)
    summary_text = summary.get("summary")
    if isinstance(summary_text, str):
        summary["summary"] = _compact_text(summary_text, 360)
    summary["keywords"] = _safe_summary_items(summary.get("keywords"))
    summary["facts"] = _safe_summary_items(summary.get("facts"))
    summary["decisions"] = _safe_summary_items(summary.get("decisions"))
    summary["corrections"] = _safe_summary_items(summary.get("corrections"))
    summary["tool_refs"] = _tool_refs_from_steps(tool_steps)
    summary["artifact_refs"] = _artifact_refs_from_steps(tool_steps)
    summary["source_message_ids"] = source_message_ids
    summary["source_tool_step_ids"] = source_tool_step_ids
    if not isinstance(summary.get("summary"), str) or not summary["summary"].strip():
        summary["summary"] = _neutral_locator_summary()
    task = dict(task)
    task.setdefault("action", "no_change")
    task.setdefault("status", "foreground")
    task.setdefault("source_turn_ids", [])
    return {"source": "model", "turn_tags": tags, "turn_summary": summary, "task_memory": task}


def _reflect_memory_with_model(
    model_config: str,
    llm_mode: str | None,
    artifact_dir: str | None,
    raw_user_input: str,
    final_answer: str,
    trace: dict,
    tool_steps: list[dict],
    existing_tasks: list[dict],
    source_message_ids: list[str],
    source_tool_step_ids: list[str],
) -> dict:
    mode = llm_mode or "prompt_json"
    if mode != "prompt_json":
        raise ValueError("memory reflection model is only enabled in prompt_json mode")
    from b4_local_agent_llm import generate_ai_message

    result = generate_ai_message(
        model_config,
        _memory_reflection_messages(raw_user_input, final_answer, trace, tool_steps, existing_tasks),
        [],
        mode,
        artifact_dir,
        "memory_reflection",
        prompt_ready=False,
    )
    if result.get("status") != "success":
        raise ValueError(f"memory reflection failed: {result.get('error')}")
    ai_message = result.get("ai_message") if isinstance(result.get("ai_message"), dict) else {}
    content = ai_message.get("content")
    if not isinstance(content, str):
        raise ValueError("memory reflection content must be a JSON string")
    return _coerce_memory_decision(json.loads(content), source_message_ids, source_tool_step_ids, tool_steps)


def _apply_task_memory_decision(
    config_path: str,
    conversation_id: str,
    turn_id: str,
    task_memory: dict,
) -> dict:
    action = task_memory.get("action")
    if action not in {"update_foreground", "switch_task", "resume_task", "pause_task", "complete_task"}:
        return {"status": "skipped", "reason": "no task memory update requested"}
    task = dict(task_memory)
    task["source_turn_ids"] = list(dict.fromkeys([*(_safe_list(task.get("source_turn_ids"))), turn_id]))
    if action in {"pause_task"}:
        task["status"] = "paused"
    elif action in {"complete_task"}:
        task["status"] = "completed"
    else:
        task["status"] = "foreground"
    title = task.get("title")
    if not isinstance(title, str) or not title.strip():
        task["title"] = "当前任务"
    return upsert_task_memory(
        _conversation_db_path(config_path),
        conversation_id,
        task,
        task_id=task.get("target_task_id") if isinstance(task.get("target_task_id"), str) else None,
    )


def _maybe_create_memory_block(config_path: str, conversation_id: str, min_turns: int = 6) -> dict:
    db_path = _conversation_db_path(config_path)
    turns = list_unblocked_conversation_turns(db_path, conversation_id, min_turns)
    if len(turns) < min_turns:
        return {"status": "skipped", "reason": "not enough turns"}
    block_turns = turns[:min_turns]
    start = block_turns[0]["turn_index"]
    end = block_turns[-1]["turn_index"]
    turn_ids = [turn["id"] for turn in block_turns]
    summaries = list_turn_summaries(db_path, conversation_id, turn_ids=turn_ids)
    summaries.sort(key=lambda item: int(item.get("turn_index") or 0))
    keywords = _unique_strings(
        [
            keyword
            for summary in summaries
            for keyword in [
                *_safe_list(summary.get("keywords")),
                *_safe_list(summary.get("labels")),
            ]
        ],
        16,
    )
    representative = []
    for summary in summaries[:4]:
        text = summary.get("summary")
        if isinstance(text, str) and text.strip():
            representative.append(f"turn {summary.get('turn_index')}: {_compact_text(text, 120)}")
    topic_text = ", ".join(keywords[:6]) if keywords else "general conversation"
    block = {
        "title": f"Turns {start}-{end}: {topic_text}",
        "summary": (
            f"Block covering turns {start}-{end}. Topics: {topic_text}. "
            + ("Representative turn summaries: " + " | ".join(representative) + ". " if representative else "")
            + "Use linked turn summaries first, then load original messages/tool steps for exact facts."
        ),
        "status": "active",
        "keywords": keywords,
        "source": "derived_from_turn_summaries",
    }
    return upsert_memory_block(
        db_path,
        conversation_id,
        block,
        turn_ids,
    )


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


def build_layered_memory_context(
    config_path: str,
    conversation_id: str,
    current_user_input: str,
    history_messages: list[dict],
    selected_memory: dict | None = None,
    outdir: str | None = None,
) -> dict:
    """Build layered memory context for a future context assembler.

    Recent raw messages are returned separately and are never summarized here.
    Older history is recalled through block -> turn -> source-message/tool-step
    references so the model can use summaries for locating, not as final facts.
    """
    conversation_id = _safe_conversation_id(conversation_id)
    normalized_history = normalize_history_messages(history_messages)
    recent_history = normalized_history[-RECENT_CONTEXT_TURNS * 2 :]
    paths = _memory_paths(config_path)
    db_path = _conversation_db_path(config_path)
    max_chars = int(paths["max_chars"])
    tasks = list_conversation_tasks(config_path, conversation_id)
    turns = list_conversation_turns(db_path, conversation_id)
    newest_turn_index = max([int(turn.get("turn_index") or 0) for turn in turns], default=0)
    recent_turn_ids = {turn["id"] for turn in turns[-RECENT_CONTEXT_TURNS:] if isinstance(turn.get("id"), str)}
    query_text = "\n".join(
        item
        for item in [
            current_user_input,
            _history_query_text(normalized_history),
            _task_query_text(tasks),
        ]
        if isinstance(item, str) and item.strip()
    )

    blocks = list_memory_blocks(db_path, conversation_id, status="active")
    scored_blocks = []
    for block in blocks:
        score = _score_block(block, query_text, newest_turn_index)
        if score > 0.05:
            item = dict(block)
            item["score"] = score
            scored_blocks.append(item)
    scored_blocks.sort(key=lambda item: (item["score"], item.get("end_turn_index") or 0), reverse=True)
    selected_blocks = scored_blocks[:MAX_RECALLED_BLOCKS]

    block_ids = [block["id"] for block in selected_blocks if isinstance(block.get("id"), str)]
    candidate_turns = list_turn_summaries(db_path, conversation_id, block_ids=block_ids) if block_ids else []
    all_old_candidates = list_turn_summaries(
        db_path,
        conversation_id,
        exclude_turn_ids=list(recent_turn_ids),
        limit=40,
    )
    by_turn_id: dict[str, dict] = {}
    for turn in [*candidate_turns, *all_old_candidates]:
        turn_id = turn.get("turn_id")
        if not isinstance(turn_id, str) or turn_id in recent_turn_ids:
            continue
        existing = by_turn_id.get(turn_id)
        if existing is None or (turn.get("block_id") and not existing.get("block_id")):
            by_turn_id[turn_id] = turn

    scored_turns = []
    for turn in by_turn_id.values():
        score = _score_turn(turn, query_text, newest_turn_index)
        high_value = (
            bool(turn.get("has_decision"))
            or bool(turn.get("has_user_correction"))
            or float(turn.get("long_term_value") or 0.0) >= 0.7
        )
        if score <= 0.1 and not high_value:
            continue
        item = dict(turn)
        item["score"] = score
        scored_turns.append(item)
    scored_turns.sort(key=lambda item: (item["score"], item.get("turn_index") or 0), reverse=True)
    selected_turns = scored_turns[:MAX_RECALLED_TURNS]

    source_message_ids = _unique_strings(
        [
            source_id
            for turn in selected_turns
            for source_id in _safe_list(turn.get("source_message_ids"))
        ],
        MAX_RECALLED_TURNS * 2,
    )
    source_tool_step_ids = _unique_strings(
        [
            source_id
            for turn in selected_turns
            for source_id in _safe_list(turn.get("source_tool_step_ids"))
        ],
        MAX_RECALLED_TURNS * 4,
    )
    source_messages = list_messages_by_ids(db_path, source_message_ids)
    source_tool_steps = list_tool_steps_by_ids(db_path, source_tool_step_ids)

    legacy_docs = []
    if isinstance(selected_memory, dict):
        legacy_docs = [
            doc
            for doc in _safe_list(selected_memory.get("selected_memory_docs"))
            if isinstance(doc, dict) and isinstance(doc.get("content"), str)
        ]

    context_text, truncated = _build_memory_context_text(
        tasks=tasks,
        selected_blocks=selected_blocks,
        selected_turns=selected_turns,
        source_messages=source_messages,
        source_tool_steps=source_tool_steps,
        legacy_docs=legacy_docs,
        max_chars=max_chars,
    )
    memory_messages = [{"role": "system", "content": context_text}] if context_text else []
    retrieval_log = record_memory_retrieval(
        db_path,
        conversation_id,
        current_user_input,
        query_context={
            "recent_context_turns": RECENT_CONTEXT_TURNS,
            "history_message_count": len(normalized_history),
            "recent_history_message_count": len(recent_history),
            "task_count": len(tasks),
            "query_chars": len(query_text),
        },
        candidate_blocks=[
            {
                "block_id": block.get("id"),
                "score": block.get("score"),
                "start_turn_index": block.get("start_turn_index"),
                "end_turn_index": block.get("end_turn_index"),
            }
            for block in selected_blocks
        ],
        selected_turns=[
            {
                "turn_id": turn.get("turn_id"),
                "turn_index": turn.get("turn_index"),
                "score": turn.get("score"),
                "source_message_ids": turn.get("source_message_ids"),
                "source_tool_step_ids": turn.get("source_tool_step_ids"),
            }
            for turn in selected_turns
        ],
        loaded_message_ids=[message.get("id") for message in source_messages],
    )
    result = {
        "status": "success",
        "conversation_id": conversation_id,
        "recent_context_turns": RECENT_CONTEXT_TURNS,
        "history_message_count": len(normalized_history),
        "recent_history_message_count": len(recent_history),
        "recent_history_messages": recent_history,
        "memory_messages": memory_messages,
        "context_chars": len(context_text),
        "max_context_chars": max_chars,
        "truncated": truncated,
        "tasks": tasks,
        "candidate_blocks": selected_blocks,
        "selected_turns": selected_turns,
        "loaded_message_ids": [message.get("id") for message in source_messages],
        "loaded_tool_step_ids": [step.get("id") for step in source_tool_steps],
        "retrieval_log": retrieval_log,
    }
    if outdir:
        output_dir = Path(outdir)
        write_json(result, output_dir / "layered_memory_context.json")
        append_jsonl(
            {
                "timestamp": now_iso(),
                "operation": "build_layered_context",
                "status": "success",
                "conversation_id": conversation_id,
                "selected_block_count": len(selected_blocks),
                "selected_turn_count": len(selected_turns),
                "context_chars": len(context_text),
            },
            output_dir / "memory_log.jsonl",
        )
    return result


def record_completed_turn_memory(
    config_path: str,
    conversation_id: str,
    run_id: str,
    user_message_id: str,
    assistant_message_id: str,
    raw_user_input: str,
    final_answer: str,
    trace: dict,
    model_config: str | None = None,
    llm_mode: str | None = None,
    artifact_dir: str | None = None,
) -> dict:
    """Record layered memory metadata for one completed web Agent turn.

    The original messages and tool_steps remain the source of truth. Summaries
    are locator metadata used for future retrieval and must point back to source
    message/tool-step ids.
    """
    conversation_id = _safe_conversation_id(conversation_id)
    turn = upsert_conversation_turn(
        _conversation_db_path(config_path),
        conversation_id,
        run_id,
        user_message_id,
        assistant_message_id,
        status=trace.get("status", "unknown") if isinstance(trace, dict) else "unknown",
    )
    turn_id = turn["turn_id"]
    tool_steps = list_message_tool_steps(config_path, assistant_message_id)
    source_message_ids = [user_message_id, assistant_message_id]
    source_tool_step_ids = [step["id"] for step in tool_steps if isinstance(step.get("id"), str)]
    existing_tasks = list_conversation_tasks(config_path, conversation_id)
    reflection_error = None
    decision = None
    if model_config:
        try:
            decision = _reflect_memory_with_model(
                model_config,
                llm_mode,
                artifact_dir,
                raw_user_input,
                final_answer,
                trace,
                tool_steps,
                existing_tasks,
                source_message_ids,
                source_tool_step_ids,
            )
        except Exception as exc:
            reflection_error = {"type": type(exc).__name__, "message": str(exc)}
    if decision is None:
        decision = _neutral_memory_decision(
            raw_user_input,
            final_answer,
            trace,
            source_message_ids,
            source_tool_step_ids,
            tool_steps,
        )
    tags_result = upsert_turn_memory_tags(
        _conversation_db_path(config_path),
        turn_id,
        decision["turn_tags"],
        source=decision.get("source", "neutral_fallback"),
    )
    summary_result = upsert_turn_summary(
        _conversation_db_path(config_path),
        turn_id,
        decision["turn_summary"],
        source=decision.get("source", "neutral_fallback"),
    )
    task_result = _apply_task_memory_decision(config_path, conversation_id, turn_id, decision["task_memory"])
    block_result = _maybe_create_memory_block(config_path, conversation_id)
    return {
        "status": "success",
        "turn": turn,
        "tags": tags_result,
        "summary": summary_result,
        "task_memory": task_result,
        "memory_block": block_result,
        "decision_source": decision.get("source", "neutral_fallback"),
        "reflection_error": reflection_error,
    }


def load_memory(
    config_path: str,
    selected_memory_ids: list[str],
    use_global_memory: bool,
    query: str | None = None,
    outdir: str | None = None,
) -> dict:
    if not isinstance(selected_memory_ids, list) or not all(isinstance(item, str) for item in selected_memory_ids):
        raise ValueError("selected_memory_ids must be a list of strings")
    paths = _memory_paths(config_path)
    index = _read_index(paths["index"])
    ordered_ids = []
    if use_global_memory:
        ordered_ids.extend(sorted(key for key, item in index.items() if item.get("memory_type") == "global"))
    ordered_ids.extend(selected_memory_ids)
    ordered_ids = list(dict.fromkeys(ordered_ids))

    docs = []
    errors = []
    any_truncated = False
    for memory_id in ordered_ids:
        metadata = index.get(memory_id)
        if not isinstance(metadata, dict):
            errors.append({"memory_id": memory_id, "type": "MemoryNotFound", "message": "memory_id does not exist"})
            continue
        relative_path = metadata.get("path")
        if not isinstance(relative_path, str):
            errors.append({"memory_id": memory_id, "type": "InvalidMetadata", "message": "memory path is missing"})
            continue
        document_path = (paths["root"] / relative_path).resolve()
        try:
            document_path.relative_to(paths["root"].resolve())
        except ValueError:
            errors.append({"memory_id": memory_id, "type": "InvalidPath", "message": "memory path escapes root"})
            continue
        if not document_path.is_file():
            errors.append({"memory_id": memory_id, "type": "FileNotFoundError", "message": f"memory file not found: {relative_path}"})
            continue
        original = read_text(document_path)
        remaining = int(paths["max_chars"]) - sum(item["included_chars"] for item in docs)
        included = original[:remaining] if remaining > 0 else ""
        truncated = len(included) < len(original)
        any_truncated = any_truncated or truncated
        if included:
            docs.append(
                {
                    "memory_id": memory_id,
                    "memory_type": metadata.get("memory_type"),
                    "title": metadata.get("title", memory_id),
                    "path": relative_path,
                    "content": included,
                    "original_chars": len(original),
                    "included_chars": len(included),
                    "truncated": truncated,
                }
            )
    if errors and docs:
        status = "partial"
    elif errors:
        status = "error"
    else:
        status = "success"
    result = {
        "status": status,
        "query": query,
        "selected_memory_docs": docs,
        "max_memory_chars": paths["max_chars"],
        "total_chars": sum(item["included_chars"] for item in docs),
        "truncated": any_truncated,
        "errors": errors,
    }
    if outdir:
        output_dir = Path(outdir)
        write_json(result, output_dir / "selected_memory.json")
        append_jsonl(
            {
                "timestamp": now_iso(),
                "operation": "load",
                "status": status,
                "selected_ids": [item["memory_id"] for item in docs],
                "errors": errors,
            },
            output_dir / "memory_log.jsonl",
        )
    return result


def _safe_conversation_id(conversation_id: str) -> str:
    return validate_conversation_id(conversation_id)


def save_memory(
    config_path: str,
    conversation_id: str,
    save_type: str,
    messages_path: str,
    trace_path: str,
    answer_path: str,
    outdir: str | None = None,
) -> dict:
    conversation_id = _safe_conversation_id(conversation_id)
    if save_type not in {"conversation", "global"}:
        raise ValueError("save_type must be conversation or global")
    paths = _memory_paths(config_path)
    messages = read_json(messages_path)
    trace = read_json(trace_path)
    answer = read_text(answer_path).strip()
    if not isinstance(messages, list) or not isinstance(trace, dict):
        raise ValueError("messages must be an array and trace must be an object")
    now = now_iso()
    memory_id = f"mem_{save_type}_{conversation_id}"
    target_dir = paths["conversations"] if save_type == "conversation" else paths["global"]
    relative_dir = "conversations" if save_type == "conversation" else "global"
    target_path = Path(target_dir) / f"{conversation_id}.md"
    relative_path = f"{relative_dir}/{conversation_id}.md"
    title = f"{save_type.title()} {conversation_id}"
    summary = answer[:200]
    markdown = (
        f"# {title}\n\n"
        f"- memory_id: `{memory_id}`\n"
        f"- conversation_id: `{conversation_id}`\n"
        f"- created_or_updated_at: `{now}`\n\n"
        "## Final Answer\n\n"
        f"{answer}\n\n"
        "## Messages\n\n```json\n"
        f"{json.dumps(messages, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Trace\n\n```json\n"
        f"{json.dumps(trace, ensure_ascii=False, indent=2)}\n```\n"
    )
    write_text(markdown, target_path)
    index = _read_index(paths["index"])
    existing = index.get(memory_id, {})
    created_at = existing.get("created_at", now)
    index[memory_id] = {
        "memory_id": memory_id,
        "memory_type": save_type,
        "title": title,
        "summary": summary,
        "path": relative_path,
        "conversation_id": conversation_id,
        "created_at": created_at,
        "updated_at": now,
    }
    write_json(index, paths["index"])
    result = {
        "status": "success",
        "memory_id": memory_id,
        "memory_type": save_type,
        "conversation_id": conversation_id,
        "title": title,
        "summary": summary,
        "path": relative_path,
        "index_path": Path(paths["index"]).name,
        "created_at": created_at,
        "updated_at": now,
        "source_paths": {
            "messages": str(messages_path),
            "trace": str(trace_path),
            "answer": str(answer_path),
        },
    }
    if outdir:
        output_dir = Path(outdir)
        write_json(result, output_dir / "saved_memory.json")
        append_jsonl(
            {
                "timestamp": now,
                "operation": "save",
                "status": "success",
                "memory_id": memory_id,
            },
            output_dir / "memory_log.jsonl",
        )
    return result


def parse_bool(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select or save local memory documents.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--select_memory_ids", nargs="*")
    parser.add_argument("--use_global_memory", type=parse_bool)
    parser.add_argument("--query")
    parser.add_argument("--save_type", choices=["conversation", "global"])
    parser.add_argument("--save_input_path")
    parser.add_argument("--outdir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config_path = resolve_cli_path(args.config)
        outdir = resolve_cli_path(args.outdir)
        if args.save_type or args.save_input_path:
            if not args.save_type or not args.save_input_path:
                raise ValueError("--save_type and --save_input_path must be provided together")
            input_path = resolve_cli_path(args.save_input_path)
            payload = read_json(input_path)
            if payload.get("save_type") != args.save_type:
                raise ValueError("CLI save_type must match memory_save_input.json")
            base = input_path.parent
            save_memory(
                str(config_path),
                payload["conversation_id"],
                args.save_type,
                str((base / payload["messages_path"]).resolve()),
                str((base / payload["trace_path"]).resolve()),
                str((base / payload["answer_path"]).resolve()),
                str(outdir),
            )
            print(outdir / "saved_memory.json")
        else:
            if args.select_memory_ids is None and args.use_global_memory is None:
                raise ValueError("select mode requires --select_memory_ids or --use_global_memory")
            result = load_memory(
                str(config_path),
                args.select_memory_ids or [],
                bool(args.use_global_memory),
                args.query,
                str(outdir),
            )
            print(outdir / "selected_memory.json")
        return 0
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
