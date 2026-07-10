from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from common.io_utils import append_jsonl, read_json, read_text, read_yaml, write_json, write_text
from common.conversation_store import (
    append_message,
    init_store,
    list_conversations,
    list_messages,
    list_tool_steps,
    record_tool_step,
    upsert_conversation,
)
from common.logging_utils import now_iso
from common.path_utils import resolve_cli_path, resolve_from_file


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


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    lowered = query.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered)
    terms: list[str] = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            terms.extend(list(word))
            terms.extend(word[index : index + 2] for index in range(max(0, len(word) - 1)))
        elif len(word) >= 2:
            terms.append(word)
    counts = Counter(terms)
    return [term for term, _ in counts.most_common()]


def _score_memory(metadata: dict, content: str, terms: list[str]) -> int:
    if not terms:
        return 0
    blob = "\n".join(
        [
            str(metadata.get("title", "")),
            str(metadata.get("summary", "")),
            content,
        ]
    ).lower()
    return sum(blob.count(term) for term in terms)


def _best_excerpt(content: str, terms: list[str], limit: int) -> str:
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
    return prefix + content[start:end] + suffix


def _retrieval_config(paths: dict[str, Path | int]) -> dict:
    config = paths.get("retrieval", {})
    return config if isinstance(config, dict) else {}


def _compact_summary(text: str, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def _extract_final_answer(markdown: str) -> str:
    match = re.search(r"## Final Answer\s*(.*?)\s*## Messages", markdown, flags=re.S)
    if not match:
        return ""
    return match.group(1).strip()


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
    return "rewrite_or_conflict"


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

    retrieval = _retrieval_config(paths)
    top_k = int(retrieval.get("top_k", 5))
    per_doc_chars = int(retrieval.get("per_doc_chars", paths["max_chars"]))
    top_k = max(1, top_k)
    per_doc_chars = max(1, per_doc_chars)
    terms = _query_terms(query)

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
        score = _score_memory(metadata, original, terms)
        candidates.append(
            {
                "memory_id": memory_id,
                "metadata": metadata,
                "relative_path": relative_path,
                "original": original,
                "score": score,
                "explicit": memory_id in selected_memory_ids,
            }
        )

    explicit_candidates = [item for item in candidates if item["explicit"]]
    ranked_candidates = [item for item in candidates if not item["explicit"]]
    if terms:
        ranked_candidates.sort(key=lambda item: (-item["score"], item["memory_id"]))
        ranked_candidates = ranked_candidates[:top_k]
    ranked = explicit_candidates + ranked_candidates
    ranked_ids = set()
    unique_ranked = []
    for item in ranked:
        if item["memory_id"] in ranked_ids:
            continue
        ranked_ids.add(item["memory_id"])
        unique_ranked.append(item)
    ranked = unique_ranked

    docs = []
    remaining = int(paths["max_chars"])
    any_truncated = False
    for item in ranked:
        if remaining <= 0:
            any_truncated = True
            break
        memory_id = item["memory_id"]
        metadata = item["metadata"]
        original = item["original"]
        relative_path = item["relative_path"]
        limit = min(per_doc_chars, remaining)
        included = _best_excerpt(original, terms, limit)
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
                    "retrieval_score": item["score"],
                    "selection_reason": "explicit_id" if item["explicit"] else ("keyword_top_k" if terms else "configured_order"),
                }
            )
            remaining -= len(included)
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
        },
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
        "update_analysis": {
            "existed_before": bool(old_text),
            "classification": update_kind,
            "old_chars": len(old_text),
            "new_chars": len(markdown),
            "old_summary": _compact_summary(old_answer, 120),
            "new_summary": _compact_summary(answer, 120),
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
