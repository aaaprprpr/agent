from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterator

from common.io_utils import append_jsonl, write_json, write_text
from common.logging_utils import now_iso
from common.schemas import make_ai_message

from .b1_llm_bridge import generate_ai_message, generate_json_object, stream_ai_message
from .b1_prompting import (
    _workspace_answer_messages,
    _workspace_observation_messages,
    _workspace_planning_messages,
    _workspace_stage_failure_answer_messages,
    _workspace_tool_messages,
)
from .b1_workspace import (
    _agent_step_from_observation,
    _agent_step_from_plan,
    _as_string_list,
    _merge_unique,
    _record_no_tool_action,
    _record_stage,
    _workspace_from_runtime,
)


def _write_runtime_outputs(
    runtime: dict,
    execution_mode: str,
    mode: str,
    output_dir: Path,
    started: float,
    selected_memory: dict,
    messages: list[dict],
    all_tool_messages: list[dict],
    final_answer: str,
    status: str,
    tool_rounds: int,
    llm_calls: int,
    turns: list[dict],
    final_control: dict | None,
    warnings: list[str],
    terminal_error: dict | None,
    memory_file: Path | None,
    workspace: dict | None = None,
    streaming: bool = False,
) -> dict:
    write_json(messages, output_dir / "messages.json")
    if execution_mode == "integrated":
        write_json(all_tool_messages, output_dir / "tool_messages.json")
    write_text(final_answer.strip() + "\n", output_dir / "final_answer.md")
    memory_save = {"requested": runtime["save_memory"], "status": "not_requested"}
    if status != "success" and runtime["save_memory"] != "none":
        memory_save = {"requested": runtime["save_memory"], "status": "skipped", "reason": status}
    trace = {
        "conversation_id": runtime["conversation_id"],
        "execution_mode": execution_mode,
        "status": status,
        "toolset": runtime["toolset"],
        "tool_rounds_used": tool_rounds,
        "llm_call_count": llm_calls,
        "final_state": final_control["state"] if final_control else "failed",
        "finish_reason": final_control["reason"] if final_control else "",
        "turns": turns,
        "final_answer_path": "final_answer.md",
        "memory_save": memory_save,
        "warnings": warnings,
        "error": terminal_error,
    }
    if workspace is not None:
        trace["workspace"] = workspace
    write_json(trace, output_dir / "trace.json")

    saved_memory = None
    if execution_mode == "integrated" and runtime["save_memory"] != "none" and trace["status"] == "success":
        try:
            from b5_memory import save_memory

            saved_memory = save_memory(
                str(memory_file),
                runtime["conversation_id"],
                runtime["save_memory"],
                str(output_dir / "messages.json"),
                str(output_dir / "trace.json"),
                str(output_dir / "final_answer.md"),
                str(output_dir),
            )
            trace["memory_save"] = {"requested": runtime["save_memory"], "status": "success"}
        except Exception as exc:
            trace["memory_save"] = {
                "requested": runtime["save_memory"],
                "status": "error",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            trace["warnings"].append("memory save failed")
            if trace["status"] == "success":
                trace["status"] = "partial"
        write_json(trace, output_dir / "trace.json")

    result = {
        "conversation_id": runtime["conversation_id"],
        "execution_mode": execution_mode,
        "status": trace["status"],
        "final_answer": final_answer,
        "messages_path": str(output_dir / "messages.json"),
        "trace_path": str(output_dir / "trace.json"),
        "final_answer_path": str(output_dir / "final_answer.md"),
        "selected_memory": selected_memory,
        "saved_memory": saved_memory,
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
    }
    if execution_mode == "integrated":
        log_record = {
            "timestamp": now_iso(),
            "conversation_id": runtime["conversation_id"],
            "execution_mode": execution_mode,
            "status": trace["status"],
            "llm_mode": mode,
            "tool_rounds_used": tool_rounds,
            "llm_call_count": llm_calls,
            "elapsed_ms": result["elapsed_ms"],
        }
        if streaming:
            log_record["streaming"] = True
        append_jsonl(log_record, output_dir / "runtime_log.jsonl")
    return result


def _has_successful_tool_result(tool_messages: list[dict] | None) -> bool:
    if not tool_messages:
        return False
    for message in tool_messages:
        if isinstance(message, dict) and message.get("status") == "success":
            return True
    return False


def _workspace_parse_failure(
    runtime: dict,
    execution_mode: str,
    system_prompt: str,
    model_file: Path,
    mode: str,
    output_dir: Path,
    started: float,
    selected_memory: dict,
    messages: list[dict],
    turns: list[dict],
    llm_calls: int,
    warnings: list[str],
    memory_file: Path | None,
    workspace: dict,
    stage: str,
    error: dict | None,
    raw_text: str | None = None,
    all_tool_messages: list[dict] | None = None,
    tool_rounds: int = 0,
    streaming: bool = False,
) -> dict:
    parse_error = {
        "type": "LLMStageParseError",
        "message": f"runtime stage failed to parse: {stage}",
        "stage": stage,
        "cause": error,
    }
    warnings.append(f"workspace stage parse failed: {stage}")
    _record_stage(
        workspace,
        "stage_parse_error",
        {
            "stage": stage,
            "error": error,
            "raw_text": raw_text,
        },
    )
    llm_calls += 1
    answer_messages = _workspace_stage_failure_answer_messages(system_prompt, workspace, stage, error, raw_text)
    if stage == "observation" and _has_successful_tool_result(all_tool_messages or workspace["tools"].get("results", [])):
        answer_messages = _workspace_answer_messages(system_prompt, workspace)
    final_result = generate_ai_message(
        str(model_file),
        answer_messages,
        [],
        mode,
        str(output_dir / "llm_calls"),
        f"workspace_{llm_calls:03d}_{stage}_failure_answering",
        prompt_ready=True,
    )
    if not isinstance(final_result, dict) or not isinstance(final_result.get("ai_message"), dict):
        raise ValueError("B4 result must contain an ai_message object")
    final_ai_message = final_result["ai_message"]
    final_answer = final_ai_message.get("content", "")
    final_control = final_ai_message.get("control")
    status = "success"
    terminal_error = None
    if final_result.get("status") != "success":
        status = "llm_parse_error"
        terminal_error = {
            **parse_error,
            "final_answer_error": final_result.get("error"),
            "llm_call_index": llm_calls,
        }
    elif final_control and final_control.get("state") == "failed":
        status = "agent_failed"
        terminal_error = {
            **parse_error,
            "final_reason": final_control.get("reason", ""),
            "llm_call_index": llm_calls,
        }
    workspace["final"] = {"answer": final_answer, "status": status}
    _record_stage(
        workspace,
        "answering",
        {
            "content": final_answer,
            "control": final_control,
            "agent_step": final_ai_message.get("agent_step"),
        },
    )
    messages.append(final_ai_message)
    turns.append(
        {
            "turn_index": llm_calls,
            "ai_message": final_ai_message,
            "llm_prompt_messages": final_result.get("prompt_messages"),
            "llm_status": final_result.get("status"),
            "llm_error": final_result.get("error"),
            "tool_messages": [],
            "control": final_control,
            "agent_step": final_ai_message.get("agent_step"),
            "latency_ms": None,
        }
    )
    return _write_runtime_outputs(
        runtime,
        execution_mode,
        mode,
        output_dir,
        started,
        selected_memory,
        messages,
        all_tool_messages or [],
        final_answer,
        status,
        tool_rounds,
        llm_calls,
        turns,
        final_control,
        warnings,
        terminal_error,
        memory_file,
        workspace,
        streaming,
    )


def _cancel_requested(should_cancel: Callable[[], bool] | None) -> bool:
    return bool(should_cancel and should_cancel())


def _workspace_cancelled_result(
    runtime: dict,
    execution_mode: str,
    mode: str,
    output_dir: Path,
    started: float,
    selected_memory: dict,
    messages: list[dict],
    all_tool_messages: list[dict],
    partial_answer: str,
    tool_rounds: int,
    llm_calls: int,
    turns: list[dict],
    warnings: list[str],
    memory_file: Path | None,
    workspace: dict,
) -> dict:
    final_answer = partial_answer.strip() or "已终止回答。"
    final_control = {
        "state": "failed",
        "action": "finish",
        "reason": "user cancelled",
    }
    workspace["final"] = {"answer": final_answer, "status": "cancelled"}
    _record_stage(
        workspace,
        "cancelled",
        {
            "content": final_answer,
            "control": final_control,
        },
    )
    return _write_runtime_outputs(
        runtime,
        execution_mode,
        mode,
        output_dir,
        started,
        selected_memory,
        messages,
        all_tool_messages,
        final_answer,
        "cancelled",
        tool_rounds,
        llm_calls,
        turns,
        final_control,
        warnings,
        None,
        memory_file,
        workspace,
        streaming=True,
    )


def _run_workspace(
    runtime: dict,
    execution_mode: str,
    system_prompt: str,
    selected_memory: dict,
    tools_schema: list[dict],
    tools_file: Path,
    memory_file: Path,
    model_file: Path,
    mode: str,
    output_dir: Path,
    started: float,
) -> dict:
    from b3_tool_layer import execute_tool_calls

    workspace = _workspace_from_runtime(runtime, selected_memory)
    current_user_message = {"role": "user", "content": runtime["user_input"]}
    if runtime["input_images"]:
        current_user_message["images"] = runtime["input_images"]
    messages = [
        {"role": "system", "content": system_prompt},
        *workspace["input"].get("history_messages", []),
        current_user_message,
    ]
    turns = []
    all_tool_messages = []
    warnings = []
    if selected_memory.get("status") in {"partial", "error"}:
        warnings.append("memory selection completed with errors")
    layered_status = workspace.get("memory", {}).get("layered", {}).get("status")
    if layered_status == "error":
        warnings.append("layered memory context failed")
    llm_calls = 0
    tool_rounds = 0
    status = "success"
    terminal_error = None
    final_control = None

    llm_calls += 1
    plan_result = generate_json_object(
        str(model_file),
        _workspace_planning_messages(system_prompt, runtime, selected_memory, tools_schema),
        mode,
        str(output_dir / "llm_calls"),
        f"workspace_{llm_calls:03d}_planning",
        prompt_ready=True,
    )
    if plan_result.get("status") != "success" or not isinstance(plan_result.get("json"), dict):
        return _workspace_parse_failure(
            runtime,
            execution_mode,
            system_prompt,
            model_file,
            mode,
            output_dir,
            started,
            selected_memory,
            messages,
            turns,
            llm_calls,
            warnings,
            memory_file,
            workspace,
            "planning",
            plan_result.get("error"),
            plan_result.get("raw_text"),
        )
    plan = plan_result["json"]
    workspace["task"].update(
        {
            "user_goal": str(plan.get("user_goal") or runtime["user_input"]),
            "requirements": _as_string_list(plan.get("requirements")),
            "plan": str(plan.get("plan") or ""),
            "stage": str(plan.get("next_stage") or "answering"),
            "reason": str(plan.get("reason") or ""),
        }
    )
    _merge_unique(workspace["draft"]["known_facts"], plan.get("known_facts"))
    _merge_unique(workspace["draft"]["missing_info"], plan.get("missing_info"))
    _record_stage(workspace, "planning", plan)
    plan_ai_message = make_ai_message(
        str(plan.get("plan") or plan.get("reason") or "已完成任务规划。"),
        [],
        {"state": "completed", "action": "finish", "reason": "workspace planning"},
        _agent_step_from_plan(plan),
    )
    turns.append(
        {
            "turn_index": llm_calls,
            "ai_message": plan_ai_message,
            "llm_prompt_messages": plan_result.get("prompt_messages"),
            "llm_status": plan_result.get("status"),
            "llm_error": plan_result.get("error"),
            "tool_messages": [],
            "control": plan_ai_message.get("control"),
            "agent_step": plan_ai_message.get("agent_step"),
            "latency_ms": None,
        }
    )

    next_stage = workspace["task"]["stage"]
    while next_stage == "tool_calling":
        llm_calls += 1
        turn_start = perf_counter()
        tool_result = generate_ai_message(
            str(model_file),
            _workspace_tool_messages(system_prompt, workspace, tools_schema),
            [],
            mode,
            str(output_dir / "llm_calls"),
            f"workspace_{llm_calls:03d}_tool_calling",
            prompt_ready=True,
        )
        if not isinstance(tool_result, dict) or not isinstance(tool_result.get("ai_message"), dict):
            raise ValueError("B4 result must contain an ai_message object")
        ai_message = tool_result["ai_message"]
        llm_status = tool_result.get("status")
        llm_error = tool_result.get("error")
        turn = {
            "turn_index": llm_calls,
            "ai_message": ai_message,
            "llm_prompt_messages": tool_result.get("prompt_messages"),
            "llm_status": llm_status,
            "llm_error": llm_error,
            "tool_messages": [],
            "control": ai_message.get("control"),
            "agent_step": ai_message.get("agent_step"),
            "latency_ms": None,
        }
        messages.append(ai_message)
        if llm_status != "success":
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
            return _workspace_parse_failure(
                runtime,
                execution_mode,
                system_prompt,
                model_file,
                mode,
                output_dir,
                started,
                selected_memory,
                messages,
                turns,
                llm_calls,
                warnings,
                memory_file,
                workspace,
                "tool_calling",
                llm_error,
                tool_result.get("raw_text"),
                all_tool_messages,
                tool_rounds,
            )
        tool_calls = ai_message.get("tool_calls", [])
        workspace["tools"]["last_tool_intent"] = ai_message.get("content", "")
        _record_stage(
            workspace,
            "tool_calling",
            {
                "assistant_content": ai_message.get("content", ""),
                "agent_step": ai_message.get("agent_step"),
                "tool_calls": tool_calls,
            },
        )
        if not tool_calls:
            _record_no_tool_action(workspace, ai_message)
            turns.append(turn)
            next_stage = workspace["task"]["stage"]
            continue
        tool_messages = execute_tool_calls(
            tool_calls,
            str(tools_file),
            runtime["toolset"],
            str(output_dir),
        )
        tool_rounds += 1
        messages.extend(tool_messages)
        all_tool_messages.extend(tool_messages)
        workspace["tools"]["calls"].extend(deepcopy(tool_calls))
        workspace["tools"]["results"].extend(deepcopy(tool_messages))
        turn["tool_messages"] = tool_messages
        turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
        turns.append(turn)

        llm_calls += 1
        observation_result = generate_json_object(
            str(model_file),
            _workspace_observation_messages(system_prompt, workspace, tool_messages),
            mode,
            str(output_dir / "llm_calls"),
            f"workspace_{llm_calls:03d}_observation",
            prompt_ready=True,
        )
        if observation_result.get("status") != "success" or not isinstance(observation_result.get("json"), dict):
            return _workspace_parse_failure(
                runtime,
                execution_mode,
                system_prompt,
                model_file,
                mode,
                output_dir,
                started,
                selected_memory,
                messages,
                turns,
                llm_calls,
                warnings,
                memory_file,
                workspace,
                "observation",
                observation_result.get("error"),
                observation_result.get("raw_text"),
                all_tool_messages,
                tool_rounds,
            )
        observation = observation_result["json"]
        _merge_unique(workspace["tools"]["accepted_evidence"], observation.get("accepted_evidence"))
        _merge_unique(workspace["tools"]["rejected_evidence"], observation.get("rejected_evidence"))
        _merge_unique(workspace["draft"]["known_facts"], observation.get("known_facts"))
        _merge_unique(workspace["draft"]["missing_info"], observation.get("missing_info"))
        workspace["tools"]["observations"].append(str(observation.get("observation") or ""))
        next_stage = str(observation.get("next_stage") or "answering")
        workspace["task"]["stage"] = next_stage
        workspace["task"]["reason"] = str(observation.get("reason") or "")
        _record_stage(workspace, "observation", observation)
        observation_ai_message = make_ai_message(
            str(observation.get("observation") or observation.get("reason") or "已观察工具结果。"),
            [],
            {"state": "completed", "action": "finish", "reason": "workspace observation"},
            _agent_step_from_observation(observation),
        )
        messages.append(observation_ai_message)
        turns.append(
            {
                "turn_index": llm_calls,
                "ai_message": observation_ai_message,
                "llm_prompt_messages": observation_result.get("prompt_messages"),
                "llm_status": observation_result.get("status"),
                "llm_error": observation_result.get("error"),
                "tool_messages": [],
                "control": observation_ai_message.get("control"),
                "agent_step": observation_ai_message.get("agent_step"),
                "latency_ms": None,
            }
        )

    llm_calls += 1
    final_result = generate_ai_message(
        str(model_file),
        _workspace_answer_messages(system_prompt, workspace),
        [],
        mode,
        str(output_dir / "llm_calls"),
        f"workspace_{llm_calls:03d}_answering",
        prompt_ready=True,
    )
    if not isinstance(final_result, dict) or not isinstance(final_result.get("ai_message"), dict):
        raise ValueError("B4 result must contain an ai_message object")
    final_ai_message = final_result["ai_message"]
    final_answer = final_ai_message.get("content", "")
    final_control = final_ai_message.get("control")
    if final_result.get("status") != "success":
        status = "llm_parse_error"
        terminal_error = {
            "type": "LLMParseError",
            "message": "B4 failed to parse final answer output.",
            "llm_call_index": llm_calls,
            "cause": final_result.get("error"),
        }
    elif final_control and final_control.get("state") == "failed":
        status = "agent_failed"
        terminal_error = {
            "type": "AgentDeclaredFailure",
            "message": final_control.get("reason", ""),
            "llm_call_index": llm_calls,
        }
    workspace["final"] = {"answer": final_answer, "status": status}
    _record_stage(
        workspace,
        "answering",
        {
            "content": final_answer,
            "control": final_control,
            "agent_step": final_ai_message.get("agent_step"),
        },
    )
    messages.append(final_ai_message)
    turns.append(
        {
            "turn_index": llm_calls,
            "ai_message": final_ai_message,
            "llm_prompt_messages": final_result.get("prompt_messages"),
            "llm_status": final_result.get("status"),
            "llm_error": final_result.get("error"),
            "tool_messages": [],
            "control": final_ai_message.get("control"),
            "agent_step": final_ai_message.get("agent_step"),
            "latency_ms": None,
        }
    )
    print(f"content: {final_answer}")
    return _write_runtime_outputs(
        runtime,
        execution_mode,
        mode,
        output_dir,
        started,
        selected_memory,
        messages,
        all_tool_messages,
        final_answer,
        status,
        tool_rounds,
        llm_calls,
        turns,
        final_control,
        warnings,
        terminal_error,
        memory_file,
        workspace,
    )


def _run_workspace_stream(
    runtime: dict,
    execution_mode: str,
    system_prompt: str,
    selected_memory: dict,
    tools_schema: list[dict],
    tools_file: Path,
    memory_file: Path,
    model_file: Path,
    mode: str,
    output_dir: Path,
    started: float,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[dict]:
    from b3_tool_layer import execute_tool_calls

    workspace = _workspace_from_runtime(runtime, selected_memory)
    current_user_message = {"role": "user", "content": runtime["user_input"]}
    if runtime["input_images"]:
        current_user_message["images"] = runtime["input_images"]
    messages = [
        {"role": "system", "content": system_prompt},
        *workspace["input"].get("history_messages", []),
        current_user_message,
    ]
    turns = []
    all_tool_messages = []
    warnings = []
    if selected_memory.get("status") in {"partial", "error"}:
        warnings.append("memory selection completed with errors")
    layered_status = workspace.get("memory", {}).get("layered", {}).get("status")
    if layered_status == "error":
        warnings.append("layered memory context failed")
    llm_calls = 0
    tool_rounds = 0
    status = "success"
    terminal_error = None
    final_control = None

    def cancelled_done(partial_answer: str = "") -> dict:
        return {
            "type": "done",
            "result": _workspace_cancelled_result(
                runtime,
                execution_mode,
                mode,
                output_dir,
                started,
                selected_memory,
                messages,
                all_tool_messages,
                partial_answer,
                tool_rounds,
                llm_calls,
                turns,
                warnings,
                memory_file,
                workspace,
            ),
        }

    if _cancel_requested(should_cancel):
        yield cancelled_done()
        return

    llm_calls += 1
    plan_result = generate_json_object(
        str(model_file),
        _workspace_planning_messages(system_prompt, runtime, selected_memory, tools_schema),
        mode,
        str(output_dir / "llm_calls"),
        f"workspace_{llm_calls:03d}_planning",
        prompt_ready=True,
    )
    if plan_result.get("status") != "success" or not isinstance(plan_result.get("json"), dict):
        result = _workspace_parse_failure(
            runtime,
            execution_mode,
            system_prompt,
            model_file,
            mode,
            output_dir,
            started,
            selected_memory,
            messages,
            turns,
            llm_calls,
            warnings,
            memory_file,
            workspace,
            "planning",
            plan_result.get("error"),
            plan_result.get("raw_text"),
            streaming=True,
        )
        yield {"type": "done", "result": result}
        return
    if _cancel_requested(should_cancel):
        yield cancelled_done()
        return
    plan = plan_result["json"]
    workspace["task"].update(
        {
            "user_goal": str(plan.get("user_goal") or runtime["user_input"]),
            "requirements": _as_string_list(plan.get("requirements")),
            "plan": str(plan.get("plan") or ""),
            "stage": str(plan.get("next_stage") or "answering"),
            "reason": str(plan.get("reason") or ""),
        }
    )
    _merge_unique(workspace["draft"]["known_facts"], plan.get("known_facts"))
    _merge_unique(workspace["draft"]["missing_info"], plan.get("missing_info"))
    _record_stage(workspace, "planning", plan)
    plan_ai_message = make_ai_message(
        str(plan.get("plan") or plan.get("reason") or "已完成任务规划。"),
        [],
        {"state": "completed", "action": "finish", "reason": "workspace planning"},
        _agent_step_from_plan(plan),
    )
    turns.append(
        {
            "turn_index": llm_calls,
            "ai_message": plan_ai_message,
            "llm_prompt_messages": plan_result.get("prompt_messages"),
            "llm_status": plan_result.get("status"),
            "llm_error": plan_result.get("error"),
            "tool_messages": [],
            "control": plan_ai_message.get("control"),
            "agent_step": plan_ai_message.get("agent_step"),
            "latency_ms": None,
        }
    )
    yield {
        "type": "state",
        "state": "planning",
        "action": "workspace_plan",
        "reason": workspace["task"].get("reason", ""),
        "agent_step": plan_ai_message.get("agent_step"),
        "llm_call_index": llm_calls,
    }

    next_stage = workspace["task"]["stage"]
    while next_stage == "tool_calling":
        if _cancel_requested(should_cancel):
            yield cancelled_done()
            return
        llm_calls += 1
        turn_start = perf_counter()
        tool_result = generate_ai_message(
            str(model_file),
            _workspace_tool_messages(system_prompt, workspace, tools_schema),
            [],
            mode,
            str(output_dir / "llm_calls"),
            f"workspace_{llm_calls:03d}_tool_calling",
            prompt_ready=True,
        )
        if not isinstance(tool_result, dict) or not isinstance(tool_result.get("ai_message"), dict):
            raise ValueError("B4 result must contain an ai_message object")
        ai_message = tool_result["ai_message"]
        llm_status = tool_result.get("status")
        llm_error = tool_result.get("error")
        turn = {
            "turn_index": llm_calls,
            "ai_message": ai_message,
            "llm_prompt_messages": tool_result.get("prompt_messages"),
            "llm_status": llm_status,
            "llm_error": llm_error,
            "tool_messages": [],
            "control": ai_message.get("control"),
            "agent_step": ai_message.get("agent_step"),
            "latency_ms": None,
        }
        messages.append(ai_message)
        if llm_status != "success":
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
            result = _workspace_parse_failure(
                runtime,
                execution_mode,
                system_prompt,
                model_file,
                mode,
                output_dir,
                started,
                selected_memory,
                messages,
                turns,
                llm_calls,
                warnings,
                memory_file,
                workspace,
                "tool_calling",
                llm_error,
                tool_result.get("raw_text"),
                all_tool_messages,
                tool_rounds,
                streaming=True,
            )
            yield {"type": "done", "result": result}
            return
        control = ai_message.get("control", {})
        yield {"type": "state", **control, "agent_step": ai_message.get("agent_step"), "llm_call_index": llm_calls}
        if _cancel_requested(should_cancel):
            yield cancelled_done()
            return
        tool_calls = ai_message.get("tool_calls", [])
        workspace["tools"]["last_tool_intent"] = ai_message.get("content", "")
        _record_stage(
            workspace,
            "tool_calling",
            {
                "assistant_content": ai_message.get("content", ""),
                "agent_step": ai_message.get("agent_step"),
                "tool_calls": tool_calls,
            },
        )
        if not tool_calls:
            _record_no_tool_action(workspace, ai_message)
            turns.append(turn)
            next_stage = workspace["task"]["stage"]
            continue
        yield {
            "type": "tool_start",
            "tool_calls": tool_calls,
            "assistant_content": ai_message.get("content", ""),
            "agent_step": ai_message.get("agent_step"),
            "llm_call_index": llm_calls,
        }
        if _cancel_requested(should_cancel):
            yield cancelled_done()
            return
        tool_messages = execute_tool_calls(
            tool_calls,
            str(tools_file),
            runtime["toolset"],
            str(output_dir),
        )
        tool_rounds += 1
        messages.extend(tool_messages)
        all_tool_messages.extend(tool_messages)
        workspace["tools"]["calls"].extend(deepcopy(tool_calls))
        workspace["tools"]["results"].extend(deepcopy(tool_messages))
        turn["tool_messages"] = tool_messages
        turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
        turns.append(turn)
        yield {"type": "tool_done", "tool_messages": tool_messages, "llm_call_index": llm_calls}
        if _cancel_requested(should_cancel):
            yield cancelled_done()
            return

        llm_calls += 1
        observation_result = generate_json_object(
            str(model_file),
            _workspace_observation_messages(system_prompt, workspace, tool_messages),
            mode,
            str(output_dir / "llm_calls"),
            f"workspace_{llm_calls:03d}_observation",
            prompt_ready=True,
        )
        if observation_result.get("status") != "success" or not isinstance(observation_result.get("json"), dict):
            result = _workspace_parse_failure(
                runtime,
                execution_mode,
                system_prompt,
                model_file,
                mode,
                output_dir,
                started,
                selected_memory,
                messages,
                turns,
                llm_calls,
                warnings,
                memory_file,
                workspace,
                "observation",
                observation_result.get("error"),
                observation_result.get("raw_text"),
                all_tool_messages,
                tool_rounds,
                streaming=True,
            )
            yield {"type": "done", "result": result}
            return
        if _cancel_requested(should_cancel):
            yield cancelled_done()
            return
        observation = observation_result["json"]
        _merge_unique(workspace["tools"]["accepted_evidence"], observation.get("accepted_evidence"))
        _merge_unique(workspace["tools"]["rejected_evidence"], observation.get("rejected_evidence"))
        _merge_unique(workspace["draft"]["known_facts"], observation.get("known_facts"))
        _merge_unique(workspace["draft"]["missing_info"], observation.get("missing_info"))
        workspace["tools"]["observations"].append(str(observation.get("observation") or ""))
        next_stage = str(observation.get("next_stage") or "answering")
        workspace["task"]["stage"] = next_stage
        workspace["task"]["reason"] = str(observation.get("reason") or "")
        _record_stage(workspace, "observation", observation)
        observation_ai_message = make_ai_message(
            str(observation.get("observation") or observation.get("reason") or "已观察工具结果。"),
            [],
            {"state": "completed", "action": "finish", "reason": "workspace observation"},
            _agent_step_from_observation(observation),
        )
        messages.append(observation_ai_message)
        turns.append(
            {
                "turn_index": llm_calls,
                "ai_message": observation_ai_message,
                "llm_prompt_messages": observation_result.get("prompt_messages"),
                "llm_status": observation_result.get("status"),
                "llm_error": observation_result.get("error"),
                "tool_messages": [],
                "control": observation_ai_message.get("control"),
                "agent_step": observation_ai_message.get("agent_step"),
                "latency_ms": None,
            }
        )
        yield {
            "type": "state",
            "state": "observing",
            "action": "workspace_observe",
            "reason": workspace["task"].get("reason", ""),
            "agent_step": observation_ai_message.get("agent_step"),
            "llm_call_index": llm_calls,
        }

    if _cancel_requested(should_cancel):
        yield cancelled_done()
        return

    llm_calls += 1
    final_result = None
    final_chunks: list[str] = []
    for event in stream_ai_message(
        str(model_file),
        _workspace_answer_messages(system_prompt, workspace),
        [],
        mode,
        str(output_dir / "llm_calls"),
        f"workspace_{llm_calls:03d}_answering",
        prompt_ready=True,
    ):
        if _cancel_requested(should_cancel):
            yield cancelled_done("".join(final_chunks))
            return
        if not isinstance(event, dict):
            continue
        if event.get("type") == "delta":
            text = str(event.get("text", ""))
            final_chunks.append(text)
            yield {"type": "delta", "text": text, "llm_call_index": llm_calls}
        elif event.get("type") == "done":
            final_result = event.get("result")
    if _cancel_requested(should_cancel):
        yield cancelled_done("".join(final_chunks))
        return
    if not isinstance(final_result, dict) or not isinstance(final_result.get("ai_message"), dict):
        raise ValueError("B4 stream result must contain an ai_message object")
    final_ai_message = final_result["ai_message"]
    final_answer = final_ai_message.get("content", "")
    final_control = final_ai_message.get("control")
    if final_result.get("status") != "success":
        status = "llm_parse_error"
        terminal_error = {
            "type": "LLMParseError",
            "message": "B4 failed to parse final answer output.",
            "llm_call_index": llm_calls,
            "cause": final_result.get("error"),
        }
    elif final_control and final_control.get("state") == "failed":
        status = "agent_failed"
        terminal_error = {
            "type": "AgentDeclaredFailure",
            "message": final_control.get("reason", ""),
            "llm_call_index": llm_calls,
        }
    workspace["final"] = {"answer": final_answer, "status": status}
    _record_stage(
        workspace,
        "answering",
        {
            "content": final_answer,
            "control": final_control,
            "agent_step": final_ai_message.get("agent_step"),
        },
    )
    messages.append(final_ai_message)
    turns.append(
        {
            "turn_index": llm_calls,
            "ai_message": final_ai_message,
            "llm_prompt_messages": final_result.get("prompt_messages"),
            "llm_status": final_result.get("status"),
            "llm_error": final_result.get("error"),
            "tool_messages": [],
            "control": final_ai_message.get("control"),
            "agent_step": final_ai_message.get("agent_step"),
            "latency_ms": None,
        }
    )
    yield {"type": "state", **(final_control or {}), "agent_step": final_ai_message.get("agent_step"), "llm_call_index": llm_calls}
    result = _write_runtime_outputs(
        runtime,
        execution_mode,
        mode,
        output_dir,
        started,
        selected_memory,
        messages,
        all_tool_messages,
        final_answer,
        status,
        tool_rounds,
        llm_calls,
        turns,
        final_control,
        warnings,
        terminal_error,
        memory_file,
        workspace,
        streaming=True,
    )
    yield {"type": "done", "result": result}

