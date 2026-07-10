from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

from common.io_utils import append_jsonl, read_json, read_text, read_yaml, write_json, write_text
from common.logging_utils import now_iso
from common.path_utils import resolve_cli_path, resolve_from_file


CHINESE_STOPWORD_WORDS = {
    "帮我",
    "请问",
    "能否",
    "可以",
    "如何",
    "怎么",
    "怎样",
    "什么",
    "为什么",
    "一下",
}

CHINESE_STOPWORD_CHARS = {
    "我",
    "帮",
    "请",
    "的",
    "了",
    "吗",
    "呢",
    "啊",
    "和",
    "与",
    "及",
    "或",
    "在",
    "是",
    "为",
    "对",
    "把",
    "给",
}

ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "for",
    "how",
    "id",
    "is",
    "mem",
    "memory",
    "of",
    "or",
    "the",
    "to",
    "what",
}

DEFAULT_FIELD_WEIGHTS = {
    "title": 5,
    "summary": 3,
    "final_answer": 4,
    "user_messages": 4,
    "content": 1,
}

MEMORY_BLOCK_PATTERN = re.compile(r"\n*<memory\b[^>]*>.*?</memory>\n*", flags=re.S)


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
    retrieval = memory.get("retrieval", {})
    if not isinstance(retrieval, dict):
        retrieval = {}
    return {
        "root": root,
        "global": root / memory["global_memory_dir"],
        "conversations": root / memory["conversation_memory_dir"],
        "index": root / memory["index_path"],
        "max_chars": max_chars,
        "retrieval": retrieval,
    }


def _read_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {}
    index = read_json(index_path)
    if not isinstance(index, dict):
        raise ValueError("memory_index.json must be an object")
    return index


def _unique_in_order(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _split_chinese_by_stopwords(text: str) -> list[str]:
    pieces = [text]
    for stopword in sorted(CHINESE_STOPWORD_WORDS, key=len, reverse=True):
        next_pieces = []
        for piece in pieces:
            next_pieces.extend(part for part in piece.split(stopword) if part)
        pieces = next_pieces
    cleaned = []
    for piece in pieces:
        stripped = "".join(char for char in piece if char not in CHINESE_STOPWORD_CHARS)
        if len(stripped) >= 2:
            cleaned.append(stripped)
    return cleaned


def _strip_memory_blocks(text: str) -> str:
    return MEMORY_BLOCK_PATTERN.sub("\n[memory context omitted]\n", text)


def _strip_memory_metadata(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"-\s*(memory_id|conversation_id|created_or_updated_at):\s*`?.*`?", stripped):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _markdown_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        flags=re.M | re.S,
    )
    match = pattern.search(markdown)
    return match.group("body").strip() if match else ""


def _extract_messages(markdown: str) -> list[dict]:
    body = _markdown_section(markdown, "Messages")
    if not body:
        return []
    try:
        messages = json.loads(_strip_code_fence(body))
    except json.JSONDecodeError:
        return []
    return messages if isinstance(messages, list) else []


