from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from common.io_utils import append_jsonl, read_json, read_text, read_yaml, write_json, write_text
from common.conversation_store import (
    append_message,
    delete_conversation,
    init_store,
    list_conversations,
    list_unblocked_conversation_turns,
    list_messages,
    list_task_memories,
    list_tool_steps,
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
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _contains_any(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _looks_like_exact_payload(value: str) -> bool:
    return bool(
        re.search(
            r"([A-Za-z]:\\|[/\\][\w .-]+[/\\]|```|Traceback|Exception|Error:|"
            r"\bpython\s+|\bnpm\s+|\bgit\s+|&&|\|\||#include\s*<|def\s+\w+\(|function\s+\w+\()",
            value,
            re.I,
        )
    )


def _safe_summary_items(value: Any) -> list:
    items = []
    if not isinstance(value, list):
        return items
    for item in value:
        if not isinstance(item, str):
            continue
        compact = _compact_text(item, 180)
        if compact and not _looks_like_exact_payload(compact):
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


def _heuristic_memory_decision(
    raw_user_input: str,
    final_answer: str,
    trace: dict,
    source_message_ids: list[str],
    source_tool_step_ids: list[str],
    tool_steps: list[dict],
) -> dict:
    text = f"{raw_user_input}\n{final_answer}"
    tool_count = len(tool_steps)
    has_decision = _contains_any(text, ["决定", "确定", "采用", "不要", "禁止", "必须", "改成", "保留"])
    has_correction = _contains_any(text, ["不对", "错了", "纠正", "不是", "应该", "重新"])
    has_fact = bool(re.search(r"[A-Za-z]:\\|/|\.py|\.md|\.txt|\.json|\.yaml|\.docx|报错|error|trace|commit", text, re.I))
    task_like = _contains_any(
        text,
        ["项目", "模块", "实现", "修复", "计划", "任务", "开发", "代码", "前端", "后端", "数据库", "memory", "agent", "b5"],
    )
    noise = 0.8 if _compact_text(raw_user_input) in {"你好", "您好", "hi", "hello", "ok", "好的", "谢谢"} else 0.1
    tags = {
        "current_task_relevance": 0.8 if task_like else 0.2,
        "long_term_value": 0.8 if has_decision or has_correction else (0.6 if has_fact or tool_count else 0.2),
        "has_explicit_fact": has_fact,
        "has_decision": has_decision,
        "has_user_correction": has_correction,
        "allow_compress": True,
        "allow_drop": noise > 0.7 and not has_fact and not has_decision and not has_correction,
        "noise_score": noise,
        "labels": [
            label
            for label, enabled in {
                "task_like": task_like,
                "tool_used": tool_count > 0,
                "decision": has_decision,
                "user_correction": has_correction,
                "explicit_fact": has_fact,
            }.items()
            if enabled
        ],
    }
    summary = {
        "summary": (
            "This turn records the user request and the agent response. "
            "Use the linked source messages and tool steps for exact paths, parameters, commands, code, errors, and outputs."
        ),
        "keywords": [label for label in tags["labels"]],
        "facts": [],
        "decisions": [],
        "corrections": [],
        "tool_refs": _tool_refs_from_steps(tool_steps),
        "artifact_refs": _artifact_refs_from_steps(tool_steps),
        "source_message_ids": source_message_ids,
        "source_tool_step_ids": source_tool_step_ids,
    }
    task_action = "update_foreground" if task_like and (has_decision or tool_count or "任务" in text) else "no_change"
    task_memory = {
        "action": task_action,
        "status": "foreground",
        "title": _compact_text(raw_user_input, 40) or "当前任务",
        "objective": _compact_text(raw_user_input, 160),
        "phase": "in_progress",
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
        "source": "heuristic",
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
    if isinstance(summary_text, str) and _looks_like_exact_payload(summary_text):
        summary["summary"] = (
            "This turn may contain exact operational details. "
            "Use the linked source messages and tool steps for exact paths, commands, code, errors, and outputs."
        )
    summary["keywords"] = _safe_summary_items(summary.get("keywords"))
    summary["facts"] = _safe_summary_items(summary.get("facts"))
    summary["decisions"] = _safe_summary_items(summary.get("decisions"))
    summary["corrections"] = _safe_summary_items(summary.get("corrections"))
    summary["tool_refs"] = _tool_refs_from_steps(tool_steps)
    summary["artifact_refs"] = _artifact_refs_from_steps(tool_steps)
    summary["source_message_ids"] = source_message_ids
    summary["source_tool_step_ids"] = source_tool_step_ids
    if not isinstance(summary.get("summary"), str) or not summary["summary"].strip():
        raise ValueError("turn_summary.summary must be non-empty")
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
    turns = list_unblocked_conversation_turns(_conversation_db_path(config_path), conversation_id, min_turns)
    if len(turns) < min_turns:
        return {"status": "skipped", "reason": "not enough turns"}
    block_turns = turns[:min_turns]
    start = block_turns[0]["turn_index"]
    end = block_turns[-1]["turn_index"]
    block = {
        "title": f"Turns {start}-{end}",
        "summary": (
            f"Block covering turns {start}-{end}. Use linked turn summaries first, "
            "then load original messages/tool steps for exact facts."
        ),
        "status": "active",
        "keywords": [],
        "source": "heuristic",
    }
    return upsert_memory_block(
        _conversation_db_path(config_path),
        conversation_id,
        block,
        [turn["id"] for turn in block_turns],
    )


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
        decision = _heuristic_memory_decision(
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
        source=decision.get("source", "heuristic"),
    )
    summary_result = upsert_turn_summary(
        _conversation_db_path(config_path),
        turn_id,
        decision["turn_summary"],
        source=decision.get("source", "heuristic"),
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
        "decision_source": decision.get("source", "heuristic"),
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
