from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from common.conversation_store import (
    append_message,
    init_store,
    list_conversations,
    list_messages,
    list_tool_steps,
    record_tool_step,
    search_messages,
    upsert_conversation,
)
from common.io_utils import append_jsonl, read_json, read_text, read_yaml, write_json, write_text
from common.logging_utils import now_iso
from common.path_utils import resolve_cli_path, resolve_from_file


LOW_VALUE_TERMS = {
    "我",
    "你",
    "他",
    "她",
    "它",
    "的",
    "了",
    "和",
    "与",
    "或",
    "在",
    "是",
    "帮",
    "请",
    "如何",
    "怎么",
    "一个",
    "一下",
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "for",
    "with",
}


ROLE_LABELS = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
}


def _memory_paths(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path).resolve()
    config = read_yaml(path)
    if not isinstance(config, dict) or not isinstance(config.get("memory"), dict):
        raise ValueError("memory.yaml must define a memory object")
    memory = config["memory"]
    required = ["root_dir", "global_memory_dir", "conversation_memory_dir", "index_path", "max_memory_chars"]
    missing = [name for name in required if name not in memory]
    if missing:
        raise ValueError(f"memory.yaml missing: {', '.join(missing)}")
    max_chars = memory["max_memory_chars"]
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_memory_chars must be a positive integer")
    retrieval = memory.get("retrieval", {})
    if not isinstance(retrieval, dict):
        retrieval = {}
    root = resolve_from_file(memory["root_dir"], path)
    return {
        "root": root,
        "global": root / memory["global_memory_dir"],
        "conversations": root / memory["conversation_memory_dir"],
        "index": root / memory["index_path"],
        "conversation_db": root / memory.get("conversation_db_path", "conversation_store.sqlite3"),
        "max_chars": max_chars,
        "retrieval": retrieval,
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


def _safe_conversation_id(conversation_id: str) -> str:
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", conversation_id):
        raise ValueError("conversation_id may only contain letters, numbers, dot, underscore, and hyphen")
    return conversation_id


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _retrieval_config(paths: dict[str, Any]) -> dict:
    config = paths.get("retrieval", {})
    return config if isinstance(config, dict) else {}


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    lowered = query.lower()
    raw = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered)
    terms: list[str] = []
    for item in raw:
        if item in LOW_VALUE_TERMS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            if len(item) >= 2:
                terms.append(item)
                terms.extend(item[index : index + 2] for index in range(len(item) - 1))
                if len(item) >= 3:
                    terms.extend(item[index : index + 3] for index in range(len(item) - 2))
            elif item not in LOW_VALUE_TERMS:
                terms.append(item)
        elif len(item) >= 2 and item not in LOW_VALUE_TERMS:
            terms.append(item)
    filtered = [term for term in terms if term and term not in LOW_VALUE_TERMS]
    counts = Counter(filtered)
    ordered = sorted(counts, key=lambda term: (-counts[term], -len(term), term))
    return ordered[:24]


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def _score_text(text: str, terms: list[str]) -> float:
    if not terms or not text:
        return 0.0
    lowered = text.lower()
    score = 0.0
    for term in terms:
        count = lowered.count(term.lower())
        if count:
            score += count * max(1.0, min(len(term), 6) / 2)
    return score


