from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from b1_agent_runtime import run as run_agent_runtime  # noqa: E402
from b1_agent_runtime import run_stream as run_agent_runtime_stream  # noqa: E402
from b5_memory import (  # noqa: E402
    append_conversation_message,
    delete_conversation_record,
    init_conversation_db,
    list_conversation_history,
    list_conversation_records,
    list_conversation_messages,
    list_message_tool_steps,
    record_conversation_tool_step,
    update_conversation_message,
    upsert_conversation_record,
)


HOST = "127.0.0.1"
PORT = 8020
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "backend_runs"
UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"
TOOLS_CONFIG = PROJECT_ROOT / "configs" / "tools.yaml"
MEMORY_CONFIG = PROJECT_ROOT / "configs" / "memory.yaml"
MODEL_CONFIG = PROJECT_ROOT / "configs" / "model.yaml"
RUNTIME_BASE = PROJECT_ROOT / "data" / "__frontend_runtime__.json"
SYSTEM_PROMPT_PATH = "../prompts/local_tool_agent.txt"
MAX_UPLOAD_FILES = 5
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SUPPORTED_UPLOAD_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".py",
    ".log",
    ".docx",
    ".pptx",
}


class UploadedFileRef(BaseModel):
    name: str
    path: str
    size: int


class UploadFilePayload(BaseModel):
    name: str = Field(..., min_length=1)
    content_base64: str = Field(..., min_length=1)
    size: int | None = None
    mime_type: str | None = None


class UploadRequest(BaseModel):
    conversation_id: str | None = None
    files: list[UploadFilePayload] = Field(default_factory=list)


class UploadResponse(BaseModel):
    files: list[UploadedFileRef]


class RunRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    conversation_id: str | None = None
    uploaded_files: list[UploadedFileRef] = Field(default_factory=list)
    uploaded_file_payloads: list[UploadFilePayload] = Field(default_factory=list)
    selected_memory_ids: list[str] = Field(default_factory=list)
    use_global_memory: bool = False
    toolset: str = "basic_tools"
    save_memory: Literal["none", "conversation", "global"] = "conversation"
    llm_mode: Literal["mock", "prompt_json"] | None = None


class RunResponse(BaseModel):
    conversation_id: str
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    status: str
    final_answer: str
    elapsed_ms: float
    output_dir: str
    trace: dict


class ConversationSummary(BaseModel):
    id: str
    title: str
    is_trivial: bool = False
    created_at: str
    updated_at: str
    last_message_at: str | None = None


class ConversationMessage(BaseModel):
    id: str
    role: str
    content: str
    message_order: int
    created_at: str
    status: Literal["pending", "error"] | None = None
    tool_steps: list[dict] = Field(default_factory=list)
    attachments: list[UploadedFileRef] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage]


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    deleted: bool
    upload_dir_deleted: bool
    output_dir_deleted: bool


app = FastAPI(title="Agent Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_upload_filename(name: str, fallback: str) -> str:
    original = Path(name.strip()).name
    suffix = Path(original).suffix.lower()
    stem = Path(original).stem
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" ._")
    safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    if safe_suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported upload file type: {suffix or '(none)'}",
        )
    return f"{safe_stem or fallback}{safe_suffix}"


def _unique_child_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    path = Path(filename)
    for index in range(1, 1000):
        candidate = directory / f"{path.stem}_{index}{path.suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="too many uploaded files with the same name")


def _decode_upload_file(payload: UploadFilePayload) -> bytes:
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid base64 content for {payload.name}") from exc
    if payload.size is not None and payload.size != len(data):
        raise HTTPException(status_code=400, detail=f"upload size mismatch for {payload.name}")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"uploaded file is too large: {payload.name}")
    return data


