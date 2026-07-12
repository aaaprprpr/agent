from __future__ import annotations

import json
from typing import Any

from common.conversation_store import (
    list_turn_summaries,
    list_unblocked_conversation_turns,
    upsert_conversation_turn,
    upsert_memory_block,
    upsert_task_memory,
    upsert_turn_memory_tags,
    upsert_turn_summary,
)

from b5_memory_parts.conversation_api import list_conversation_tasks, list_message_tool_steps
from b5_memory_parts.paths import _conversation_db_path, _safe_conversation_id
from b5_memory_parts.text_utils import (
    _compact_jsonish,
    _compact_text,
    _safe_list,
    _unique_strings,
)


def _neutral_locator_summary() -> str:
    return (
        "Memory reflection was unavailable for this turn. "
        "Use the linked source messages and tool steps for all facts, paths, commands, code, errors, and outputs."
    )


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