def _compact_for_context(text: str, limit: int) -> str:
    text = _strip_memory_blocks(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _message_texts(messages: list[dict], role: str, limit_each: int = 160) -> list[str]:
    texts = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != role:
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            compact = _compact_for_context(content, limit_each)
            if compact and compact != "[memory context omitted]":
                texts.append(compact)
    return texts


def _memory_view(metadata: dict, raw_content: str) -> dict:
    cleaned_content = _strip_memory_metadata(raw_content)
    final_answer = _markdown_section(raw_content, "Final Answer")
    messages = _extract_messages(raw_content)
    user_messages = _message_texts(messages, "user")
    assistant_messages = _message_texts(messages, "assistant")
    title = str(metadata.get("title", metadata.get("memory_id", "")))
    summary = str(metadata.get("summary", ""))
    searchable_content = "\n".join(
        item
        for item in [
            _compact_for_context(final_answer, 1000),
            "\n".join(user_messages),
            "\n".join(assistant_messages[-2:]),
            _compact_for_context(cleaned_content, 1200),
        ]
        if item
    )
    rendered_parts = [
        f"# {title}",
        f"- memory_id: `{metadata.get('memory_id', '')}`",
        f"- memory_type: `{metadata.get('memory_type', '')}`",
    ]
    if summary:
        rendered_parts.append(f"- summary: {summary}")
    if user_messages:
        rendered_parts.append("\n## Relevant User Messages\n" + "\n".join(f"- {item}" for item in user_messages[-3:]))
    if final_answer:
        rendered_parts.append("\n## Final Answer\n" + _compact_for_context(final_answer, 1200))
    elif searchable_content:
        rendered_parts.append("\n## Content\n" + _compact_for_context(searchable_content, 1200))
    return {
        "title": title,
        "summary": summary,
        "final_answer": _compact_for_context(final_answer, 2000),
        "user_messages": "\n".join(user_messages),
        "assistant_messages": "\n".join(assistant_messages),
        "searchable_content": searchable_content,
        "rendered_content": "\n\n".join(rendered_parts).strip(),
        "messages_count": len(messages),
    }


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    lowered = query.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered)
    terms: list[str] = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            for phrase in _split_chinese_by_stopwords(word):
                terms.append(phrase)
                terms.extend(phrase[index : index + 2] for index in range(max(0, len(phrase) - 1)))
        elif len(word) >= 2 and word not in ENGLISH_STOPWORDS:
            terms.append(word)
    counts = Counter(terms)
    ranked = [term for term, _ in counts.most_common()]
    return _unique_in_order(ranked)


def _retrieval_config(paths: dict[str, Path | int]) -> dict:
    config = paths.get("retrieval", {})
    return config if isinstance(config, dict) else {}


def _field_weights(retrieval: dict) -> dict[str, int]:
    configured = retrieval.get("field_weights", {})
    weights = dict(DEFAULT_FIELD_WEIGHTS)
    if isinstance(configured, dict):
        for field, value in configured.items():
            if field in weights:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    continue
                if parsed > 0:
                    weights[field] = parsed
    return weights


def _auto_select_config(retrieval: dict) -> dict:
    configured = retrieval.get("auto_select", {})
    if not isinstance(configured, dict):
        configured = {}
    memory_types = configured.get("memory_types", ["global", "conversation"])
    if not isinstance(memory_types, list):
        memory_types = ["global", "conversation"]
    memory_types = [str(item) for item in memory_types if str(item) in {"global", "conversation"}]
    try:
        min_score = int(configured.get("min_score", 2))
    except (TypeError, ValueError):
        min_score = 2
    try:
        max_candidates = int(configured.get("max_candidates", 50))
    except (TypeError, ValueError):
        max_candidates = 50
    return {
        "enabled": bool(configured.get("enabled", False)),
        "memory_types": memory_types,
        "min_score": max(0, min_score),
        "max_candidates": max(1, max_candidates),
    }


def _term_counts(text: str, terms: list[str]) -> dict[str, int]:
    lowered = text.lower()
    counts = {}
    for term in terms:
        count = lowered.count(term)
        if count > 0:
            counts[term] = count
    return counts


def _score_memory(metadata: dict, content: str, terms: list[str], weights: dict[str, int]) -> dict:
    view = _memory_view(metadata, content)
    fields = {
        "title": view["title"],
        "summary": view["summary"],
        "final_answer": view["final_answer"],
        "user_messages": view["user_messages"],
        "content": view["searchable_content"],
    }
    field_matches = {field: _term_counts(text, terms) for field, text in fields.items()}
    field_scores = {
        field: sum(matches.values()) * weights.get(field, 1)
        for field, matches in field_matches.items()
    }
    matched_terms = _unique_in_order(
        [term for term in terms if any(term in matches for matches in field_matches.values())]
    )
    return {
        "total_score": sum(field_scores.values()),
        "field_scores": field_scores,
        "field_matches": field_matches,
        "matched_terms": matched_terms,
        "view": view,
    }


def _metadata_prefilter_score(metadata: dict, terms: list[str]) -> int:
    if not terms:
        return 0
    text = "\n".join(
        str(metadata.get(field, ""))
        for field in ["title", "summary", "conversation_id", "memory_type"]
    )
    return sum(_term_counts(text, terms).values())