def _save_uploaded_files(request: UploadRequest) -> list[UploadedFileRef]:
    if not request.files:
        raise HTTPException(status_code=400, detail="files are required")
    if len(request.files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"at most {MAX_UPLOAD_FILES} files can be uploaded at once")
    conversation_id = _safe_conversation_id(request.conversation_id)
    target_dir = UPLOAD_ROOT / conversation_id
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[UploadedFileRef] = []
    for index, file_payload in enumerate(request.files, 1):
        filename = _safe_upload_filename(file_payload.name, f"uploaded_{index}")
        data = _decode_upload_file(file_payload)
        target = _unique_child_path(target_dir, filename)
        target.write_bytes(data)
        saved.append(
            UploadedFileRef(
                name=file_payload.name,
                path=f"uploads/{conversation_id}/{target.name}",
                size=len(data),
            )
        )
    return saved


def _save_run_uploads(conversation_id: str, files: list[UploadFilePayload]) -> list[UploadedFileRef]:
    if not files:
        return []
    return _save_uploaded_files(UploadRequest(conversation_id=conversation_id, files=files))


def _delete_child_directory(root: Path, child_name: str) -> bool:
    root = root.resolve()
    target = (root / child_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="resolved delete path escaped allowed root") from exc
    if target == root:
        raise HTTPException(status_code=400, detail="refusing to delete root directory")
    if not target.exists():
        return False
    if not target.is_dir():
        raise HTTPException(status_code=409, detail=f"delete target is not a directory: {target.name}")
    shutil.rmtree(target)
    return True


def _user_input_with_uploaded_files(user_input: str, files: list[UploadedFileRef]) -> str:
    if not files:
        return user_input
    lines = [
        "本次用户上传了以下文件。调用文件工具时，path 必须原样使用这里给出的规范路径：",
    ]
    for file in files:
        lines.append(f"- path: {file.path}")
    lines.extend(
        [
            "如果当前用户输入中的“这份文档”“这个文件”“附件”“上传文件”等指代不明确，优先使用上述上传文件路径。",
            "",
            "当前用户输入：",
            user_input,
        ]
    )
    return "\n".join(lines)


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _safe_conversation_id(value: str | None) -> str:
    if value is None or not value.strip():
        return f"conv_web_{_now_stamp()}"
    cleaned = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", cleaned):
        raise HTTPException(status_code=400, detail="conversation_id contains unsupported characters")
    return cleaned


def _read_trace(trace_path: str) -> dict:
    trace = _read_json_file(trace_path)
    if not isinstance(trace, dict):
        return {}
    return {
        "tool_rounds_used": trace.get("tool_rounds_used"),
        "llm_call_count": trace.get("llm_call_count"),
        "final_state": trace.get("final_state"),
        "finish_reason": trace.get("finish_reason"),
        "memory_save": trace.get("memory_save"),
        "warnings": trace.get("warnings", []),
        "error": trace.get("error"),
    }


def _read_json_file(path_text: str) -> dict | list | None:
    path = Path(path_text)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _write_json_file(path_text: str, payload: dict | list) -> None:
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _stream_event(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _short_title(text: str, limit: int = 18) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return "新对话"
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _is_trivial_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    return compact in {"你好", "您好", "hi", "hello", "在吗", "你是谁", "谢谢", "好的", "ok"}


def _is_trivial_conversation(history: list[dict], current_user_input: str) -> bool:
    user_texts = [message["content"] for message in history if message.get("role") == "user"]
    user_texts.append(current_user_input)
    return bool(user_texts) and all(_is_trivial_text(text) for text in user_texts)


def _history_title(history: list[dict], current_user_input: str) -> str:
    for message in history:
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return _short_title(message["content"])
    return _short_title(current_user_input)


def _extract_tool_steps(trace: dict) -> list[dict]:
    steps = []
    turns = trace.get("turns", [])
    if not isinstance(turns, list):
        return steps
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        ai_message = turn.get("ai_message") if isinstance(turn.get("ai_message"), dict) else {}
        assistant_content = ai_message.get("content") if isinstance(ai_message.get("content"), str) else ""
        raw_tool_calls = ai_message.get("tool_calls") if isinstance(ai_message, dict) else []
        tool_calls_by_id = {
            call.get("id"): call
            for call in raw_tool_calls
            if isinstance(call, dict) and isinstance(call.get("id"), str)
        } if isinstance(raw_tool_calls, list) else {}
        for tool_message in turn.get("tool_messages", []):
            if not isinstance(tool_message, dict):
                continue
            raw_content = tool_message.get("content")
            try:
                parsed = json.loads(raw_content) if isinstance(raw_content, str) else {}
            except json.JSONDecodeError:
                parsed = {}
            tool_call_id = tool_message.get("tool_call_id")
            tool_call = tool_calls_by_id.get(tool_call_id)
            input_data = parsed.get("input")
            if tool_call is not None:
                input_data = {
                    "assistant_content_before_tool": assistant_content,
                    "tool_call": tool_call,
                    "skill_input": input_data,
                }
            output_data = parsed.get("output")
            steps.append(
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_message.get("name") or parsed.get("skill_name") or "unknown",
                    "input_data": input_data,
                    "output_data": output_data,
                    "status": tool_message.get("status") or parsed.get("status") or "unknown",
                    "error": parsed.get("error"),
                    "latency_ms": parsed.get("latency_ms"),
                }
            )
    return steps


