from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from threading import Event, Lock, Thread
from typing import Iterator
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api_models import (  # noqa: E402
    B2SkillRunRequest,
    B3ToolCallsPreviewRequest,
    B5RecallPreviewRequest,
    ConversationDetail,
    ConversationMessage,
    ConversationPromptResponse,
    ConversationSummary,
    DeleteConversationResponse,
    RunRequest,
    RunResponse,
    UpdateConversationPromptRequest,
    UploadRequest,
    UploadResponse,
    UploadedFileRef,
)
from backend.conversation_utils import (  # noqa: E402
    assistant_metadata as _assistant_metadata,
    extract_tool_steps as _extract_tool_steps,
    history_title as _history_title,
    is_trivial_conversation as _is_trivial_conversation,
    is_trivial_text as _is_trivial_text,
    message_attachments as _message_attachments,
    message_resumable as _message_resumable,
    message_ui_status as _message_ui_status,
    read_trace as _read_trace,
    read_trace_full as _read_trace_full,
    stream_event as _stream_event,
    write_json_file as _write_json_file,
)
from backend.settings import (  # noqa: E402
    CODE_DIR,
    DEFAULT_SYSTEM_PROMPTS_PATH,
    HOST,
    MEMORY_CONFIG,
    MODEL_CONFIG,
    OUTPUT_ROOT,
    PORT,
    PROMPT_STORE_PATH,
    RUNTIME_BASE,
    SYSTEM_PROMPT_PATH,
    TOOLS_CONFIG,
    UPLOAD_ROOT,
)
from backend.uploads import (  # noqa: E402
    delete_child_directory,
    save_run_uploads,
    save_uploaded_files,
    uploaded_image_data_urls,
    user_input_with_uploaded_files,
)

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from b1_agent_runtime import resume_stream as resume_agent_runtime_stream  # noqa: E402
from b1_agent_runtime import run as run_agent_runtime  # noqa: E402
from b1_agent_runtime import run_stream as run_agent_runtime_stream  # noqa: E402
from b1_agent_runtime_parts.b1_checkpoint import checkpoint_metadata, load_checkpoint  # noqa: E402
from b2_run_skill import run_skill as run_b2_skill  # noqa: E402
from b3_tool_layer import execute_tool_calls as execute_b3_tool_calls  # noqa: E402
from b3_tool_layer import get_tools_schema as get_b3_tools_schema  # noqa: E402
from common.identifiers import validate_conversation_id  # noqa: E402
from common.io_utils import append_jsonl, write_json  # noqa: E402
from common.logging_utils import now_iso  # noqa: E402
from common.prompt_store import (  # noqa: E402
    delete_conversation_prompt,
    default_system_prompt,
    get_conversation_prompt,
    update_conversation_prompt,
)
from common.tool_config import get_tool_definition, load_tools_config, resolve_toolset  # noqa: E402
from b5_memory import (  # noqa: E402
    append_conversation_message,
    clear_message_tool_steps,
    delete_conversation_record,
    get_conversation_memory_snapshot,
    init_conversation_db,
    list_conversation_history,
    list_conversation_records,
    list_conversation_messages,
    list_message_tool_steps,
    prepare_workspace_memory_context,
    record_completed_turn_memory,
    record_conversation_tool_step,
    update_conversation_message,
    upsert_conversation_record,
)