def _best_excerpt(content: str, terms: list[str], limit: int) -> str:
    if limit <= 0:
        return ""
    if len(content) <= limit:
        return content
    lowered = content.lower()
    first_hit = None
    for term in terms:
        hit = lowered.find(term)
        if hit >= 0 and (first_hit is None or hit < first_hit):
            first_hit = hit
    center = first_hit if first_hit is not None else 0
    start = max(0, center - limit // 4)
    end = min(len(content), start + limit)
    start = max(0, end - limit)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    available = limit - len(prefix) - len(suffix)
    if available <= 0:
        return content[:limit]
    end = min(len(content), start + available)
    return prefix + content[start:end] + suffix


def _compact_summary(text: str, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def _extract_final_answer(markdown: str) -> str:
    return _markdown_section(markdown, "Final Answer")


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


def _text_tokens(text: str) -> set[str]:
    terms = set(_query_terms(text))
    terms.update(token for token in re.findall(r"[a-z0-9_]+", text.lower()) if len(token) >= 2)
    return terms


def _text_similarity(left: str, right: str) -> float:
    left_terms = _text_tokens(left)
    right_terms = _text_tokens(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _sanitize_messages_for_memory(messages: list[dict]) -> list[dict]:
    sanitized = deepcopy(messages)
    for message in sanitized:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _strip_memory_blocks(content).strip()
    return sanitized


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
    retrieval = _retrieval_config(paths)
    top_k = int(retrieval.get("top_k", 5))
    per_doc_chars = int(retrieval.get("per_doc_chars", paths["max_chars"]))
    top_k = max(1, top_k)
    per_doc_chars = max(1, per_doc_chars)
    weights = _field_weights(retrieval)
    auto_select = _auto_select_config(retrieval)
    terms = _query_terms(query)

    ordered_ids = []
    source_by_id: dict[str, str] = {}

    def add_candidate_id(memory_id: str, source: str) -> None:
        if memory_id not in source_by_id:
            ordered_ids.append(memory_id)
            source_by_id[memory_id] = source

    for memory_id in selected_memory_ids:
        add_candidate_id(memory_id, "explicit_id")
    if use_global_memory:
        for memory_id in sorted(key for key, item in index.items() if item.get("memory_type") == "global"):
            add_candidate_id(memory_id, "global_memory")
    if auto_select["enabled"] and terms:
        auto_pool = []
        for memory_id, item in sorted(index.items()):
            if not isinstance(item, dict) or item.get("memory_type") not in auto_select["memory_types"]:
                continue
            if memory_id in source_by_id:
                continue
            auto_pool.append((_metadata_prefilter_score(item, terms), memory_id))
        auto_pool.sort(key=lambda item: (-item[0], item[1]))
        for _, memory_id in auto_pool[: auto_select["max_candidates"]]:
            add_candidate_id(memory_id, "auto_keyword")

    candidates = []
    errors = []
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
        metadata_for_view = {**metadata, "memory_id": memory_id}
        score = _score_memory(metadata_for_view, original, terms, weights)
        candidates.append(
            {
                "memory_id": memory_id,
                "metadata": metadata_for_view,
                "relative_path": relative_path,
                "original": original,
                "view": score["view"],
                "score": score["total_score"],
                "field_scores": score["field_scores"],
                "field_matches": score["field_matches"],
                "matched_terms": score["matched_terms"],
                "explicit": memory_id in selected_memory_ids,
                "candidate_source": source_by_id.get(memory_id, "unknown"),
            }
        )

    preserved_candidates = [item for item in candidates if item["explicit"]]
    ranked_candidates = [item for item in candidates if not item["explicit"]]
    if terms:
        ranked_candidates = [
            item
            for item in ranked_candidates
            if item["candidate_source"] != "auto_keyword" or item["score"] >= auto_select["min_score"]
        ]
        ranked_candidates.sort(key=lambda item: (-item["score"], item["memory_id"]))
        ranked_candidates = ranked_candidates[:top_k]
    ranked = preserved_candidates + ranked_candidates
    ranked_ids = set()
    unique_ranked = []
    for item in ranked:
        if item["memory_id"] in ranked_ids:
            continue
        ranked_ids.add(item["memory_id"])
        unique_ranked.append(item)
    ranked = unique_ranked
    initially_selected_ids = {item["memory_id"] for item in ranked}

    docs = []
    included_ids = set()
    length_dropped_ids = []
    remaining = int(paths["max_chars"])
    any_truncated = False
    for index, item in enumerate(ranked):
        if remaining <= 0:
            any_truncated = True
            length_dropped_ids.extend(candidate["memory_id"] for candidate in ranked[index:])
            break
        memory_id = item["memory_id"]
        metadata = item["metadata"]
        original = item["original"]
        rendered = item["view"]["rendered_content"] or original
        relative_path = item["relative_path"]
        limit = min(per_doc_chars, remaining)
        included = _best_excerpt(rendered, terms, limit)
        truncated = len(included) < len(rendered)
        any_truncated = any_truncated or truncated
        if included:
            included_ids.add(memory_id)
            docs.append(
                {
                    "memory_id": memory_id,
                    "memory_type": metadata.get("memory_type"),
                    "title": metadata.get("title", memory_id),
                    "path": relative_path,
                    "content": included,
                    "original_chars": len(original),
                    "rendered_chars": len(rendered),
                    "included_chars": len(included),
                    "truncated": truncated,
                    "retrieval_score": item["score"],
                    "selection_reason": (
                        "explicit_id"
                        if item["explicit"]
                        else (
                            f"{item['candidate_source']}_ranked"
                            if terms
                            else item["candidate_source"]
                        )
                    ),
                    "candidate_source": item["candidate_source"],
                    "matched_terms": item["matched_terms"],
                    "field_scores": item["field_scores"],
                }
            )
            remaining -= len(included)
        else:
            length_dropped_ids.append(memory_id)

    ranked_candidates_report = []
    source_rank = {"explicit_id": 0, "global_memory": 1, "auto_keyword": 2}
    for rank, item in enumerate(
        sorted(
            candidates,
            key=lambda candidate: (
                source_rank.get(candidate["candidate_source"], 9),
                -candidate["score"],
                candidate["memory_id"],
            ),
        ),
        1,
    ):
        memory_id = item["memory_id"]
        included = memory_id in included_ids
        if included:
            drop_reason = None
        elif memory_id in length_dropped_ids:
            drop_reason = "length_limit_exceeded"
        elif item["candidate_source"] == "auto_keyword" and item["score"] < auto_select["min_score"]:
            drop_reason = "min_score_excluded"
        elif memory_id not in initially_selected_ids and not item["explicit"]:
            drop_reason = "top_k_excluded"
        else:
            drop_reason = "not_included"
        ranked_candidates_report.append(
            {
                "rank": rank,
                "memory_id": memory_id,
                "memory_type": item["metadata"].get("memory_type"),
                "title": item["metadata"].get("title", memory_id),
                "path": item["relative_path"],
                "explicit": item["explicit"],
                "candidate_source": item["candidate_source"],
                "included": included,
                "drop_reason": drop_reason,
                "retrieval_score": item["score"],
                "matched_terms": item["matched_terms"],
                "field_scores": item["field_scores"],
                "field_matches": item["field_matches"],
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
        "retrieval": {
            "mode": "keyword_top_k" if terms else "configured_order",
            "terms": terms,
            "top_k": top_k,
            "per_doc_chars": per_doc_chars,
            "field_weights": weights,
            "auto_select": auto_select,
        },
        "ranked_candidates": ranked_candidates_report,
        "discarded_memory_ids": [
            item["memory_id"]
            for item in ranked_candidates_report
            if not item["included"] and item["drop_reason"] is not None
        ],
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
                "retrieval_mode": result["retrieval"]["mode"],
                "query": query,
                "query_terms": terms,
                "selected_count": len(docs),
                "candidate_count": len(ranked_candidates_report),
                "truncated": any_truncated,
                "discarded_memory_ids": result["discarded_memory_ids"],
                "auto_select_enabled": auto_select["enabled"],
                "errors": errors,
            },
            output_dir / "memory_log.jsonl",
        )
    return result


def _safe_conversation_id(conversation_id: str) -> str:
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", conversation_id):
        raise ValueError("conversation_id may only contain letters, numbers, dot, underscore, and hyphen")
    return conversation_id


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
            result = save_memory(
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