def _read_trace_full(trace_path: str) -> dict:
    trace = _read_json_file(trace_path)
    return trace if isinstance(trace, dict) else {}


def _read_messages(path_text: str) -> list[dict]:
    messages = _read_json_file(path_text)
    return messages if isinstance(messages, list) else []


def _assistant_metadata(result: dict, trace: dict) -> dict:
    return {
        "agent_status": result.get("status"),
        "elapsed_ms": result.get("elapsed_ms"),
        "trace_path": result.get("trace_path"),
        "output_dir": str(Path(result.get("trace_path", "")).parent) if result.get("trace_path") else None,
        "llm_call_count": trace.get("llm_call_count"),
        "tool_rounds_used": trace.get("tool_rounds_used"),
        "final_state": trace.get("final_state"),
        "finish_reason": trace.get("finish_reason"),
        "memory_save": trace.get("memory_save"),
    }


def _message_ui_status(message: dict) -> str | None:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    status = metadata.get("ui_status")
    return status if status in {"pending", "error"} else None


def _message_attachments(message: dict) -> list[UploadedFileRef]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    raw_attachments = metadata.get("attachments")
    if not isinstance(raw_attachments, list):
        return []
    attachments = []
    for item in raw_attachments:
        try:
            attachments.append(UploadedFileRef.model_validate(item))
        except (TypeError, ValueError):
            continue
    return attachments


def _build_runtime_payload(
    request: RunRequest,
    conversation_id: str,
    user_input: str,
    history_messages: list[dict],
) -> dict:
    # Web chat passes completed SQLite turns through history_messages. Optional
    # legacy markdown memory still flows through B1 when explicitly selected.
    selected_memory_ids = request.selected_memory_ids
    use_global_memory = request.use_global_memory
    return {
        "conversation_id": conversation_id,
        "user_input": user_input,
        "history_messages": history_messages,
        "system_prompt_path": SYSTEM_PROMPT_PATH,
        "selected_memory_ids": selected_memory_ids,
        "use_global_memory": use_global_memory,
        "toolset": request.toolset,
        "save_memory": "none",
    }


def _record_tool_steps(
    conversation_id: str,
    assistant_message_id: str,
    run_id: str,
    trace: dict,
) -> None:
    for index, step in enumerate(_extract_tool_steps(trace), 1):
        record_conversation_tool_step(
            str(MEMORY_CONFIG),
            conversation_id,
            assistant_message_id,
            step["tool_name"],
            index,
            run_id=run_id,
            tool_call_id=step.get("tool_call_id"),
            input_data=step.get("input_data"),
            output_data=step.get("output_data"),
            status=step.get("status") or "unknown",
            error=step.get("error"),
            latency_ms=step.get("latency_ms"),
        )