def _score_memory(metadata: dict, content: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    title = str(metadata.get("title", ""))
    summary = str(metadata.get("summary", ""))
    return round(_score_text(title, terms) * 4 + _score_text(summary, terms) * 3 + _score_text(content, terms), 4)


def _best_excerpt(content: str, terms: list[str], limit: int) -> str:
    if limit <= 0 or not content:
        return ""
    if len(content) <= limit:
        return content
    lowered = content.lower()
    first_hit: int | None = None
    for term in terms:
        hit = lowered.find(term.lower())
        if hit >= 0 and (first_hit is None or hit < first_hit):
            first_hit = hit
    window = max(1, limit - 6)
    center = first_hit if first_hit is not None else 0
    start = max(0, center - window // 3)
    end = min(len(content), start + window)
    start = max(0, end - window)
    excerpt = content[start:end]
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(content):
        excerpt = excerpt + "..."
    return excerpt[:limit]


def _compact_summary(text: str, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", _strip_memory_blocks(text)).strip()
    return compact[:limit]


def _markdown_section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    marker = f"## {heading}".strip().lower()
    collecting = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if collecting:
                break
            if stripped.lower() == marker:
                collecting = True
                continue
        elif collecting:
            collected.append(line)
    return "\n".join(collected).strip()


def _extract_final_answer(markdown: str) -> str:
    return _markdown_section(markdown, "Final Answer")


def _strip_memory_blocks(text: str) -> str:
    return re.sub(r"<memory\b[^>]*>.*?</memory>", "", text, flags=re.IGNORECASE | re.DOTALL)


def _text_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", " ", left or "").strip()
    right_norm = re.sub(r"\s+", " ", right or "").strip()
    if not left_norm and not right_norm:
        return 1.0
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _sanitize_messages_for_memory(messages: list[dict]) -> list[dict]:
    sanitized = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            content = _strip_memory_blocks(content).strip()
            if len(content) > 4000:
                content = content[:4000] + "...[truncated]"
        item = {
            "role": message.get("role"),
            "content": content,
        }
        for optional_key in ("name", "tool_call_id", "status"):
            if optional_key in message:
                item[optional_key] = message.get(optional_key)
        sanitized.append(item)
    return sanitized


def _classify_memory_update(old_answer: str, new_answer: str) -> str:
    old_norm = re.sub(r"\s+", " ", old_answer).strip()
    new_norm = re.sub(r"\s+", " ", new_answer).strip()
    if not old_norm:
        return "new_memory"
    if old_norm == new_norm:
        return "duplicate_no_change"
    if old_norm in new_norm:
        return "supplement"
    if new_norm in old_norm:
        return "shorter_rewrite"
    similarity = _text_similarity(old_norm, new_norm)
    if similarity >= 0.85:
        return "minor_rewrite"
    if similarity >= 0.45:
        return "related_update"
    return "rewrite_or_conflict"


def _legacy_metadata_view(metadata: dict, memory_id: str) -> dict:
    return {
        "memory_id": memory_id,
        "memory_type": metadata.get("memory_type"),
        "title": metadata.get("title", memory_id),
        "summary": metadata.get("summary", ""),
        "conversation_id": metadata.get("conversation_id"),
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
    }


def _legacy_candidate(
    memory_id: str,
    source: str,
    paths: dict[str, Any],
    index: dict,
    terms: list[str],
    *,
    explicit: bool = False,
) -> tuple[dict | None, dict | None]:
    metadata = index.get(memory_id)
    if not isinstance(metadata, dict):
        return None, {"memory_id": memory_id, "type": "MemoryNotFound", "message": "memory_id does not exist"}
    relative_path = metadata.get("path")
    if not isinstance(relative_path, str):
        return None, {"memory_id": memory_id, "type": "InvalidMetadata", "message": "memory path is missing"}
    root = Path(paths["root"]).resolve()
    document_path = (Path(paths["root"]) / relative_path).resolve()
    try:
        document_path.relative_to(root)
    except ValueError:
        return None, {"memory_id": memory_id, "type": "InvalidPath", "message": "memory path escapes root"}
    if not document_path.is_file():
        return None, {
            "memory_id": memory_id,
            "type": "FileNotFoundError",
            "message": f"memory file not found: {relative_path}",
        }
    content = read_text(document_path)
    metadata_view = _legacy_metadata_view(metadata, memory_id)
    rendered = "\n".join(
        part
        for part in [
            f"Legacy memory: {metadata_view['title']}",
            f"Summary: {metadata_view.get('summary', '')}" if metadata_view.get("summary") else "",
            content,
        ]
        if part
    )
    score = _score_memory(metadata_view, content, terms)
    return (
        {
            "memory_id": memory_id,
            "memory_type": metadata.get("memory_type", "legacy"),
            "title": metadata_view["title"],
            "summary": metadata_view.get("summary", ""),
            "path": relative_path,
            "raw_content": content,
            "rendered_content": rendered,
            "memory_source": source,
            "selection_reason": "explicit_legacy_memory_id" if explicit else "legacy_global_keyword_top_k",
            "retrieval_score": score,
            "matched_terms": _matched_terms(rendered, terms),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "explicit": explicit,
        },
        None,
    )


def _db_recent_candidate(
    config_path: str,
    conversation_id: str | None,
    terms: list[str],
    recent_limit: int,
) -> list[dict]:
    if not conversation_id:
        return []
    db_path = _conversation_db_path(config_path)
    if not db_path.is_file():
        return []
    messages = [
        message
        for message in list_messages(db_path, conversation_id)
        if message.get("role") in {"system", "user", "assistant"} and str(message.get("content", "")).strip()
    ]
    if not messages:
        return []
    recent = messages[-recent_limit:]
    lines = [f"SQLite recent history for conversation `{conversation_id}`:"]
    for message in recent:
        role = ROLE_LABELS.get(str(message.get("role")), str(message.get("role")))
        content = str(message.get("content", "")).strip()
        lines.append(f"{role}: {content}")
    rendered = "\n".join(lines)
    matched = _matched_terms(rendered, terms)
    score = max(20.0, _score_text(rendered, terms) + 10.0)
    return [
        {
            "memory_id": f"db_recent_{conversation_id}",
            "memory_type": "conversation_db_recent",
            "title": f"Recent history: {conversation_id}",
            "summary": f"{len(recent)} recent message(s) from current SQLite conversation",
            "path": str(db_path),
            "raw_content": rendered,
            "rendered_content": rendered,
            "memory_source": "db_recent",
            "selection_reason": "same_conversation_recent_history",
            "retrieval_score": round(score, 4),
            "matched_terms": matched,
            "created_at": recent[0].get("created_at"),
            "updated_at": recent[-1].get("created_at"),
            "explicit": False,
            "message_count": len(recent),
        }
    ]


def _db_search_candidates(
    config_path: str,
    query: str | None,
    conversation_id: str | None,
    terms: list[str],
    top_k: int,
) -> list[dict]:
    if not query or not terms:
        return []
    db_path = _conversation_db_path(config_path)
    if not db_path.is_file():
        return []
    rows = search_messages(
        db_path,
        query,
        limit=top_k,
        exclude_conversation_id=conversation_id,
        include_trivial=False,
        roles=("user", "assistant"),
    )
    candidates = []
    for row in rows:
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        role = ROLE_LABELS.get(str(row.get("role")), str(row.get("role")))
        source = str(row.get("search_backend") or "keyword")
        rendered = "\n".join(
            [
                f"SQLite cross-conversation memory from `{row.get('conversation_id')}`:",
                f"title: {row.get('conversation_title') or row.get('conversation_id')}",
                f"created_at: {row.get('created_at')}",
                f"{role}: {content}",
            ]
        )
        candidates.append(
            {
                "memory_id": f"db_search_{row.get('id')}",
                "memory_type": "conversation_db_search",
                "title": str(row.get("conversation_title") or row.get("conversation_id")),
                "summary": f"{role} message from SQLite conversation history",
                "path": str(db_path),
                "raw_content": content,
                "rendered_content": rendered,
                "memory_source": "db_search",
                "selection_reason": f"cross_conversation_{source}_keyword_match",
                "retrieval_score": float(row.get("search_score") or _score_text(rendered, terms)),
                "matched_terms": _matched_terms(rendered, terms),
                "created_at": row.get("created_at"),
                "updated_at": row.get("conversation_updated_at"),
                "explicit": False,
                "conversation_id": row.get("conversation_id"),
                "message_id": row.get("id"),
                "role": row.get("role"),
                "search_backend": source,
            }
        )
    return candidates


def _candidate_view(candidate: dict, rank: int | None = None) -> dict:
    view = {
        "memory_id": candidate.get("memory_id"),
        "memory_type": candidate.get("memory_type"),
        "title": candidate.get("title"),
        "memory_source": candidate.get("memory_source"),
        "retrieval_score": candidate.get("retrieval_score", 0),
        "selection_reason": candidate.get("selection_reason"),
        "matched_terms": candidate.get("matched_terms", []),
        "selected": candidate.get("selected", False),
        "dropped_reason": candidate.get("dropped_reason"),
        "truncated": candidate.get("truncated", False),
    }
    if rank is not None:
        view["rank"] = rank
    for optional_key in ("path", "conversation_id", "message_id", "search_backend"):
        if candidate.get(optional_key) is not None:
            view[optional_key] = candidate.get(optional_key)
    return view


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        memory_id = str(candidate.get("memory_id"))
        if memory_id in seen:
            continue
        seen.add(memory_id)
        unique.append(candidate)
    return unique


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


def list_conversation_messages(config_path: str, conversation_id: str) -> list[dict]:
    _safe_conversation_id(conversation_id)
    return list_messages(_conversation_db_path(config_path), conversation_id)


def list_message_tool_steps(config_path: str, assistant_message_id: str) -> list[dict]:
    return list_tool_steps(_conversation_db_path(config_path), assistant_message_id)


def search_conversation_messages(
    config_path: str,
    query: str,
    *,
    limit: int = 8,
    conversation_id: str | None = None,
    exclude_conversation_id: str | None = None,
    include_trivial: bool = False,
) -> list[dict]:
    return search_messages(
        _conversation_db_path(config_path),
        query,
        limit=limit,
        conversation_id=conversation_id,
        exclude_conversation_id=exclude_conversation_id,
        include_trivial=include_trivial,
    )


def load_memory(
    config_path: str,
    selected_memory_ids: list[str],
    use_global_memory: bool,
    query: str | None = None,
    outdir: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    if not isinstance(selected_memory_ids, list) or not all(isinstance(item, str) for item in selected_memory_ids):
        raise ValueError("selected_memory_ids must be a list of strings")
    if conversation_id is not None:
        _safe_conversation_id(conversation_id)

    paths = _memory_paths(config_path)
    retrieval = _retrieval_config(paths)
    top_k = _positive_int(retrieval.get("top_k"), 5)
    per_doc_chars = _positive_int(retrieval.get("per_doc_chars"), int(paths["max_chars"]))
    db_recent_messages = _positive_int(retrieval.get("db_recent_messages"), 8)
    terms = _query_terms(query)
    index = _read_index(paths["index"])

    errors: list[dict] = []
    explicit_candidates: list[dict] = []
    for memory_id in selected_memory_ids:
        candidate, error = _legacy_candidate(memory_id, "legacy_explicit", paths, index, terms, explicit=True)
        if error:
            errors.append(error)
        elif candidate:
            explicit_candidates.append(candidate)

    db_recent = _db_recent_candidate(config_path, conversation_id, terms, db_recent_messages)
    db_search = _db_search_candidates(config_path, query, conversation_id, terms, top_k)

    global_candidates: list[dict] = []
    if use_global_memory:
        selected_set = set(selected_memory_ids)
        for memory_id, metadata in sorted(index.items()):
            if memory_id in selected_set or not isinstance(metadata, dict):
                continue
            if metadata.get("memory_type") != "global":
                continue
            candidate, error = _legacy_candidate(memory_id, "legacy_global", paths, index, terms)
            if error:
                errors.append(error)
            elif candidate and (not terms or candidate["retrieval_score"] > 0):
                global_candidates.append(candidate)

    global_candidates.sort(
        key=lambda item: (
            float(item.get("retrieval_score", 0)),
            str(item.get("updated_at") or item.get("created_at") or ""),
            str(item.get("memory_id")),
        ),
        reverse=True,
    )
    global_candidates = global_candidates[:top_k]

    ranked_other = db_search + global_candidates
    ranked_other.sort(
        key=lambda item: (
            float(item.get("retrieval_score", 0)),
            str(item.get("updated_at") or item.get("created_at") or ""),
            str(item.get("memory_id")),
        ),
        reverse=True,
    )
    ranked_candidates = _dedupe_candidates(explicit_candidates + db_recent + ranked_other[:top_k])

    selected_docs = []
    dropped_memory = []
    remaining = int(paths["max_chars"])
    any_truncated = False
    selected_by_id: set[str] = set()
    dropped_by_id: dict[str, str] = {}

    for candidate in ranked_candidates:
        memory_id = str(candidate["memory_id"])
        rendered = str(candidate.get("rendered_content") or candidate.get("raw_content") or "")
        if remaining <= 0:
            candidate["dropped_reason"] = "max_memory_chars_exhausted"
            dropped_by_id[memory_id] = "max_memory_chars_exhausted"
            dropped_memory.append(_candidate_view(candidate))
            any_truncated = True
            continue
        limit = min(per_doc_chars, remaining)
        included = _best_excerpt(rendered, terms, limit)
        if not included:
            candidate["dropped_reason"] = "empty_content"
            dropped_by_id[memory_id] = "empty_content"
            dropped_memory.append(_candidate_view(candidate))
            continue
        truncated = len(included) < len(rendered)
        candidate["selected"] = True
        candidate["truncated"] = truncated
        selected_by_id.add(memory_id)
        any_truncated = any_truncated or truncated
        selected_docs.append(
            {
                "memory_id": memory_id,
                "memory_type": candidate.get("memory_type"),
                "title": candidate.get("title", memory_id),
                "summary": candidate.get("summary", ""),
                "path": candidate.get("path"),
                "content": included,
                "memory_source": candidate.get("memory_source"),
                "selection_reason": candidate.get("selection_reason"),
                "retrieval_score": candidate.get("retrieval_score", 0),
                "matched_terms": candidate.get("matched_terms", []),
                "original_chars": len(str(candidate.get("raw_content") or "")),
                "rendered_chars": len(rendered),
                "included_chars": len(included),
                "truncated": truncated,
            }
        )
        remaining -= len(included)

    for candidate in ranked_candidates:
        memory_id = str(candidate.get("memory_id"))
        candidate["selected"] = memory_id in selected_by_id
        candidate["dropped_reason"] = dropped_by_id.get(memory_id)

    if errors and selected_docs:
        status = "partial"
    elif errors:
        status = "error"
    else:
        status = "success"

    result = {
        "status": status,
        "query": query,
        "conversation_id": conversation_id,
        "retrieval": {
            "mode": "sqlite_first_keyword_top_k",
            "terms": terms,
            "top_k": top_k,
            "per_doc_chars": per_doc_chars,
            "db_recent_messages": db_recent_messages,
            "sources": {
                "db_recent": len(db_recent),
                "db_search": len(db_search),
                "legacy_explicit": len(explicit_candidates),
                "legacy_global": len(global_candidates),
            },
        },
        "selected_memory_docs": selected_docs,
        "ranked_candidates": [_candidate_view(candidate, index + 1) for index, candidate in enumerate(ranked_candidates)],
        "dropped_memory": dropped_memory,
        "max_memory_chars": paths["max_chars"],
        "total_chars": sum(item["included_chars"] for item in selected_docs),
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
                "query": query,
                "conversation_id": conversation_id,
                "selected_count": len(selected_docs),
                "selected_ids": [item["memory_id"] for item in selected_docs],
                "source_counts": result["retrieval"]["sources"],
                "truncated": any_truncated,
                "dropped_count": len(dropped_memory),
                "errors": errors,
            },
            output_dir / "memory_log.jsonl",
        )
    return result


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
    answer = _strip_memory_blocks(read_text(answer_path)).strip()
    if not isinstance(messages, list) or not isinstance(trace, dict):
        raise ValueError("messages must be an array and trace must be an object")
    sanitized_messages = _sanitize_messages_for_memory(messages)
    now = now_iso()
    memory_id = f"mem_{save_type}_{conversation_id}"
    target_dir = paths["conversations"] if save_type == "conversation" else paths["global"]
    relative_dir = "conversations" if save_type == "conversation" else "global"
    target_path = Path(target_dir) / f"{conversation_id}.md"
    relative_path = f"{relative_dir}/{conversation_id}.md"
    title = f"{save_type.title()} {conversation_id}"
    summary = _compact_summary(answer, 200)
    old_text = read_text(target_path) if target_path.is_file() else ""
    old_answer = _extract_final_answer(old_text)
    update_kind = _classify_memory_update(old_answer, answer)
    markdown = (
        f"# {title}\n\n"
        f"- memory_id: `{memory_id}`\n"
        f"- conversation_id: `{conversation_id}`\n"
        f"- created_or_updated_at: `{now}`\n\n"
        "## Final Answer\n\n"
        f"{answer}\n\n"
        "## Messages\n\n```json\n"
        f"{json.dumps(sanitized_messages, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Trace\n\n```json\n"
        f"{json.dumps(trace, ensure_ascii=False, indent=2)}\n```\n"
    )
    write_text(markdown, target_path)
    index = _read_index(paths["index"])
    existing = index.get(memory_id, {})
    created_at = existing.get("created_at", now) if isinstance(existing, dict) else now
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
        "update_analysis": {
            "existed_before": bool(old_text),
            "classification": update_kind,
            "old_chars": len(old_text),
            "new_chars": len(markdown),
            "old_summary": _compact_summary(old_answer, 120),
            "new_summary": _compact_summary(answer, 120),
            "similarity": round(_text_similarity(old_answer, answer), 4) if old_answer else 0.0,
        },
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
                "update_classification": update_kind,
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
            if args.select_memory_ids is None and args.use_global_memory is None and not args.query:
                raise ValueError("select mode requires --select_memory_ids, --use_global_memory, or --query")
            load_memory(
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
