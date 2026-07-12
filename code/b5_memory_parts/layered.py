from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from common.conversation_store import (
    list_conversation_turns,
    list_messages_by_ids,
    list_memory_blocks,
    list_tool_steps_by_ids,
    list_turn_summaries,
    list_unblocked_conversation_turns,
    record_memory_retrieval,
    upsert_conversation_turn,
    upsert_memory_block,
    upsert_task_memory,
    upsert_turn_memory_tags,
    upsert_turn_summary,
)
from common.io_utils import append_jsonl, read_json, read_text, write_json, write_text
from common.logging_utils import now_iso
from common.schemas import normalize_history_messages

from b5_memory_parts.conversation_api import list_conversation_messages, list_conversation_tasks
from b5_memory_parts.paths import _conversation_db_path, _memory_paths, _safe_conversation_id

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

def _neutral_locator_summary() -> str:
    return (
        "Memory reflection was unavailable for this turn. "
        "Use the linked source messages and tool steps for all facts, paths, commands, code, errors, and outputs."
    )

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

def _workspace_snapshot(trace: dict) -> dict:
    workspace = trace.get("workspace") if isinstance(trace, dict) and isinstance(trace.get("workspace"), dict) else {}
    if not workspace:
        return {}
    tools = workspace.get("tools") if isinstance(workspace.get("tools"), dict) else {}
    draft = workspace.get("draft") if isinstance(workspace.get("draft"), dict) else {}
    stages = []
    for entry in _safe_list(workspace.get("trace"))[-8:]:
        if not isinstance(entry, dict):
            continue
        stages.append(
            {
                "phase": entry.get("phase"),
                "payload": _compact_jsonish(entry.get("payload")),
            }
        )
    return {
        "task": _compact_jsonish(workspace.get("task") if isinstance(workspace.get("task"), dict) else {}),
        "known_facts": _compact_jsonish(draft.get("known_facts", [])),
        "missing_info": _compact_jsonish(draft.get("missing_info", [])),
        "accepted_evidence": _compact_jsonish(tools.get("accepted_evidence", [])),
        "rejected_evidence": _compact_jsonish(tools.get("rejected_evidence", [])),
        "observations": _compact_jsonish(tools.get("observations", [])),
        "final": _compact_jsonish(workspace.get("final") if isinstance(workspace.get("final"), dict) else {}),
        "stages": stages,
    }

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
        "workspace": _workspace_snapshot(trace),
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
        "Return exactly one JSON object matching the requested memory schema. "
        "Do not wrap it in an AIMessage. Do not output content, tool_calls, control, or agent_step. "
        "Summaries are only locators: do not copy exact file paths, commands, code, parameters, traceback text, or tool output values. "
        "When exact facts are needed later, the system will load source messages and tool steps."
    )
    user = (
        "Return a JSON object with exactly these top-level keys: turn_tags, turn_summary, task_memory.\n\n"
        "Memory schema:\n"
        + json.dumps(schema_hint, ensure_ascii=False, indent=2)
        + "\n\nCompleted turn observation:\n"
        + json.dumps(observation, ensure_ascii=False, indent=2)
        + "\n\nReturn the memory JSON object now."
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
    from b4_local_agent_llm import generate_json_object

    result = generate_json_object(
        model_config,
        _memory_reflection_messages(raw_user_input, final_answer, trace, tool_steps, existing_tasks),
        mode,
        artifact_dir,
        "memory_reflection",
        prompt_ready=True,
    )
    if result.get("status") != "success" or not isinstance(result.get("json"), dict):
        raise ValueError(f"memory reflection failed: {result.get('error')}")
    return _coerce_memory_decision(result["json"], source_message_ids, source_tool_step_ids, tool_steps)

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
    source_message_context = _source_message_context(source_messages)
    source_tool_context = _source_tool_context(source_tool_steps)

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
        "memory_policy": {
            "current_input_priority": True,
            "summaries_are_locators": True,
            "exact_facts_require_source": True,
            "recent_history_is_raw": True,
            "older_history_is_recalled_only_when_selected": True,
        },
        "foreground_task": _foreground_task(tasks),
        "paused_tasks": _paused_tasks(tasks)[:6],
        "context_chars": len(context_text),
        "max_context_chars": max_chars,
        "truncated": truncated,
        "tasks": tasks,
        "recalled_blocks": selected_blocks,
        "recalled_turns": selected_turns,
        "source_messages": source_message_context,
        "source_tool_steps": source_tool_context,
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

def _workspace_memory_from_layered_context(layered_context: dict) -> dict:
    if not isinstance(layered_context, dict):
        return {"status": "not_requested"}
    return {
        "status": layered_context.get("status"),
        "memory_policy": layered_context.get("memory_policy", {}),
        "foreground_task": layered_context.get("foreground_task"),
        "paused_tasks": layered_context.get("paused_tasks", []),
        "recalled_blocks": layered_context.get("recalled_blocks", []),
        "recalled_turns": layered_context.get("recalled_turns", []),
        "source_messages": layered_context.get("source_messages", []),
        "source_tool_steps": layered_context.get("source_tool_steps", []),
        "recent_context_turns": layered_context.get("recent_context_turns"),
        "history_message_count": layered_context.get("history_message_count"),
        "recent_history_message_count": layered_context.get("recent_history_message_count"),
        "context_chars": layered_context.get("context_chars"),
        "max_context_chars": layered_context.get("max_context_chars"),
        "truncated": layered_context.get("truncated"),
        "loaded_message_ids": layered_context.get("loaded_message_ids", []),
        "loaded_tool_step_ids": layered_context.get("loaded_tool_step_ids", []),
        "retrieval_log": layered_context.get("retrieval_log"),
        "error": layered_context.get("error"),
    }

def _error_layered_memory_context(conversation_id: str, normalized_history: list[dict], exc: Exception) -> dict:
    recent_history = normalized_history[-RECENT_CONTEXT_TURNS * 2 :]
    return {
        "status": "error",
        "conversation_id": conversation_id,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        "recent_context_turns": RECENT_CONTEXT_TURNS,
        "history_message_count": len(normalized_history),
        "recent_history_message_count": len(recent_history),
        "recent_history_messages": recent_history,
        "memory_messages": [],
        "memory_policy": {
            "current_input_priority": True,
            "summaries_are_locators": True,
            "exact_facts_require_source": True,
            "recent_history_is_raw": True,
            "older_history_is_recalled_only_when_selected": True,
        },
        "foreground_task": None,
        "paused_tasks": [],
        "context_chars": 0,
        "max_context_chars": 0,
        "truncated": False,
        "tasks": [],
        "recalled_blocks": [],
        "recalled_turns": [],
        "source_messages": [],
        "source_tool_steps": [],
        "candidate_blocks": [],
        "selected_turns": [],
        "loaded_message_ids": [],
        "loaded_tool_step_ids": [],
        "retrieval_log": None,
    }

def prepare_workspace_memory_context(
    config_path: str,
    conversation_id: str,
    current_user_input: str,
    history_messages: list[dict],
    selected_memory: dict | None = None,
    outdir: str | None = None,
) -> dict:
    """Prepare the explicit B5 context package consumed by B1 workspace mode.

    B1 should keep the original runtime history intact. This package separately
    provides recent raw history and structured memory for the workspace.
    """
    conversation_id = _safe_conversation_id(conversation_id)
    normalized_history = normalize_history_messages(history_messages)
    try:
        layered_context = build_layered_memory_context(
            config_path,
            conversation_id,
            current_user_input,
            normalized_history,
            selected_memory,
            outdir,
        )
    except Exception as exc:
        layered_context = _error_layered_memory_context(conversation_id, normalized_history, exc)

    recent_history = layered_context.get("recent_history_messages")
    if not isinstance(recent_history, list):
        recent_history = normalized_history[-RECENT_CONTEXT_TURNS * 2 :]
    recent_history = normalize_history_messages(recent_history)
    workspace_memory = _workspace_memory_from_layered_context(layered_context)
    result = {
        "status": workspace_memory.get("status"),
        "conversation_id": conversation_id,
        "history_message_count": len(normalized_history),
        "recent_history_message_count": len(recent_history),
        "recent_history_messages": recent_history,
        "workspace_memory": workspace_memory,
        "layered_memory_context": layered_context,
    }
    if outdir:
        try:
            output_dir = Path(outdir)
            write_json(result, output_dir / "workspace_memory_context.json")
            append_jsonl(
                {
                    "timestamp": now_iso(),
                    "operation": "prepare_workspace_memory_context",
                    "status": result["status"],
                    "conversation_id": conversation_id,
                    "recent_history_message_count": len(recent_history),
                    "context_chars": workspace_memory.get("context_chars"),
                },
                output_dir / "memory_log.jsonl",
            )
        except Exception as exc:
            result["artifact_write_error"] = {"type": type(exc).__name__, "message": str(exc)}
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