def _start_run_messages(
    conversation_id: str,
    run_id: str,
    raw_user_input: str,
    history: list[dict],
    uploaded_files: list[UploadedFileRef],
) -> tuple[str, str]:
    user_record = append_conversation_message(
        str(MEMORY_CONFIG),
        conversation_id,
        "user",
        raw_user_input,
        run_id=run_id,
        is_trivial=_is_trivial_text(raw_user_input),
        metadata={
            "attachments": [file.model_dump() for file in uploaded_files],
        } if uploaded_files else None,
    )
    assistant_record = append_conversation_message(
        str(MEMORY_CONFIG),
        conversation_id,
        "assistant",
        "...",
        run_id=run_id,
        metadata={"ui_status": "pending", "agent_status": "running"},
    )
    title = _history_title(history, raw_user_input)
    upsert_conversation_record(
        str(MEMORY_CONFIG),
        conversation_id,
        title,
        is_trivial=_is_trivial_conversation(history, raw_user_input),
        trivial_reason="only trivial user messages" if _is_trivial_conversation(history, raw_user_input) else None,
    )
    return user_record["message_id"], assistant_record["message_id"]


def _finish_run_message(
    conversation_id: str,
    assistant_message_id: str,
    run_id: str,
    result: dict,
    trace: dict,
) -> None:
    metadata = _assistant_metadata(result, trace)
    if result.get("status") != "success":
        metadata["ui_status"] = "error"
    update_conversation_message(
        str(MEMORY_CONFIG),
        assistant_message_id,
        content=result["final_answer"] or "[empty response]",
        metadata=metadata,
    )
    _record_tool_steps(conversation_id, assistant_message_id, run_id, trace)


def _mark_run_failed(assistant_message_id: str, error: Exception) -> None:
    update_conversation_message(
        str(MEMORY_CONFIG),
        assistant_message_id,
        content=f"请求失败：{type(error).__name__}: {error}",
        metadata={
            "ui_status": "error",
            "agent_status": "backend_error",
            "error": {"type": type(error).__name__, "message": str(error)},
        },
    )


def _call_agent(request: RunRequest) -> RunResponse:
    conversation_id = _safe_conversation_id(request.conversation_id)
    raw_user_input = request.user_input.strip()
    init_conversation_db(str(MEMORY_CONFIG))
    history = list_conversation_messages(str(MEMORY_CONFIG), conversation_id)
    history_messages = list_conversation_history(str(MEMORY_CONFIG), conversation_id)
    title = _history_title(history, raw_user_input)
    upsert_conversation_record(
        str(MEMORY_CONFIG),
        conversation_id,
        title,
        is_trivial=_is_trivial_conversation(history, raw_user_input),
        trivial_reason="only trivial user messages" if _is_trivial_conversation(history, raw_user_input) else None,
    )
    uploaded_refs = [
        *request.uploaded_files,
        *_save_run_uploads(conversation_id, request.uploaded_file_payloads),
    ]
    agent_user_input = _user_input_with_uploaded_files(raw_user_input, uploaded_refs)
    runtime_payload = _build_runtime_payload(
        request, conversation_id, agent_user_input, history_messages
    )
    run_id = _now_stamp()
    user_message_id, assistant_message_id = _start_run_messages(
        conversation_id,
        run_id,
        raw_user_input,
        history,
        uploaded_refs,
    )
    output_dir = OUTPUT_ROOT / conversation_id / run_id
    try:
        result = run_agent_runtime(
            runtime_payload,
            str(TOOLS_CONFIG),
            str(MEMORY_CONFIG),
            str(MODEL_CONFIG),
            str(output_dir),
            request.llm_mode,
            RUNTIME_BASE,
        )
    except Exception as exc:
        _mark_run_failed(assistant_message_id, exc)
        raise
    full_trace = _read_trace_full(result["trace_path"])
    _finish_run_message(
        conversation_id,
        assistant_message_id,
        run_id,
        result,
        full_trace,
    )
    full_trace["memory_save"] = {
        "requested": "database",
        "status": "success",
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "storage": "sqlite",
    }
    _write_json_file(result["trace_path"], full_trace)
    return RunResponse(
        conversation_id=result["conversation_id"],
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status=result["status"],
        final_answer=result["final_answer"],
        elapsed_ms=result["elapsed_ms"],
        output_dir=str(output_dir),
        trace=_read_trace(result["trace_path"]),
    )