app = FastAPI(title="Agent Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_RUN_CANCEL_EVENTS: dict[str, Event] = {}
_RUN_CANCEL_LOCK = Lock()


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _safe_conversation_id(value: str | None) -> str:
    if value is None or not value.strip():
        return f"conv_web_{_now_stamp()}"
    cleaned = value.strip()
    try:
        return validate_conversation_id(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="conversation_id contains unsupported characters") from exc


def _safe_run_id(value: str) -> str:
    try:
        return validate_conversation_id(value.strip())
    except (AttributeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="run_id contains unsupported characters") from exc


def _safe_generated_artifact_path(relative_path: str) -> Path:
    normalized = relative_path.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or path.parts[0] != "generated_files":
        raise HTTPException(status_code=400, detail="artifact path must stay inside generated_files")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(status_code=400, detail="artifact path contains unsupported segments")
    return Path(*path.parts)


def _artifact_download_url(output_dir: Path, relative_output_path: object) -> str | None:
    if not isinstance(relative_output_path, str) or not relative_output_path.strip():
        return None
    try:
        artifact_path = _safe_generated_artifact_path(relative_output_path)
        output_dir.resolve().relative_to(OUTPUT_ROOT.resolve())
    except (HTTPException, ValueError):
        return None
    conversation_id = output_dir.parent.name
    run_id = output_dir.name
    if not conversation_id or not run_id:
        return None
    encoded_path = "/".join(quote(part, safe="") for part in PurePosixPath(artifact_path.as_posix()).parts)
    return f"/api/artifacts/{quote(conversation_id, safe='')}/{quote(run_id, safe='')}/{encoded_path}"


def _attach_artifact_download_urls(result: dict, output_dir: Path) -> None:
    output = result.get("output")
    if isinstance(output, dict):
        download_url = _artifact_download_url(output_dir, output.get("relative_output_path"))
        if download_url:
            output.setdefault("download_url", download_url)
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        return
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        download_url = _artifact_download_url(output_dir, artifact.get("relative_output_path"))
        if download_url:
            artifact.setdefault("download_url", download_url)


def _b2_skill_summary(name: str, definition: dict, enabled: bool) -> dict:
    parameters = definition.get("parameters") if isinstance(definition.get("parameters"), dict) else {}
    returns = definition.get("returns") if isinstance(definition.get("returns"), dict) else {}
    required = definition.get("required") if isinstance(definition.get("required"), list) else []
    return {
        "name": name,
        "enabled": enabled,
        "module": definition.get("module"),
        "function": definition.get("function"),
        "description": definition.get("description"),
        "side_effects": bool(definition.get("side_effects")),
        "parameters": parameters,
        "required": required,
        "returns": returns,
        "parameter_count": len(parameters),
        "return_count": len(returns),
    }


def _b3_tool_calls_from_request(request: B3ToolCallsPreviewRequest) -> list:
    if request.tool_calls:
        return request.tool_calls
    if isinstance(request.ai_message, dict):
        tool_calls = request.ai_message.get("tool_calls")
        if isinstance(tool_calls, list):
            return tool_calls
    return []


def _parse_b3_tool_message(message: dict) -> dict | None:
    content = message.get("content")
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _register_cancel_event(conversation_id: str) -> Event:
    cancel_event = Event()
    with _RUN_CANCEL_LOCK:
        _RUN_CANCEL_EVENTS[conversation_id] = cancel_event
    return cancel_event


def _request_cancel(conversation_id: str) -> bool:
    with _RUN_CANCEL_LOCK:
        cancel_event = _RUN_CANCEL_EVENTS.get(conversation_id)
    if cancel_event is None:
        return False
    cancel_event.set()
    return True


def _clear_cancel_event(conversation_id: str, cancel_event: Event) -> None:
    with _RUN_CANCEL_LOCK:
        if _RUN_CANCEL_EVENTS.get(conversation_id) is cancel_event:
            _RUN_CANCEL_EVENTS.pop(conversation_id, None)


def _build_runtime_payload(
    request: RunRequest,
    conversation_id: str,
    user_input: str,
    history_messages: list[dict],
    input_images: list[str],
) -> dict:
    # Web chat passes completed SQLite turns through history_messages. Optional
    # legacy markdown memory still flows through B1 when explicitly selected.
    selected_memory_ids = request.selected_memory_ids
    use_global_memory = request.use_global_memory
    prompt_text = request.system_prompt.strip() if isinstance(request.system_prompt, str) and request.system_prompt.strip() else None
    if prompt_text is None:
        prompt_text = get_conversation_prompt(
            conversation_id,
            PROMPT_STORE_PATH,
            DEFAULT_SYSTEM_PROMPTS_PATH,
        )["content"]
    else:
        update_conversation_prompt(
            conversation_id,
            prompt_text,
            PROMPT_STORE_PATH,
            DEFAULT_SYSTEM_PROMPTS_PATH,
        )
    return {
        "conversation_id": conversation_id,
        "user_input": user_input,
        "history_messages": history_messages,
        "input_images": input_images,
        "system_prompt_path": SYSTEM_PROMPT_PATH,
        "system_prompt": prompt_text,
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
    if result.get("status") == "cancelled":
        metadata["ui_status"] = "cancelled"
        metadata["cancelled"] = True
        metadata["resumable"] = True
    elif result.get("status") != "success":
        metadata["ui_status"] = "error"
    update_conversation_message(
        str(MEMORY_CONFIG),
        assistant_message_id,
        content=result["final_answer"] or "[empty response]",
        metadata=metadata,
    )
    _record_tool_steps(conversation_id, assistant_message_id, run_id, trace)


def _record_completed_turn_memory(
    conversation_id: str,
    run_id: str,
    user_message_id: str,
    assistant_message_id: str,
    raw_user_input: str,
    result: dict,
    trace: dict,
    llm_mode: str | None,
    output_dir: Path,
) -> dict:
    try:
        return record_completed_turn_memory(
            str(MEMORY_CONFIG),
            conversation_id,
            run_id,
            user_message_id,
            assistant_message_id,
            raw_user_input,
            result.get("final_answer") or "",
            trace,
            str(MODEL_CONFIG) if result.get("status") == "success" else None,
            llm_mode,
            str(output_dir / "memory_reflection"),
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def _write_turn_memory_result(trace_path: str, turn_memory: dict) -> None:
    trace = _read_trace_full(trace_path)
    memory_save = trace.get("memory_save") if isinstance(trace.get("memory_save"), dict) else {}
    memory_save["turn_memory"] = turn_memory
    trace["memory_save"] = memory_save
    _write_json_file(trace_path, trace)


def _schedule_completed_turn_memory(
    conversation_id: str,
    run_id: str,
    user_message_id: str,
    assistant_message_id: str,
    raw_user_input: str,
    result: dict,
    trace: dict,
    llm_mode: str | None,
    output_dir: Path,
    trace_path: str,
) -> dict:
    scheduled = {
        "status": "scheduled",
        "mode": "background",
        "reason": "memory reflection and layered memory writes run after the user response",
    }

    def worker() -> None:
        try:
            turn_memory = _record_completed_turn_memory(
                conversation_id,
                run_id,
                user_message_id,
                assistant_message_id,
                raw_user_input,
                result,
                trace,
                llm_mode,
                output_dir,
            )
            _write_turn_memory_result(trace_path, turn_memory)
        except Exception:
            return

    Thread(target=worker, name=f"memory-{run_id}", daemon=True).start()
    return scheduled


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


def _mark_run_cancelled(assistant_message_id: str, partial_answer: str = "") -> None:
    content = partial_answer.strip() or "已终止回答。"
    update_conversation_message(
        str(MEMORY_CONFIG),
        assistant_message_id,
        content=content,
        metadata={
            "ui_status": "cancelled",
            "agent_status": "cancelled",
            "cancelled": True,
            "resumable": True,
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
        *save_run_uploads(conversation_id, request.uploaded_file_payloads),
    ]
    agent_user_input = user_input_with_uploaded_files(raw_user_input, uploaded_refs)
    input_images = uploaded_image_data_urls(uploaded_refs)
    runtime_payload = _build_runtime_payload(
        request, conversation_id, agent_user_input, history_messages, input_images
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
        "turn_memory": {
            "status": "scheduled",
            "mode": "background",
            "reason": "memory reflection and layered memory writes run after the user response",
        },
    }
    _write_json_file(result["trace_path"], full_trace)
    _schedule_completed_turn_memory(
        conversation_id,
        run_id,
        user_message_id,
        assistant_message_id,
        raw_user_input,
        result,
        full_trace,
        request.llm_mode,
        output_dir,
        result["trace_path"],
    )
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
        *save_run_uploads(conversation_id, request.uploaded_file_payloads),
    ]
    agent_user_input = user_input_with_uploaded_files(raw_user_input, uploaded_refs)
    input_images = uploaded_image_data_urls(uploaded_refs)
    runtime_payload = _build_runtime_payload(
        request, conversation_id, agent_user_input, history_messages, input_images
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
    cancel_event = _register_cancel_event(conversation_id)
    streamed_answer = ""
    candidate_chunks: list[str] = []
    run_finished = False
    try:
        yield _stream_event(
            {
                "type": "start",
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
            }
        )
        for event in run_agent_runtime_stream(
            runtime_payload,
            str(TOOLS_CONFIG),
            str(MEMORY_CONFIG),
            str(MODEL_CONFIG),
            str(output_dir),
            request.llm_mode,
            RUNTIME_BASE,
            should_cancel=cancel_event.is_set,
        ):
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "delta":
                delta = str(event.get("text", ""))
                if not delta:
                    continue
                candidate_chunks.append(delta)
                streamed_answer += delta
                yield _stream_event(
                    {
                        "type": "delta",
                        "conversation_id": conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "text": delta,
                    }
                )
            elif event_type == "state":
                candidate_chunks = []
                yield _stream_event(
                    {
                        "type": "state",
                        "conversation_id": conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "state": event.get("state"),
                        "action": event.get("action"),
                        "reason": event.get("reason"),
                        "agent_step": event.get("agent_step"),
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
                        "agent_step": event.get("agent_step"),
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
                if result.get("status") == "cancelled":
                    full_trace["memory_save"] = {
                        "requested": "database",
                        "status": "skipped",
                        "reason": "cancelled",
                        "conversation_id": conversation_id,
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "storage": "sqlite",
                        "turn_memory": {"status": "skipped", "reason": "cancelled"},
                    }
                    _write_json_file(result["trace_path"], full_trace)
                else:
                    full_trace["memory_save"] = {
                        "requested": "database",
                        "status": "success",
                        "conversation_id": conversation_id,
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "storage": "sqlite",
                        "turn_memory": {
                            "status": "scheduled",
                            "mode": "background",
                            "reason": "memory reflection and layered memory writes run after the user response",
                        },
                    }
                    _write_json_file(result["trace_path"], full_trace)
                    _schedule_completed_turn_memory(
                        conversation_id,
                        run_id,
                        user_message_id,
                        assistant_message_id,
                        raw_user_input,
                        result,
                        full_trace,
                        request.llm_mode,
                        output_dir,
                        result["trace_path"],
                    )
                tool_steps = list_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id)
                run_finished = True
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
    except GeneratorExit:
        if not run_finished:
            _mark_run_cancelled(assistant_message_id, streamed_answer or "".join(candidate_chunks))
        raise
    except Exception as exc:
        if cancel_event.is_set():
            cancelled_answer = streamed_answer or "".join(candidate_chunks)
            _mark_run_cancelled(assistant_message_id, cancelled_answer)
            yield _stream_event(
                {
                    "type": "done",
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "cancelled",
                    "final_answer": cancelled_answer.strip() or "已终止回答。",
                    "elapsed_ms": None,
                    "output_dir": str(output_dir),
                    "trace": {
                        "final_state": "failed",
                        "finish_reason": "user cancelled",
                        "memory_save": {"status": "skipped", "reason": "cancelled"},
                    },
                    "tool_steps": list_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id),
                }
            )
            return
        _mark_run_failed(assistant_message_id, exc)
        yield _stream_event(
            {
                "type": "error",
                "conversation_id": conversation_id,
                "assistant_message_id": assistant_message_id,
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        _clear_cancel_event(conversation_id, cancel_event)


def _safe_stream_agent(request: RunRequest) -> Iterator[str]:
    try:
        yield from _stream_agent(request)
    except Exception as exc:
        yield _stream_event(
            {
                "type": "error",
                "conversation_id": request.conversation_id,
                "message": f"{type(exc).__name__}: {exc}",
            }
        )


def _resume_message_context(conversation_id: str, assistant_message_id: str) -> dict:
    messages = list_conversation_messages(str(MEMORY_CONFIG), conversation_id)
    target = None
    previous_user = None
    for message in messages:
        if message.get("id") == assistant_message_id:
            target = message
            break
        if message.get("role") == "user":
            previous_user = message
    if target is None or target.get("role") != "assistant":
        raise HTTPException(status_code=404, detail="assistant message not found")
    if previous_user is None:
        raise HTTPException(status_code=400, detail="cannot resume without a previous user message")
    return {
        "run_id": target.get("run_id") or _now_stamp(),
        "user_message_id": previous_user["id"],
        "raw_user_input": previous_user["content"],
    }


def _stream_resume_agent(conversation_id: str, assistant_message_id: str) -> Iterator[str]:
    safe_conversation_id = _safe_conversation_id(conversation_id)
    init_conversation_db(str(MEMORY_CONFIG))
    context = _resume_message_context(safe_conversation_id, assistant_message_id)
    run_id = context["run_id"]
    user_message_id = context["user_message_id"]
    raw_user_input = context["raw_user_input"]
    update_conversation_message(
        str(MEMORY_CONFIG),
        assistant_message_id,
        content="...",
        metadata={"ui_status": "pending", "agent_status": "resuming", "resumable": True},
    )
    clear_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id)
    cancel_event = _register_cancel_event(safe_conversation_id)
    streamed_answer = ""
    candidate_chunks: list[str] = []
    run_finished = False
    output_dir = OUTPUT_ROOT / safe_conversation_id / run_id
    try:
        yield _stream_event(
            {
                "type": "start",
                "conversation_id": safe_conversation_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "resumed": True,
            }
        )
        for event in resume_agent_runtime_stream(safe_conversation_id, should_cancel=cancel_event.is_set):
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "delta":
                delta = str(event.get("text", ""))
                if not delta:
                    continue
                candidate_chunks.append(delta)
                streamed_answer += delta
                yield _stream_event(
                    {
                        "type": "delta",
                        "conversation_id": safe_conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "text": delta,
                    }
                )
            elif event_type == "state":
                candidate_chunks = []
                yield _stream_event(
                    {
                        "type": "state",
                        "conversation_id": safe_conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "state": event.get("state"),
                        "action": event.get("action"),
                        "reason": event.get("reason"),
                        "agent_step": event.get("agent_step"),
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
                    metadata={"ui_status": "pending", "agent_status": "running_tool", "resumable": True},
                )
                yield _stream_event(
                    {
                        "type": "tool_start",
                        "conversation_id": safe_conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "tool_calls": event.get("tool_calls", []),
                        "assistant_content": event.get("assistant_content", ""),
                        "agent_step": event.get("agent_step"),
                    }
                )
            elif event_type == "tool_done":
                yield _stream_event(
                    {
                        "type": "tool_done",
                        "conversation_id": safe_conversation_id,
                        "assistant_message_id": assistant_message_id,
                        "tool_messages": event.get("tool_messages", []),
                    }
                )
            elif event_type == "done":
                result = event.get("result")
                if not isinstance(result, dict):
                    raise ValueError("resume runtime finished without a result object")
                full_trace = _read_trace_full(result["trace_path"])
                clear_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id)
                _finish_run_message(
                    safe_conversation_id,
                    assistant_message_id,
                    run_id,
                    result,
                    full_trace,
                )
                if result.get("status") == "cancelled":
                    full_trace["memory_save"] = {
                        "requested": "database",
                        "status": "skipped",
                        "reason": "cancelled",
                        "conversation_id": safe_conversation_id,
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "storage": "sqlite",
                        "turn_memory": {"status": "skipped", "reason": "cancelled"},
                    }
                    _write_json_file(result["trace_path"], full_trace)
                else:
                    full_trace["memory_save"] = {
                        "requested": "database",
                        "status": "success",
                        "conversation_id": safe_conversation_id,
                        "user_message_id": user_message_id,
                        "assistant_message_id": assistant_message_id,
                        "storage": "sqlite",
                        "turn_memory": {
                            "status": "scheduled",
                            "mode": "background",
                            "reason": "memory reflection and layered memory writes run after the user response",
                        },
                    }
                    _write_json_file(result["trace_path"], full_trace)
                    _schedule_completed_turn_memory(
                        safe_conversation_id,
                        run_id,
                        user_message_id,
                        assistant_message_id,
                        raw_user_input,
                        result,
                        full_trace,
                        None,
                        output_dir,
                        result["trace_path"],
                    )
                tool_steps = list_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id)
                run_finished = True
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
    except GeneratorExit:
        if not run_finished:
            _mark_run_cancelled(assistant_message_id, streamed_answer or "".join(candidate_chunks))
        raise
    except Exception as exc:
        if cancel_event.is_set():
            cancelled_answer = streamed_answer or "".join(candidate_chunks)
            _mark_run_cancelled(assistant_message_id, cancelled_answer)
            yield _stream_event(
                {
                    "type": "done",
                    "conversation_id": safe_conversation_id,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "cancelled",
                    "final_answer": cancelled_answer.strip() or "已终止回答。",
                    "elapsed_ms": None,
                    "output_dir": str(output_dir),
                    "trace": {
                        "final_state": "failed",
                        "finish_reason": "user cancelled",
                        "memory_save": {"status": "skipped", "reason": "cancelled"},
                    },
                    "tool_steps": list_message_tool_steps(str(MEMORY_CONFIG), assistant_message_id),
                }
            )
            return
        _mark_run_failed(assistant_message_id, exc)
        yield _stream_event(
            {
                "type": "error",
                "conversation_id": safe_conversation_id,
                "assistant_message_id": assistant_message_id,
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        _clear_cancel_event(safe_conversation_id, cancel_event)


def _safe_stream_resume_agent(conversation_id: str, assistant_message_id: str) -> Iterator[str]:
    try:
        yield from _stream_resume_agent(conversation_id, assistant_message_id)
    except Exception as exc:
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
    normalized = request.model_copy(update={"conversation_id": _safe_conversation_id(request.conversation_id)})
    return UploadResponse(files=await asyncio.to_thread(save_uploaded_files, normalized))


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
            resumable=_message_resumable(message),
            tool_steps=list_message_tool_steps(str(MEMORY_CONFIG), message["id"]) if message["role"] == "assistant" else [],
            attachments=_message_attachments(message) if message["role"] == "user" else [],
        )
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    return ConversationDetail(conversation_id=conversation_id, messages=visible)


@app.get("/api/b2/skills")
def get_b2_skills(toolset: str | None = None) -> dict:
    try:
        _, config = load_tools_config(str(TOOLS_CONFIG))
        selected, enabled_tools = resolve_toolset(config, toolset)
        enabled = set(enabled_tools)
        tools = [
            _b2_skill_summary(name, get_tool_definition(config, name), name in enabled)
            for name in enabled_tools
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}
    workspace_roots = settings.get("workspace_roots") if isinstance(settings.get("workspace_roots"), dict) else {}
    return {
        "status": "success",
        "module": "B2",
        "toolset": selected,
        "tool_count": len(tools),
        "tools": tools,
        "toolsets": config.get("toolsets", {}),
        "settings": {
            "data_root": settings.get("data_root"),
            "default_workspace_root": settings.get("default_workspace_root"),
            "workspace_roots": sorted(workspace_roots.keys()),
        },
    }


@app.get("/api/b1/conversations/{conversation_id}/workspace")
def get_b1_workspace_checkpoint(conversation_id: str) -> dict:
    safe_conversation_id = _safe_conversation_id(conversation_id)
    metadata = checkpoint_metadata(safe_conversation_id)
    if not metadata["exists"]:
        return {
            "status": "missing",
            "module": "B1",
            "conversation_id": safe_conversation_id,
            "checkpoint": metadata,
            "workspace": None,
        }
    try:
        checkpoint = load_checkpoint(safe_conversation_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    runtime = checkpoint.get("runtime") if isinstance(checkpoint.get("runtime"), dict) else {}
    workspace = checkpoint.get("workspace") if isinstance(checkpoint.get("workspace"), dict) else None
    tools_schema = checkpoint.get("tools_schema")
    selected_memory = checkpoint.get("selected_memory")
    return {
        "status": "success",
        "module": "B1",
        "conversation_id": safe_conversation_id,
        "checkpoint": {
            **metadata,
            "schema_version": checkpoint.get("schema_version"),
            "status": checkpoint.get("status"),
            "stage": checkpoint.get("stage"),
            "mode": checkpoint.get("mode"),
            "execution_mode": checkpoint.get("execution_mode"),
            "output_dir": checkpoint.get("output_dir"),
        },
        "runtime": runtime,
        "selected_memory": selected_memory if isinstance(selected_memory, dict) else {},
        "tools_schema_count": len(tools_schema) if isinstance(tools_schema, list) else 0,
        "workspace": workspace,
    }


@app.post("/api/b2/skills/run")
def run_b2_skill_preview(request: B2SkillRunRequest) -> dict:
    skill_name = request.skill_name.strip()
    if not skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")
    try:
        _, config = load_tools_config(str(TOOLS_CONFIG))
        selected, enabled_tools = resolve_toolset(config, request.toolset)
        if skill_name not in enabled_tools:
            raise ValueError(f"skill is not available in {selected}: {skill_name}")
        get_tool_definition(config, skill_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = _now_stamp()
    output_dir = OUTPUT_ROOT / "b2_demo" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    result = run_b2_skill(
        skill_name,
        request.input,
        None,
        str(output_dir),
        str(TOOLS_CONFIG),
    )
    _attach_artifact_download_urls(result, output_dir)
    write_json(result, output_dir / "b2_skill_result.json")
    append_jsonl(
        {
            "timestamp": now_iso(),
            "module": "B2",
            "toolset": selected,
            "skill_name": skill_name,
            "status": result.get("status"),
            "latency_ms": result.get("latency_ms"),
            "result_path": str(output_dir / "b2_skill_result.json"),
        },
        output_dir / "b2_skill_run_log.jsonl",
    )
    return {
        "status": "success",
        "module": "B2",
        "toolset": selected,
        "skill_name": skill_name,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "result": result,
    }


@app.get("/api/b3/tools-schema")
def get_b3_schema(toolset: str | None = None) -> dict:
    try:
        _, config = load_tools_config(str(TOOLS_CONFIG))
        selected, enabled_tools = resolve_toolset(config, toolset)
        schema = get_b3_tools_schema(str(TOOLS_CONFIG), selected, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "success",
        "module": "B3",
        "toolset": selected,
        "tool_count": len(schema),
        "tools": enabled_tools,
        "tools_schema": schema,
        "toolsets": config.get("toolsets", {}),
    }


@app.post("/api/b3/tool-calls/preview")
def run_b3_tool_calls_preview(request: B3ToolCallsPreviewRequest) -> dict:
    tool_calls = _b3_tool_calls_from_request(request)
    if not tool_calls:
        raise HTTPException(status_code=400, detail="tool_calls is required")
    try:
        _, config = load_tools_config(str(TOOLS_CONFIG))
        selected, enabled_tools = resolve_toolset(config, request.toolset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = _now_stamp()
    output_dir = OUTPUT_ROOT / "b3_demo" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        schema = get_b3_tools_schema(str(TOOLS_CONFIG), selected, str(output_dir))
        tool_messages = execute_b3_tool_calls(tool_calls, str(TOOLS_CONFIG), selected, str(output_dir))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    results = []
    success_count = 0
    error_count = 0
    for index, message in enumerate(tool_messages):
        parsed = _parse_b3_tool_message(message)
        status = str(message.get("status") or (parsed or {}).get("status") or "unknown")
        if status == "success":
            success_count += 1
        elif status == "error":
            error_count += 1
        results.append(
            {
                "index": index,
                "tool_call_id": message.get("tool_call_id"),
                "name": message.get("name"),
                "status": status,
                "skill_result": parsed,
            }
        )

    return {
        "status": "success",
        "module": "B3",
        "toolset": selected,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "tool_count": len(enabled_tools),
        "tools": enabled_tools,
        "tools_schema": schema,
        "tool_calls": tool_calls,
        "tool_messages": tool_messages,
        "results": results,
        "summary": {
            "tool_call_count": len(tool_calls),
            "tool_message_count": len(tool_messages),
            "success_count": success_count,
            "error_count": error_count,
            "schema_count": len(schema),
            "artifacts": [
                artifact
                for result in results
                for artifact in (
                    (result.get("skill_result") or {}).get("artifacts", [])
                    if isinstance(result.get("skill_result"), dict)
                    and isinstance((result.get("skill_result") or {}).get("artifacts"), list)
                    else []
                )
                if isinstance(artifact, dict)
            ],
        },
    }


@app.get("/api/b5/conversations/{conversation_id}/memory")
def get_b5_conversation_memory(conversation_id: str) -> dict:
    conversation_id = _safe_conversation_id(conversation_id)
    init_conversation_db(str(MEMORY_CONFIG))
    snapshot = get_conversation_memory_snapshot(str(MEMORY_CONFIG), conversation_id)
    if snapshot.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="conversation not found")
    return snapshot


@app.post("/api/b5/conversations/{conversation_id}/recall-preview")
def run_b5_recall_preview(conversation_id: str, request: B5RecallPreviewRequest) -> dict:
    conversation_id = _safe_conversation_id(conversation_id)
    current_user_input = request.current_user_input.strip()
    if not current_user_input:
        raise HTTPException(status_code=400, detail="current_user_input is required")
    init_conversation_db(str(MEMORY_CONFIG))
    snapshot = get_conversation_memory_snapshot(str(MEMORY_CONFIG), conversation_id)
    if snapshot.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="conversation not found")
    try:
        history = list_conversation_history(str(MEMORY_CONFIG), conversation_id)
        result = prepare_workspace_memory_context(
            str(MEMORY_CONFIG),
            conversation_id,
            current_user_input,
            history,
            None,
            None,
            str(MODEL_CONFIG),
            None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    layered = result.get("layered_memory_context") if isinstance(result.get("layered_memory_context"), dict) else {}
    response = dict(result)
    response["current_user_input"] = current_user_input
    response["memory_messages"] = layered.get("memory_messages", [])
    response["recalled_blocks"] = layered.get("recalled_blocks", [])
    response["recalled_turns"] = layered.get("recalled_turns", [])
    response["source_messages"] = layered.get("source_messages", [])
    response["source_tool_steps"] = layered.get("source_tool_steps", [])
    response["vector_retrieval"] = layered.get("vector_retrieval")
    response["llm_rerank"] = layered.get("llm_rerank")
    response["retrieval_log"] = layered.get("retrieval_log")
    return response


@app.delete("/api/conversations/{conversation_id}", response_model=DeleteConversationResponse)
def delete_conversation(conversation_id: str) -> DeleteConversationResponse:
    conversation_id = _safe_conversation_id(conversation_id)
    init_conversation_db(str(MEMORY_CONFIG))
    record = delete_conversation_record(str(MEMORY_CONFIG), conversation_id)
    if not record.get("deleted"):
        raise HTTPException(status_code=404, detail="conversation not found")
    upload_dir_deleted = delete_child_directory(UPLOAD_ROOT, conversation_id)
    output_dir_deleted = delete_child_directory(OUTPUT_ROOT, conversation_id)
    delete_conversation_prompt(conversation_id, PROMPT_STORE_PATH)
    return DeleteConversationResponse(
        conversation_id=conversation_id,
        deleted=bool(record.get("deleted")),
        upload_dir_deleted=upload_dir_deleted,
        output_dir_deleted=output_dir_deleted,
    )


@app.get("/api/conversations/{conversation_id}/prompt", response_model=ConversationPromptResponse)
def get_conversation_system_prompt(conversation_id: str) -> ConversationPromptResponse:
    safe_conversation_id = _safe_conversation_id(conversation_id)
    prompt = get_conversation_prompt(
        safe_conversation_id,
        PROMPT_STORE_PATH,
        DEFAULT_SYSTEM_PROMPTS_PATH,
    )
    return ConversationPromptResponse(**prompt)


@app.get("/api/prompts/default", response_model=ConversationPromptResponse)
def get_default_system_prompt() -> ConversationPromptResponse:
    return ConversationPromptResponse(
        conversation_id="__default__",
        prompt_id="default_local_tool_agent",
        content=default_system_prompt(DEFAULT_SYSTEM_PROMPTS_PATH),
        default_content=default_system_prompt(DEFAULT_SYSTEM_PROMPTS_PATH),
        locked_default=True,
    )


@app.put("/api/conversations/{conversation_id}/prompt", response_model=ConversationPromptResponse)
def update_conversation_system_prompt(
    conversation_id: str,
    request: UpdateConversationPromptRequest,
) -> ConversationPromptResponse:
    safe_conversation_id = _safe_conversation_id(conversation_id)
    try:
        prompt = update_conversation_prompt(
            safe_conversation_id,
            request.content,
            PROMPT_STORE_PATH,
            DEFAULT_SYSTEM_PROMPTS_PATH,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConversationPromptResponse(**prompt)


@app.get("/api/messages/{message_id}/tool-steps")
def get_message_tool_steps(message_id: str) -> dict:
    init_conversation_db(str(MEMORY_CONFIG))
    return {"message_id": message_id, "tool_steps": list_message_tool_steps(str(MEMORY_CONFIG), message_id)}


@app.get("/api/artifacts/{conversation_id}/{run_id}/{relative_path:path}")
def download_generated_artifact(conversation_id: str, run_id: str, relative_path: str) -> FileResponse:
    safe_conversation_id = _safe_conversation_id(conversation_id)
    safe_run_id = _safe_run_id(run_id)
    artifact_path = _safe_generated_artifact_path(relative_path)
    output_root = OUTPUT_ROOT.resolve()
    run_dir = (OUTPUT_ROOT / safe_conversation_id / safe_run_id).resolve()
    try:
        run_dir.relative_to(output_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="artifact run directory is outside output root") from exc
    target = (run_dir / artifact_path).resolve()
    try:
        target.relative_to(run_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="artifact path is outside run directory") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(target, filename=target.name)


@app.post("/api/conversations/{conversation_id}/cancel")
def cancel_conversation_run(conversation_id: str) -> dict:
    safe_conversation_id = _safe_conversation_id(conversation_id)
    return {
        "conversation_id": safe_conversation_id,
        "cancel_requested": _request_cancel(safe_conversation_id),
    }


@app.post("/api/conversations/{conversation_id}/messages/{assistant_message_id}/resume")
def resume_conversation_run(conversation_id: str, assistant_message_id: str) -> StreamingResponse:
    return StreamingResponse(
        _safe_stream_resume_agent(conversation_id, assistant_message_id),
        media_type="application/x-ndjson; charset=utf-8",
    )


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
        _safe_stream_agent(request),
        media_type="application/x-ndjson; charset=utf-8",
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
