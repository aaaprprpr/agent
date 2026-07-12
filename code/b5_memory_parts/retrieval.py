from __future__ import annotations

from pathlib import Path

from common.conversation_store import (
    list_conversation_turns,
    list_messages_by_ids,
    list_memory_blocks,
    list_tool_steps_by_ids,
    list_turn_summaries,
    record_memory_retrieval,
)
from common.io_utils import append_jsonl, write_json
from common.logging_utils import now_iso
from common.schemas import normalize_history_messages

from b5_memory_parts.conversation_api import list_conversation_tasks
from b5_memory_parts.paths import _conversation_db_path, _memory_paths, _safe_conversation_id
from b5_memory_parts.text_utils import (
    MAX_RECALLED_BLOCKS,
    MAX_RECALLED_TURNS,
    RECENT_CONTEXT_TURNS,
    _build_memory_context_text,
    _foreground_task,
    _history_query_text,
    _paused_tasks,
    _safe_list,
    _score_block_detail,
    _score_turn_detail,
    _source_message_context,
    _source_tool_context,
    _task_query_text,
    _turn_context_role,
    _unique_strings,
)


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
        score_detail = _score_block_detail(block, query_text, newest_turn_index)
        if score_detail["score"] > 0.05:
            item = dict(block)
            item["score"] = score_detail["score"]
            item["score_breakdown"] = score_detail
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
        score_detail = _score_turn_detail(turn, query_text, newest_turn_index)
        high_value = (
            bool(turn.get("has_decision"))
            or bool(turn.get("has_user_correction"))
            or float(turn.get("long_term_value") or 0.0) >= 0.7
        )
        if score_detail["score"] <= 0.1 and not high_value:
            continue
        if turn.get("allow_drop") and score_detail["score"] < 0.35 and not high_value:
            continue
        item = dict(turn)
        item["score"] = score_detail["score"]
        item["score_breakdown"] = score_detail
        item["context_role"] = _turn_context_role(item)
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
            "retrieval_features": [
                "current_user_input",
                "recent_history",
                "task_memory",
                "field_overlap",
                "tool_overlap",
                "long_term_value",
                "current_task_relevance",
                "time_recency",
            ],
            "vector_retrieval": "not_configured",
            "llm_rerank": "not_configured",
        },
        candidate_blocks=[
            {
                "block_id": block.get("id"),
                "score": block.get("score"),
                "score_breakdown": block.get("score_breakdown"),
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
                "score_breakdown": turn.get("score_breakdown"),
                "context_role": turn.get("context_role"),
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
            "vector_retrieval": "not_configured",
            "llm_rerank": "not_configured",
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
            "vector_retrieval": "not_configured",
            "llm_rerank": "not_configured",
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
