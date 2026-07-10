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
    path = Path(trace_path)
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as file:
        trace = json.load(file)
    if not isinstance(trace, dict):
        return {}
    return {
        "tool_rounds_used": trace.get("tool_rounds_used"),
        "llm_call_count": trace.get("llm_call_count"),
        "memory_save": trace.get("memory_save"),
        "warnings": trace.get("warnings", []),
        "error": trace.get("error"),
    }


def _build_runtime_payload(request: RunRequest, conversation_id: str) -> dict:
    return {
        "conversation_id": conversation_id,
        "user_input": request.user_input.strip(),
        "system_prompt_path": SYSTEM_PROMPT_PATH,
        "selected_memory_ids": request.selected_memory_ids,
        "use_global_memory": request.use_global_memory,
        "toolset": request.toolset,
        "max_turns": request.max_turns,
        "save_memory": request.save_memory,
    }


def _call_agent(request: RunRequest) -> RunResponse:
    conversation_id = _safe_conversation_id(request.conversation_id)
    runtime_payload = _build_runtime_payload(request, conversation_id)
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
    return RunResponse(
        conversation_id=result["conversation_id"],
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