def _stream_agent(request: RunRequest) -> Iterator[str]:
    conversation_id = _safe_conversation_id(request.conversation_id)
    raw_user_input = request.user_input.strip()
    init_conversation_db(str(MEMORY_CONFIG))
    history = list_conversation_messages(str(MEMORY_CONFIG), conversation_id)
    history_messages = list_conversation_history(str(MEMORY_CONFIG), conversation_id)
    title = _history_title(history, raw_user_input)
    upsert_conversation_record(
        str(MEMORY_CONFIG),
        conversation_id,
        title,
        is_trivial=_is_trivial_conversation(history, raw_user_input),
        trivial_reason="only trivial user messages" if _is_trivial_conversation(history, raw_user_input) else None,
    )
    uploaded_refs = [
        *request.uploaded_files,
        *_save_run_uploads(conversation_id, request.uploaded_file_payloads),
    ]
    agent_user_input = _user_input_with_uploaded_files(raw_user_input, uploaded_refs)
    runtime_payload = _build_runtime_payload(
        request, conversation_id, agent_user_input, history_messages
    )
    run_id = _now_stamp()
    user_message_id, assistant_message_id = _start_run_messages(
        conversation_id,
        run_id,
        raw_user_input,
        history,
        uploaded_refs,
    )
    output_dir = OUTPUT_ROOT / conversation_id / run_id
    yield _stream_event(
        {
            "type": "start",
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
        }
    )
    streamed_answer = ""
    candidate_chunks: list[str] = []
    try:
        for event in run_agent_runtime_stream(
            runtime_payload,
            str(TOOLS_CONFIG),
            str(MEMORY_CONFIG),
            str(MODEL_CONFIG),
            str(output_dir),
            request.llm_mode,
            RUNTIME_BASE,
        ):
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "delta":
                delta = str(event.get("text", ""))
                if not delta:
                    continue
                candidate_chunks.append(delta)
            elif event_type == "state":
                action = event.get("action")
                if action == "finish" and candidate_chunks:
                    streamed_answer = "".join(candidate_chunks)
                    update_conversation_message(
                        str(MEMORY_CONFIG),
                        assistant_message_id,
                        content=streamed_answer,
                        metadata={"ui_status": "pending", "agent_status": "running_stream"},
                    )
                    yield _stream_event(
                        {
                            "type": "delta",
                            "conversation_id": conversation_id,
                            "assistant_message_id": assistant_message_id,
                            "text": streamed_answer,
                        }
                    )
                candidate_chunks = []
                yield _stream_event(
                    {
                        "type": "state",
                        "conversation_id": conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "state": event.get("state"),
                        "action": event.get("action"),
                        "reason": event.get("reason"),
                        "llm_call_index": event.get("llm_call_index"),
                        "tool_round_index": event.get("tool_round_index"),
                        "detail": event.get("detail"),
                    }
                )
            elif event_type == "tool_start":
                streamed_answer = ""
                candidate_chunks = []
                update_conversation_message(
                    str(MEMORY_CONFIG),
                    assistant_message_id,
                    content="...",
                    metadata={"ui_status": "pending", "agent_status": "running_tool"},
                )
                yield _stream_event(
                    {
                        "type": "tool_start",
                        "conversation_id": conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "tool_calls": event.get("tool_calls", []),
                        "assistant_content": event.get("assistant_content", ""),
                    }
                )
            elif event_type == "tool_done":
                yield _stream_event(
                    {
                        "type": "tool_done",
                        "conversation_id": conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "tool_messages": event.get("tool_messages", []),
                    }
                )
            elif event_type == "done":
                result = event.get("result")
                if not isinstance(result, dict):
                    raise ValueError("stream runtime finished without a result object")
                full_trace = _read_trace_full(result["trace_path"])
                _finish_run_message(
                    conversation_id,
                    assistant_message_id,
                    run_id,
                    result,
                    full_trace,
                )
                full_trace["memory_save"] = {
                    "requested": "database",
                    "status": "success",
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "storage": "sqlite",
                }
                _write_json_file(result["trace_path"], full_trace)
                tool_steps = list_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id)
                yield _stream_event(
                    {
                        "type": "done",
                        "conversation_id": result["conversation_id"],
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "status": result["status"],
                        "final_answer": result["final_answer"],
                        "elapsed_ms": result["elapsed_ms"],
                        "output_dir": str(output_dir),
                        "trace": _read_trace(result["trace_path"]),
                        "tool_steps": tool_steps,
                    }
                )
                return
    except Exception as exc:
        _mark_run_failed(assistant_message_id, exc)
        yield _stream_event(
            {
                "type": "error",
                "conversation_id": conversation_id,
                "assistant_message_id": assistant_message_id,
                "message": f"{type(exc).__name__}: {exc}",
            }
        )


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "agent_runtime": "b1",
        "model_config": str(MODEL_CONFIG),
        "features": {
            "upload_in_run": True,
            "current_time_tool": True,
        },
    }


