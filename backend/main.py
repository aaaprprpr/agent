from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from b1_agent_runtime import run as run_agent_runtime  # noqa: E402
from b5_memory import (  # noqa: E402
    append_conversation_message,
    init_conversation_db,
    list_conversation_messages,
    record_conversation_tool_step,
    upsert_conversation_record,
)


HOST = "127.0.0.1"
PORT = 8020
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "backend_runs"
TOOLS_CONFIG = PROJECT_ROOT / "configs" / "tools.yaml"
MEMORY_CONFIG = PROJECT_ROOT / "configs" / "memory.yaml"
MODEL_CONFIG = PROJECT_ROOT / "configs" / "model.yaml"
RUNTIME_BASE = PROJECT_ROOT / "data" / "__frontend_runtime__.json"
SYSTEM_PROMPT_PATH = "../prompts/local_tool_agent.txt"


class RunRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    conversation_id: str | None = None
    selected_memory_ids: list[str] = Field(default_factory=list)
    use_global_memory: bool = False
    toolset: str = "basic_tools"
    max_turns: int = Field(default=3, ge=1, le=20)
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


app = FastAPI(title="Agent Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _history_context(history: list[dict]) -> str:
    visible = [message for message in history if message.get("role") in {"user", "assistant", "system"}]
    if not visible:
        return ""
    role_labels = {"system": "系统", "user": "用户", "assistant": "助手"}
    lines = [
        "以下是当前对话的完整历史记录，请作为上下文参考。回答时只回复最后的“当前用户输入”。",
        "<conversation_history>",
    ]
    for message in visible:
        role = role_labels.get(str(message.get("role")), str(message.get("role")))
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    lines.append("</conversation_history>")
    return "\n".join(lines)


def _contextual_user_input(history: list[dict], user_input: str) -> str:
    context = _history_context(history)
    if not context:
        return user_input
    return f"{context}\n\n当前用户输入：\n{user_input}"


def _extract_tool_steps(trace: dict) -> list[dict]:
    steps = []
    for turn in trace.get("turns", []):
        if not isinstance(turn, dict):
            continue
        for tool_message in turn.get("tool_messages", []):
            if not isinstance(tool_message, dict):
                continue
            raw_content = tool_message.get("content")
            try:
                parsed = json.loads(raw_content) if isinstance(raw_content, str) else {}
            except json.JSONDecodeError:
                parsed = {}
            steps.append(
                {
                    "tool_call_id": tool_message.get("tool_call_id"),
                    "tool_name": tool_message.get("name") or parsed.get("skill_name") or "unknown",
                    "input_data": parsed.get("input"),
                    "output_data": parsed.get("output"),
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
        "memory_save": trace.get("memory_save"),
    }


def _build_runtime_payload(request: RunRequest, conversation_id: str, user_input: str) -> dict:
    # Web chat uses SQLite as the primary memory store. Legacy markdown memory
    # remains available through selected_memory_ids/use_global_memory, but B1
    # must not save markdown snapshots for normal web turns.
    selected_memory_ids = request.selected_memory_ids
    use_global_memory = request.use_global_memory
    return {
        "conversation_id": conversation_id,
        "user_input": user_input,
        "system_prompt_path": SYSTEM_PROMPT_PATH,
        "selected_memory_ids": selected_memory_ids,
        "use_global_memory": use_global_memory,
        "toolset": request.toolset,
        "max_turns": request.max_turns,
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


def _record_run_messages(
    conversation_id: str,
    run_id: str,
    raw_user_input: str,
    result: dict,
    trace: dict,
    history: list[dict],
) -> tuple[str, str]:
    user_record = append_conversation_message(
        str(MEMORY_CONFIG),
        conversation_id,
        "user",
        raw_user_input,
        run_id=run_id,
        is_trivial=_is_trivial_text(raw_user_input),
    )
    assistant_record = append_conversation_message(
        str(MEMORY_CONFIG),
        conversation_id,
        "assistant",
        result["final_answer"] or "[empty response]",
        run_id=run_id,
        metadata=_assistant_metadata(result, trace),
    )
    _record_tool_steps(conversation_id, assistant_record["message_id"], run_id, trace)
    title = _history_title(history, raw_user_input)
    upsert_conversation_record(
        str(MEMORY_CONFIG),
        conversation_id,
        title,
        is_trivial=_is_trivial_conversation(history, raw_user_input),
        trivial_reason="only trivial user messages" if _is_trivial_conversation(history, raw_user_input) else None,
    )
    return user_record["message_id"], assistant_record["message_id"]


def _call_agent(request: RunRequest) -> RunResponse:
    conversation_id = _safe_conversation_id(request.conversation_id)
    raw_user_input = request.user_input.strip()
    init_conversation_db(str(MEMORY_CONFIG))
    history = list_conversation_messages(str(MEMORY_CONFIG), conversation_id)
    title = _history_title(history, raw_user_input)
    upsert_conversation_record(
        str(MEMORY_CONFIG),
        conversation_id,
        title,
        is_trivial=_is_trivial_conversation(history, raw_user_input),
        trivial_reason="only trivial user messages" if _is_trivial_conversation(history, raw_user_input) else None,
    )
    runtime_payload = _build_runtime_payload(request, conversation_id, raw_user_input)
    run_id = _now_stamp()
    output_dir = OUTPUT_ROOT / conversation_id / run_id
    result = run_agent_runtime(
        runtime_payload,
        str(TOOLS_CONFIG),
        str(MEMORY_CONFIG),
        str(MODEL_CONFIG),
        str(output_dir),
        request.llm_mode,
        RUNTIME_BASE,
    )
    full_trace = _read_trace_full(result["trace_path"])
    user_message_id, assistant_message_id = _record_run_messages(
        conversation_id,
        run_id,
        raw_user_input,
        result,
        full_trace,
        history,
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


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "agent_runtime": "b1",
        "model_config": str(MODEL_CONFIG),
    }


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


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