@app.post("/api/uploads", response_model=UploadResponse)
async def upload_files(request: UploadRequest) -> UploadResponse:
    return UploadResponse(files=await asyncio.to_thread(_save_uploaded_files, request))


@app.get("/api/conversations", response_model=list[ConversationSummary])
def get_conversations(limit: int = 50) -> list[ConversationSummary]:
    init_conversation_db(str(MEMORY_CONFIG))
    records = list_conversation_records(str(MEMORY_CONFIG), max(1, min(limit, 200)))
    return [
        ConversationSummary(
            id=record["id"],
            title=record["title"],
            is_trivial=bool(record["is_trivial"]),
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            last_message_at=record.get("last_message_at"),
        )
        for record in records
    ]


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str) -> ConversationDetail:
    conversation_id = _safe_conversation_id(conversation_id)
    init_conversation_db(str(MEMORY_CONFIG))
    messages = list_conversation_messages(str(MEMORY_CONFIG), conversation_id)
    visible = [
        ConversationMessage(
            id=message["id"],
            role=message["role"],
            content=message["content"],
            message_order=message["message_order"],
            created_at=message["created_at"],
            status=_message_ui_status(message),
            tool_steps=list_message_tool_steps(str(MEMORY_CONFIG), message["id"]) if message["role"] == "assistant" else [],
            attachments=_message_attachments(message) if message["role"] == "user" else [],
        )
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    return ConversationDetail(conversation_id=conversation_id, messages=visible)


@app.delete("/api/conversations/{conversation_id}", response_model=DeleteConversationResponse)
def delete_conversation(conversation_id: str) -> DeleteConversationResponse:
    conversation_id = _safe_conversation_id(conversation_id)
    init_conversation_db(str(MEMORY_CONFIG))
    record = delete_conversation_record(str(MEMORY_CONFIG), conversation_id)
    if not record.get("deleted"):
        raise HTTPException(status_code=404, detail="conversation not found")
    upload_dir_deleted = _delete_child_directory(UPLOAD_ROOT, conversation_id)
    output_dir_deleted = _delete_child_directory(OUTPUT_ROOT, conversation_id)
    return DeleteConversationResponse(
        conversation_id=conversation_id,
        deleted=bool(record.get("deleted")),
        upload_dir_deleted=upload_dir_deleted,
        output_dir_deleted=output_dir_deleted,
    )


@app.get("/api/messages/{message_id}/tool-steps")
def get_message_tool_steps(message_id: str) -> dict:
    init_conversation_db(str(MEMORY_CONFIG))
    return {"message_id": message_id, "tool_steps": list_message_tool_steps(str(MEMORY_CONFIG), message_id)}


@app.post("/api/run", response_model=RunResponse)
async def run_agent(request: RunRequest) -> RunResponse:
    if not request.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input is required")
    try:
        return await asyncio.to_thread(_call_agent, request)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/run/stream")
async def run_agent_stream(request: RunRequest) -> StreamingResponse:
    if not request.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input is required")
    return StreamingResponse(
        _stream_agent(request),
        media_type="application/x-ndjson; charset=utf-8",
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
