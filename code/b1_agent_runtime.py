from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Iterator

from common.io_utils import append_jsonl, read_json, read_text, read_yaml, write_json, write_text
from common.logging_utils import now_iso
from common.path_utils import resolve_cli_path, resolve_from_file
from common.schemas import make_ai_message, normalize_history_messages, validate_ai_message


def _validate_runtime_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("runtime_input.json must contain an object")
    execution_mode = payload.setdefault("execution_mode", "integrated")
    if execution_mode not in {"integrated", "fixture"}:
        raise ValueError("execution_mode must be integrated or fixture")
    required = ["conversation_id", "user_input", "system_prompt_path", "toolset", "save_memory"]
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"runtime input missing: {', '.join(missing)}")
    if not isinstance(payload["conversation_id"], str) or not payload["conversation_id"]:
        raise ValueError("conversation_id must be a non-empty string")
    if not isinstance(payload["user_input"], str) or not payload["user_input"].strip():
        raise ValueError("user_input must be a non-empty string")
    if payload["save_memory"] not in {"none", "conversation", "global"}:
        raise ValueError("save_memory must be none, conversation, or global")
    payload["history_messages"] = normalize_history_messages(payload.get("history_messages", []))
    input_images = payload.setdefault("input_images", [])
    if not isinstance(input_images, list) or not all(
        isinstance(item, str) and item.startswith("data:image/") for item in input_images
    ):
        raise ValueError("input_images must be an array of image data URLs")
    if execution_mode == "fixture":
        fixtures = payload.get("fixtures")
        if not isinstance(fixtures, dict):
            raise ValueError("fixture mode requires a fixtures object")
        required_fixtures = [
            "selected_memory_path",
            "tools_schema_path",
            "ai_messages_path",
            "tool_messages_path",
        ]
        missing_fixtures = [field for field in required_fixtures if not isinstance(fixtures.get(field), str)]
        if missing_fixtures:
            raise ValueError(f"fixtures missing paths: {', '.join(missing_fixtures)}")
        if payload["save_memory"] != "none":
            raise ValueError("fixture mode requires save_memory=none")
    else:
        selected_ids = payload.setdefault("selected_memory_ids", [])
        if not isinstance(selected_ids, list) or not all(isinstance(item, str) for item in selected_ids):
            raise ValueError("selected_memory_ids must be a list of strings")
        payload.setdefault("use_global_memory", False)
        if not isinstance(payload["use_global_memory"], bool):
            raise ValueError("use_global_memory must be boolean")
    return payload


def _default_llm_mode(model_config: Path) -> str:
    config = read_yaml(model_config)
    return config.get("runtime", {}).get("default_mode", "mock")


def build_llm_prompt_messages(messages: list[dict], tools_schema: list[dict]) -> list[dict]:
    """Build the complete model-facing prompt for one Agent loop step.

    B1 owns message flow. B4 may keep a standalone fallback, but the integrated
    Agent path should disclose tools and protocol here before calling B4.
    """
    if not isinstance(tools_schema, list):
        raise ValueError("tools_schema must be an array")
    prompt_messages = deepcopy(messages)
    protocol_instruction = (
        "本段是模型输出协议，不是用户任务内容。\n"
        "你必须只返回一个 JSON 对象，不能输出 JSON 之外的任何文字、Markdown、代码块或反引号。\n"
        '第一个输出字符必须是 "{"，最后一个输出字符必须是 "}"。\n\n'
        "JSON 顶层键必须且只能包含：\n"
        "- content：字符串。写给用户看的自然语言内容；请求工具时可简要说明下一步，但不能包含工具调用 JSON。\n"
        "- tool_calls：数组。需要调用工具时填写；不调用工具或结束时必须为 []。\n"
        "- control：对象，且只能包含 state、action、reason。\n\n"
        "- agent_step：对象，描述本轮 ReAct 中间状态，且只能包含 phase、plan、observation、known_facts、missing_info、next_step。\n\n"
        "control 取值规则：\n"
        "- 请求工具：control.action 为 call_tools，control.state 为 acting 或 replanning，tool_calls 不能为空。\n"
        "- 正常结束：control.action 为 finish，control.state 为 completed，tool_calls 必须为 []。\n"
        "- 无法继续：control.action 为 finish，control.state 为 failed，tool_calls 必须为 []，reason 必须写明具体原因。\n\n"
        "agent_step 取值规则：\n"
        "- phase 使用 plan、action、observation 或 final。\n"
        "- 第一次理解任务时，写清 plan；请求工具时，phase 通常为 action，并写明本次工具调用目的。\n"
        "- 收到工具消息后，必须先写 observation：概括工具返回了什么、是否足够、还缺什么。\n"
        "- known_facts 只写已经由上下文或工具确认的事实；missing_info 写仍缺少的信息；next_step 写下一步决策。\n"
        "- 如果工具结果足以回答，phase 使用 final，content 给出最终回答；不要只说“已获得工具结果”。\n\n"
        "工具决策规则：\n"
        "- 需要运行时、本地、上传文件、外部、搜索、计算等信息时，从本轮可用工具结构中选择匹配工具。\n"
        "- 工具结构中存在匹配能力时，不要声称该能力不可用。\n"
        "- 最新消息如果是工具结果，应先判断结果是否足够；足够则完成，不足则继续规划或失败结束。\n"
        "- 工具结果之后结束时，不要重复之前的工具调用。\n\n"
        "示例，完成任务：\n"
        '{"content":"这是最终回答。","tool_calls":[],"control":{"state":"completed","action":"finish","reason":"任务已完成"},'
        '"agent_step":{"phase":"final","plan":"已完成必要步骤","observation":"已有足够信息回答用户",'
        '"known_facts":["示例事实"],"missing_info":[],"next_step":"给出最终回答"}}\n\n'
        "示例，请求工具：\n"
        '{"content":"我先读取相关文件。","tool_calls":[{"id":"call_001","name":"file_reader",'
        '"args":{"path":"docs/agent_intro.txt","max_chars":2000}}],"control":'
        '{"state":"acting","action":"call_tools","reason":"需要读取文件内容"},'
        '"agent_step":{"phase":"action","plan":"先获取文件原文，再总结要点","observation":"尚未获得文件内容",'
        '"known_facts":[],"missing_info":["文件内容"],"next_step":"调用 file_reader"}}\n\n'
        "示例，无法继续：\n"
        '{"content":"继续处理前，我需要用户提供具体文件名。","tool_calls":[],"control":'
        '{"state":"failed","action":"finish","reason":"缺少必要文件名"},'
        '"agent_step":{"phase":"final","plan":"需要读取文件但缺少路径","observation":"当前信息不足",'
        '"known_facts":[],"missing_info":["具体文件名"],"next_step":"请求用户补充信息"}}'
    )
    output_reminder = (
        "只输出符合协议的 JSON 对象。"
        '顶层键只能是 "content"、"tool_calls"、"control"、"agent_step"。'
        "请求工具时使用 call_tools；结束时使用 finish 且 tool_calls 为 []。"
        "收到工具结果后必须先在 agent_step.observation 中观察结果，再决定继续工具或最终回答。"
        "不要在 JSON 外输出任何文字，不要把工具调用写进 content。"
    )
    tool_disclosure = (
        "\n\n本轮可用工具结构如下。仅在任务需要工具时使用，工具名和参数必须来自该结构：\n"
        + json.dumps(tools_schema, ensure_ascii=False)
        + "\n"
        + protocol_instruction
    )
    if prompt_messages and prompt_messages[0].get("role") == "system":
        prompt_messages[0]["content"] += tool_disclosure
    else:
        prompt_messages.insert(0, {"role": "system", "content": tool_disclosure.strip()})

    for message in reversed(prompt_messages):
        if message.get("role") == "user":
            message["content"] += "\n\n" + output_reminder
            break
    if prompt_messages[-1].get("role") == "tool":
        prompt_messages.append(
            {
                "role": "user",
                "content": (
                    output_reminder
                    + " 最新工具消息已经包含工具结果。必须在 agent_step.observation 中概括工具结果、有效事实和缺口；"
                    "足够则 completed 并给最终回答，不足则 replanning 继续调用工具，无法继续则 failed 并说明原因。"
                ),
            }
        )
    return prompt_messages


def generate_ai_message(*args, **kwargs) -> dict:
    """Lazy B4 proxy retained as the integrated-mode injection point."""
    from b4_local_agent_llm import generate_ai_message as b4_generate_ai_message

    return b4_generate_ai_message(*args, **kwargs)


def stream_ai_message(*args, **kwargs) -> Iterator[dict]:
    """Lazy B4 streaming proxy used only by the opt-in streaming runtime."""
    from b4_local_agent_llm import stream_ai_message as b4_stream_ai_message

    return b4_stream_ai_message(*args, **kwargs)


def generate_json_object(*args, **kwargs) -> dict:
    """Lazy B4 proxy for B1-owned workspace planning stages."""
    from b4_local_agent_llm import generate_json_object as b4_generate_json_object

    return b4_generate_json_object(*args, **kwargs)


def _json_block(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_briefs(tools_schema: list[dict]) -> list[dict]:
    briefs = []
    for tool in tools_schema:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        entry = {
            "name": tool.get("name") or function.get("name"),
            "description": tool.get("description") or function.get("description", ""),
        }
        parameters = tool.get("parameters") or function.get("parameters")
        if isinstance(parameters, dict):
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                entry["args"] = list(properties)
        briefs.append(entry)
    return briefs


def _memory_overview(selected_memory: dict) -> dict:
    if not isinstance(selected_memory, dict):
        return {"status": "unknown"}
    docs = selected_memory.get("selected_memory_docs")
    return {
        "status": selected_memory.get("status"),
        "selected_memory_count": len(docs) if isinstance(docs, list) else 0,
        "total_chars": selected_memory.get("total_chars"),
        "truncated": selected_memory.get("truncated"),
        "errors": selected_memory.get("errors", []),
        "note": "legacy markdown memory is not injected into the active workspace context",
    }


def _stage_messages(system_prompt: str, stage_name: str, instruction: str, payload: dict) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\n你现在处在 B1 运行时工作区的一个内部阶段。"
                "只完成本阶段的信息整理或决策，不直接替用户执行其他阶段。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"阶段：{stage_name}\n"
                f"{instruction}\n\n"
                "工作区输入如下：\n"
                f"{_json_block(payload)}\n\n"
                "只能输出一个 JSON 对象，不能输出 Markdown、代码块或 JSON 之外的文字。"
            ),
        },
    ]


def _workspace_planning_messages(
    system_prompt: str,
    runtime: dict,
    selected_memory: dict,
    tools_schema: list[dict],
) -> list[dict]:
    payload = {
        "user_input": runtime["user_input"],
        "input_images_count": len(runtime.get("input_images", [])),
        "history_messages": runtime.get("history_messages", []),
        "selected_memory": _memory_overview(selected_memory),
        "available_tools": _tool_briefs(tools_schema),
    }
    return _stage_messages(
        system_prompt,
        "planning",
        (
            "理解用户本轮任务，整理目标、约束、已知事实和缺失信息。"
            "如果需要工具，next_stage 写 tool_calling；如果可以直接回答，写 answering；"
            "如果无法推进，写 failed。不要调用工具。"
            "JSON 键：user_goal、requirements、plan、known_facts、missing_info、next_stage、reason。"
        ),
        payload,
    )


def _workspace_tool_messages(
    system_prompt: str,
    workspace: dict,
    tools_schema: list[dict],
) -> list[dict]:
    payload = {
        "user_input": workspace["input"]["user_input"],
        "history_messages": workspace["input"].get("history_messages", []),
        "task": workspace["task"],
        "known_facts": workspace["draft"].get("known_facts", []),
        "missing_info": workspace["draft"].get("missing_info", []),
        "accepted_evidence": workspace["tools"].get("accepted_evidence", []),
        "rejected_evidence": workspace["tools"].get("rejected_evidence", []),
        "previous_tool_attempts": _tool_attempts_summary(workspace),
        "previous_no_action_outputs": workspace["tools"].get("no_action_outputs", []),
        "observations": workspace["tools"].get("observations", []),
        "available_tools_schema": tools_schema,
    }
    return [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\n你现在是 B1 工作区的工具动作规划阶段。"
                "进入本阶段表示当前任务需要一个可执行工具动作。"
                "必须根据用户目标、缺失信息、已有工具尝试和工具 schema 决定下一步。"
                "不要输出最终答案，不要把工具结果当成已经存在的信息。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据工作区状态选择下一步工具动作。\n"
                "只输出 AIMessage JSON 对象，顶层键只能是 content、tool_calls、control、agent_step。\n"
                "正常情况必须返回至少一个 tool_call：control.action=call_tools，tool_calls 填写要调用的工具。\n"
                "如果已有失败尝试，必须根据失败原因调整工具、参数或路径；不要无变化地重复同一调用。\n"
                "如果确认没有任何可用工具能推进任务，才允许返回 control.action=finish、control.state=failed、tool_calls=[]，并在 reason 写清能力缺口。\n"
                "不能用 content 代替工具调用；content 只写极短工具前说明，不能写最终答案、完整代码、文件内容或完成声明。\n\n"
                f"工作区状态如下：\n{_json_block(payload)}"
            ),
        },
    ]


def _workspace_observation_messages(
    system_prompt: str,
    workspace: dict,
    tool_messages: list[dict],
) -> list[dict]:
    payload = {
        "user_input": workspace["input"]["user_input"],
        "task": workspace["task"],
        "last_tool_intent": workspace["tools"].get("last_tool_intent", ""),
        "last_tool_messages": tool_messages,
        "previous_tool_attempts": _tool_attempts_summary(workspace),
        "rejected_evidence_before": workspace["tools"].get("rejected_evidence", []),
        "accepted_evidence_before": workspace["tools"].get("accepted_evidence", []),
        "known_facts_before": workspace["draft"].get("known_facts", []),
        "missing_info_before": workspace["draft"].get("missing_info", []),
    }
    return _stage_messages(
        system_prompt,
        "observation",
        (
            "观察刚刚的工具结果。判断这些结果是否满足用户任务，而不只是满足工具调用目的。"
            "必须以 ToolMessage 的 status、output、error 为依据：status=success 只表示工具执行成功，不等于任务完成；"
            "status=error 的结果不能作为事实证据，只能作为失败原因。"
            "把可用于最终回答的内容放入 accepted_evidence 和 known_facts；"
            "无效、错误或偏题的信息放入 rejected_evidence；仍缺的信息放入 missing_info。"
            "如果失败原因已经表明没有工具能力或目标文件不存在，应主动结束到 answering/failed，而不是反复调用同一工具。"
            "下一步由你决定：需要继续工具写 tool_calling；足以回答写 answering；无法推进写 failed。"
            "JSON 键：observation、accepted_evidence、rejected_evidence、known_facts、missing_info、next_stage、reason。"
        ),
        payload,
    )


def _workspace_answer_messages(system_prompt: str, workspace: dict) -> list[dict]:
    payload = {
        "user_input": workspace["input"]["user_input"],
        "history_messages": workspace["input"].get("history_messages", []),
        "selected_memory": workspace["memory"],
        "task": workspace["task"],
        "accepted_evidence": workspace["tools"].get("accepted_evidence", []),
        "rejected_evidence": workspace["tools"].get("rejected_evidence", []),
        "known_facts": workspace["draft"].get("known_facts", []),
        "missing_info": workspace["draft"].get("missing_info", []),
        "tool_attempts": _tool_attempts_summary(workspace),
        "observations": workspace["tools"].get("observations", []),
    }
    return [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\n你现在是 B1 工作区的最终回答阶段。"
                "只面向用户输出最终答案。不要泄露工具 JSON、内部阶段名、工作区结构或调度过程。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据工作区中的用户任务、可用证据和已知事实生成最终回答。\n"
                "如果信息不足，直接说明缺口；不要编造。"
                "只有 accepted_evidence 或成功工具结果中明确出现的信息，才能声明为已经完成。"
                "没有成功的 file_writer 结果时，不得说文件已生成；没有下载接口或下载工具时，不得说已经可以直接下载；"
                "没有成功 file_reader/search/calculator 等结果时，不得声称已经读取、搜索或计算完成。\n"
                "只输出 AIMessage JSON 对象，顶层键只能是 content、tool_calls、control、agent_step。\n"
                "必须满足：tool_calls=[]，control.action=finish，control.state 为 completed 或 failed，"
                "agent_step.phase=final。\n\n"
                f"工作区状态如下：\n{_json_block(payload)}"
            ),
        },
    ]


def _workspace_from_runtime(runtime: dict, selected_memory: dict) -> dict:
    return {
        "input": {
            "conversation_id": runtime["conversation_id"],
            "user_input": runtime["user_input"],
            "history_messages": runtime.get("history_messages", []),
            "input_images_count": len(runtime.get("input_images", [])),
        },
        "memory": _memory_overview(selected_memory),
        "task": {
            "user_goal": "",
            "requirements": [],
            "plan": "",
            "stage": "planning",
            "reason": "",
        },
        "tools": {
            "calls": [],
            "results": [],
            "observations": [],
            "accepted_evidence": [],
            "rejected_evidence": [],
            "no_action_outputs": [],
            "last_tool_intent": "",
        },
        "draft": {
            "known_facts": [],
            "missing_info": [],
        },
        "final": {
            "answer": "",
            "status": "",
        },
        "trace": [],
    }


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text or text in {"无", "无。", "none", "None", "null"}:
            return []
        return [text]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _merge_unique(target: list[str], values: object) -> None:
    for value in _as_string_list(values):
        if value not in target:
            target.append(value)


def _compact_for_workspace(value: object, limit: int = 900) -> object:
    if isinstance(value, str):
        text = value.strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "..."
    if isinstance(value, list):
        return [_compact_for_workspace(item, max(160, limit // 3)) for item in value[:6]]
    if isinstance(value, dict):
        compact = {}
        for key, item in value.items():
            if key in {"content", "text"}:
                compact[key] = _compact_for_workspace(item, limit)
            elif key in {"generated_file_path", "relative_output_path", "filename", "file_type", "status", "error"}:
                compact[key] = _compact_for_workspace(item, limit)
            elif isinstance(item, (str, int, float, bool)) or item is None:
                compact[key] = item
        return compact
    return value


def _tool_message_payload(message: dict) -> dict:
    raw_content = message.get("content")
    try:
        parsed = json.loads(raw_content) if isinstance(raw_content, str) else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_attempts_summary(workspace: dict) -> list[dict]:
    calls = workspace["tools"].get("calls", [])
    results = workspace["tools"].get("results", [])
    summaries = []
    for index, message in enumerate(results):
        if not isinstance(message, dict):
            continue
        call = calls[index] if index < len(calls) and isinstance(calls[index], dict) else {}
        parsed = _tool_message_payload(message)
        output = parsed.get("output")
        error = parsed.get("error")
        summaries.append(
            {
                "index": index + 1,
                "tool_name": message.get("name") or call.get("name") or parsed.get("skill_name"),
                "tool_call_id": message.get("tool_call_id") or call.get("id"),
                "args": call.get("args") or parsed.get("input"),
                "status": message.get("status") or parsed.get("status"),
                "output_summary": _compact_for_workspace(output),
                "error": _compact_for_workspace(error),
            }
        )
    return summaries


def _record_no_tool_action(workspace: dict, ai_message: dict) -> None:
    content = ai_message.get("content", "").strip()
    note = "工具动作阶段没有返回 tool_calls，因此本阶段没有执行任何工具。"
    if content:
        note += " 该阶段输出的自然语言或草稿不能作为工具结果或完成证据。"
    workspace["tools"]["no_action_outputs"].append(
        {
            "content": content,
            "control": ai_message.get("control"),
            "agent_step": ai_message.get("agent_step"),
        }
    )
    _merge_unique(workspace["tools"]["rejected_evidence"], [note])
    _merge_unique(workspace["draft"]["missing_info"], ["缺少本轮工具动作实际执行后的结果。"])
    workspace["task"]["stage"] = "answering"
    workspace["task"]["reason"] = note


def _record_stage(workspace: dict, phase: str, payload: dict) -> None:
    workspace["trace"].append({"phase": phase, "payload": deepcopy(payload)})


def _agent_step_from_plan(plan: dict) -> dict:
    return {
        "phase": "plan",
        "plan": str(plan.get("plan") or ""),
        "observation": str(plan.get("reason") or ""),
        "known_facts": _as_string_list(plan.get("known_facts")),
        "missing_info": _as_string_list(plan.get("missing_info")),
        "next_step": str(plan.get("next_stage") or ""),
    }


def _agent_step_from_observation(observation: dict) -> dict:
    return {
        "phase": "observation",
        "plan": str(observation.get("reason") or ""),
        "observation": str(observation.get("observation") or ""),
        "known_facts": _as_string_list(observation.get("known_facts")),
        "missing_info": _as_string_list(observation.get("missing_info")),
        "next_step": str(observation.get("next_stage") or ""),
    }


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


def _workspace_parse_failure(
    runtime: dict,
    execution_mode: str,
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
    all_tool_messages: list[dict] | None = None,
    tool_rounds: int = 0,
    streaming: bool = False,
) -> dict:
    final_answer = "模型内部阶段输出解析失败，未生成有效回答。"
    terminal_error = {
        "type": "LLMStageParseError",
        "message": f"B1 workspace stage failed to parse: {stage}",
        "stage": stage,
        "cause": error,
    }
    final_control = {
        "state": "failed",
        "action": "finish",
        "reason": "workspace stage parse failed",
    }
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
        "llm_parse_error",
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
        *runtime["history_messages"],
        current_user_message,
    ]
    turns = []
    all_tool_messages = []
    warnings = []
    if selected_memory.get("status") in {"partial", "error"}:
        warnings.append("memory selection completed with errors")
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
            final_answer = ai_message.get("content", "").strip() or "模型工具规划输出解析失败，未生成有效回答。"
            status = "llm_parse_error"
            terminal_error = {
                "type": "LLMParseError",
                "message": "B4 failed to parse tool planning output.",
                "llm_call_index": llm_calls,
                "cause": llm_error,
            }
            final_control = {"state": "failed", "action": "finish", "reason": "tool planning parse failed"}
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
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
) -> Iterator[dict]:
    from b3_tool_layer import execute_tool_calls

    workspace = _workspace_from_runtime(runtime, selected_memory)
    current_user_message = {"role": "user", "content": runtime["user_input"]}
    if runtime["input_images"]:
        current_user_message["images"] = runtime["input_images"]
    messages = [
        {"role": "system", "content": system_prompt},
        *runtime["history_messages"],
        current_user_message,
    ]
    turns = []
    all_tool_messages = []
    warnings = []
    if selected_memory.get("status") in {"partial", "error"}:
        warnings.append("memory selection completed with errors")
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
        result = _workspace_parse_failure(
            runtime,
            execution_mode,
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
            streaming=True,
        )
        yield {"type": "done", "result": result}
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
            final_answer = ai_message.get("content", "").strip() or "模型工具规划输出解析失败，未生成有效回答。"
            status = "llm_parse_error"
            terminal_error = {
                "type": "LLMParseError",
                "message": "B4 failed to parse tool planning output.",
                "llm_call_index": llm_calls,
                "cause": llm_error,
            }
            final_control = {"state": "failed", "action": "finish", "reason": "tool planning parse failed"}
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
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
            return
        control = ai_message.get("control", {})
        yield {"type": "state", **control, "agent_step": ai_message.get("agent_step"), "llm_call_index": llm_calls}
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
                all_tool_messages,
                tool_rounds,
                streaming=True,
            )
            yield {"type": "done", "result": result}
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

    llm_calls += 1
    final_result = None
    for event in stream_ai_message(
        str(model_file),
        _workspace_answer_messages(system_prompt, workspace),
        [],
        mode,
        str(output_dir / "llm_calls"),
        f"workspace_{llm_calls:03d}_answering",
        prompt_ready=True,
    ):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "delta":
            yield {"type": "delta", "text": str(event.get("text", "")), "llm_call_index": llm_calls}
        elif event.get("type") == "done":
            final_result = event.get("result")
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

# just for inspection
def _load_fixture_inputs(input_file: Path, runtime: dict) -> dict:
    fixtures = runtime["fixtures"]
    selected_memory = read_json(resolve_from_file(fixtures["selected_memory_path"], input_file))
    tools_schema = read_json(resolve_from_file(fixtures["tools_schema_path"], input_file))
    ai_messages = read_json(resolve_from_file(fixtures["ai_messages_path"], input_file))
    tool_messages = read_json(resolve_from_file(fixtures["tool_messages_path"], input_file))
    if not isinstance(selected_memory, dict):
        raise ValueError("preset memory must be a JSON object")
    if not isinstance(tools_schema, list):
        raise ValueError("preset tools_schema must be a JSON array")
    if not isinstance(ai_messages, list) or not ai_messages:
        raise ValueError("preset AI messages must be a non-empty JSON array")
    if not isinstance(tool_messages, dict):
        raise ValueError("preset ToolMessages must be an object keyed by tool_call_id")
    for message in ai_messages:
        validate_ai_message(message)
    return {
        "selected_memory": selected_memory,
        "tools_schema": tools_schema,
        "ai_messages": ai_messages,
        "tool_messages": tool_messages,
    }


def _fixture_tool_messages(tool_calls: list[dict], preset_messages: dict) -> list[dict]:
    results = []
    for call in tool_calls:
        call_id = call.get("id")
        message = deepcopy(preset_messages.get(call_id))
        if not isinstance(message, dict):
            raise ValueError(f"fixture ToolMessage does not exist for tool_call_id: {call_id}")
        if message.get("role") != "tool" or message.get("tool_call_id") != call_id:
            raise ValueError(f"invalid fixture ToolMessage for tool_call_id: {call_id}")
        if message.get("name") != call.get("name"):
            raise ValueError(f"fixture ToolMessage name does not match call: {call_id}")
        results.append(message)
    return results


def _runtime_base_file(runtime_base: str | Path | None) -> Path:
    if runtime_base is None:
        return (Path(__file__).resolve().parents[1] / "data" / "__runtime_payload__.json").resolve()
    base = Path(runtime_base).expanduser().resolve()
    if base.is_dir():
        return (base / "__runtime_payload__.json").resolve()
    return base


def run(
    runtime_input: dict,
    tools_config: str | None,
    memory_config: str | None,
    model_config: str | None,
    outdir: str,
    llm_mode: str | None = None,
    runtime_base: str | Path | None = None,
) -> dict:
    """Run the Agent loop from an in-memory runtime payload.

    runtime_base is only used as the reference file for resolving relative paths
    inside the payload, such as system_prompt_path and fixture paths.
    """
    started = perf_counter()
    base_file = _runtime_base_file(runtime_base)
    output_dir = Path(outdir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime = _validate_runtime_input(deepcopy(runtime_input))
    print(f"user_input: {runtime['user_input']}")
    execution_mode = runtime["execution_mode"]
    prompt_path = resolve_from_file(runtime["system_prompt_path"], base_file)
    system_prompt = read_text(prompt_path).strip()
    fixture_data = None
    tools_file = memory_file = model_file = None
    if execution_mode == "fixture":
        fixture_data = _load_fixture_inputs(base_file, runtime)
        selected_memory = fixture_data["selected_memory"]
        tools_schema = fixture_data["tools_schema"]
        mode = "fixture"
    else:
        if not tools_config or not memory_config or not model_config:
            raise ValueError("integrated mode requires tools_config, memory_config, and model_config")
        from b3_tool_layer import execute_tool_calls, get_tools_schema
        from b5_memory import load_memory

        tools_file = Path(tools_config).resolve()
        memory_file = Path(memory_config).resolve()
        model_file = Path(model_config).resolve()
        selected_memory = load_memory(
            str(memory_file),
            runtime["selected_memory_ids"],
            runtime["use_global_memory"],
            runtime["user_input"],
            str(output_dir),
        )
        tools_schema = get_tools_schema(str(tools_file), runtime["toolset"], str(output_dir))
        mode = llm_mode or _default_llm_mode(model_file)
    if execution_mode == "integrated" and mode == "prompt_json":
        return _run_workspace(
            runtime,
            execution_mode,
            system_prompt,
            selected_memory,
            tools_schema,
            tools_file,
            memory_file,
            model_file,
            mode,
            output_dir,
            started,
        )
    current_user_message = {"role": "user", "content": runtime["user_input"]}
    if runtime["input_images"]:
        current_user_message["images"] = runtime["input_images"]
    messages = [
        {"role": "system", "content": system_prompt},
        *runtime["history_messages"],
        current_user_message,
    ]
    tool_rounds = 0
    llm_calls = 0
    turns = []
    all_tool_messages = []
    final_answer = ""
    status = "success"
    terminal_error = None
    warnings = []
    final_control = None
    if selected_memory.get("status") in {"partial", "error"}:
        warnings.append("memory selection completed with errors")

    while True:
        llm_calls += 1
        turn_start = perf_counter()
        if execution_mode == "fixture":
            if llm_calls > len(fixture_data["ai_messages"]):
                raise ValueError("fixture AIMessage sequence ended before a final answer")
            ai_message = deepcopy(fixture_data["ai_messages"][llm_calls - 1])
            llm_status = "success"
            llm_error = None
            llm_prompt_messages = None
        else:
            llm_input_messages = build_llm_prompt_messages(messages, tools_schema)
            llm_result = generate_ai_message(
                str(model_file),
                llm_input_messages,
                [],
                mode,
                str(output_dir / "llm_calls"),
                f"llm_call_{llm_calls:03d}",
                prompt_ready=True,
            )
            if not isinstance(llm_result, dict) or not isinstance(llm_result.get("ai_message"), dict):
                raise ValueError("B4 result must contain an ai_message object")
            ai_message = llm_result["ai_message"]
            llm_status = llm_result.get("status")
            llm_error = llm_result.get("error")
            llm_prompt_messages = llm_result.get("prompt_messages")
        messages.append(ai_message)
        turn = {
            "turn_index": llm_calls,
            "ai_message": ai_message,
            "llm_prompt_messages": llm_prompt_messages,
            "llm_status": llm_status,
            "llm_error": llm_error,
            "tool_messages": [],
            "control": ai_message.get("control"),
            "agent_step": ai_message.get("agent_step"),
            "latency_ms": None,
        }
        if llm_status != "success":
            final_answer = ai_message.get("content", "").strip() or "模型输出解析失败，未生成有效回答。"
            status = "llm_parse_error"
            terminal_error = {
                "type": "LLMParseError",
                "message": "B4 failed to parse the model output as a valid AIMessage JSON object.",
                "llm_call_index": llm_calls,
                "cause": llm_error,
            }
            final_control = {
                "state": "failed",
                "action": "finish",
                "reason": "LLM output could not be parsed",
            }
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
            break
        control = ai_message["control"]
        tool_calls = ai_message.get("tool_calls", [])
        if control["action"] == "finish":
            final_control = control
            final_answer = ai_message["content"]
            print(f"content: {final_answer}")
            if control["state"] == "failed":
                status = "agent_failed"
                terminal_error = {
                    "type": "AgentDeclaredFailure",
                    "message": control["reason"],
                    "llm_call_index": llm_calls,
                }
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
            break
        if execution_mode == "fixture":
            tool_messages = _fixture_tool_messages(
                tool_calls,
                fixture_data["tool_messages"],
            )
        else:
            tool_messages = execute_tool_calls(
                tool_calls,
                str(tools_file),
                runtime["toolset"],
                str(output_dir),
            )
        tool_rounds += 1
        messages.extend(tool_messages)
        all_tool_messages.extend(tool_messages)
        turn["tool_messages"] = tool_messages
        turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
        turns.append(turn)

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
        append_jsonl(
            {
                "timestamp": now_iso(),
                "conversation_id": runtime["conversation_id"],
                "execution_mode": execution_mode,
                "status": trace["status"],
                "llm_mode": mode,
                "tool_rounds_used": tool_rounds,
                "llm_call_count": llm_calls,
                "elapsed_ms": result["elapsed_ms"],
            },
            output_dir / "runtime_log.jsonl",
        )
    return result


def run_stream(
    runtime_input: dict,
    tools_config: str | None,
    memory_config: str | None,
    model_config: str | None,
    outdir: str,
    llm_mode: str | None = None,
    runtime_base: str | Path | None = None,
) -> Iterator[dict]:
    """Run the Agent loop and yield UI-safe streaming events.

    This is an additive entry point. The existing run()/run_agent() path remains
    the stable non-streaming module interface.
    """
    started = perf_counter()
    base_file = _runtime_base_file(runtime_base)
    output_dir = Path(outdir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime = _validate_runtime_input(deepcopy(runtime_input))
    execution_mode = runtime["execution_mode"]
    prompt_path = resolve_from_file(runtime["system_prompt_path"], base_file)
    system_prompt = read_text(prompt_path).strip()
    fixture_data = None
    tools_file = memory_file = model_file = None
    if execution_mode == "fixture":
        fixture_data = _load_fixture_inputs(base_file, runtime)
        selected_memory = fixture_data["selected_memory"]
        tools_schema = fixture_data["tools_schema"]
        mode = "fixture"
    else:
        if not tools_config or not memory_config or not model_config:
            raise ValueError("integrated mode requires tools_config, memory_config, and model_config")
        from b3_tool_layer import execute_tool_calls, get_tools_schema
        from b5_memory import load_memory

        tools_file = Path(tools_config).resolve()
        memory_file = Path(memory_config).resolve()
        model_file = Path(model_config).resolve()
        selected_memory = load_memory(
            str(memory_file),
            runtime["selected_memory_ids"],
            runtime["use_global_memory"],
            runtime["user_input"],
            str(output_dir),
        )
        tools_schema = get_tools_schema(str(tools_file), runtime["toolset"], str(output_dir))
        mode = llm_mode or _default_llm_mode(model_file)
    if execution_mode == "integrated" and mode == "prompt_json":
        yield from _run_workspace_stream(
            runtime,
            execution_mode,
            system_prompt,
            selected_memory,
            tools_schema,
            tools_file,
            memory_file,
            model_file,
            mode,
            output_dir,
            started,
        )
        return
    current_user_message = {"role": "user", "content": runtime["user_input"]}
    if runtime["input_images"]:
        current_user_message["images"] = runtime["input_images"]
    messages = [
        {"role": "system", "content": system_prompt},
        *runtime["history_messages"],
        current_user_message,
    ]
    tool_rounds = 0
    llm_calls = 0
    turns = []
    all_tool_messages = []
    final_answer = ""
    status = "success"
    terminal_error = None
    warnings = []
    final_control = None
    if selected_memory.get("status") in {"partial", "error"}:
        warnings.append("memory selection completed with errors")

    while True:
        llm_calls += 1
        turn_start = perf_counter()
        if execution_mode == "fixture":
            if llm_calls > len(fixture_data["ai_messages"]):
                raise ValueError("fixture AIMessage sequence ended before a final answer")
            ai_message = deepcopy(fixture_data["ai_messages"][llm_calls - 1])
            if ai_message.get("content"):
                yield {"type": "delta", "text": ai_message["content"], "llm_call_index": llm_calls}
            llm_status = "success"
            llm_error = None
            llm_prompt_messages = None
        else:
            llm_result = None
            llm_input_messages = build_llm_prompt_messages(messages, tools_schema)
            for event in stream_ai_message(
                str(model_file),
                llm_input_messages,
                [],
                mode,
                str(output_dir / "llm_calls"),
                f"llm_call_{llm_calls:03d}",
                prompt_ready=True,
            ):
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "delta":
                    yield {
                        "type": "delta",
                        "text": str(event.get("text", "")),
                        "llm_call_index": llm_calls,
                    }
                elif event.get("type") == "done":
                    llm_result = event.get("result")
            if not isinstance(llm_result, dict) or not isinstance(llm_result.get("ai_message"), dict):
                raise ValueError("B4 stream result must contain an ai_message object")
            ai_message = llm_result["ai_message"]
            llm_status = llm_result.get("status")
            llm_error = llm_result.get("error")
            llm_prompt_messages = llm_result.get("prompt_messages")
        messages.append(ai_message)
        turn = {
            "turn_index": llm_calls,
            "ai_message": ai_message,
            "llm_prompt_messages": llm_prompt_messages,
            "llm_status": llm_status,
            "llm_error": llm_error,
            "tool_messages": [],
            "control": ai_message.get("control"),
            "agent_step": ai_message.get("agent_step"),
            "latency_ms": None,
        }
        if llm_status != "success":
            final_answer = ai_message.get("content", "").strip() or "模型输出解析失败，未生成有效回答。"
            status = "llm_parse_error"
            terminal_error = {
                "type": "LLMParseError",
                "message": "B4 failed to parse the model output as a valid AIMessage JSON object.",
                "llm_call_index": llm_calls,
                "cause": llm_error,
            }
            final_control = {
                "state": "failed",
                "action": "finish",
                "reason": "LLM output could not be parsed",
            }
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
            yield {"type": "state", **final_control, "llm_call_index": llm_calls}
            break
        control = ai_message["control"]
        yield {"type": "state", **control, "agent_step": ai_message.get("agent_step"), "llm_call_index": llm_calls}
        tool_calls = ai_message.get("tool_calls", [])
        if control["action"] == "finish":
            final_control = control
            final_answer = ai_message["content"]
            if control["state"] == "failed":
                status = "agent_failed"
                terminal_error = {
                    "type": "AgentDeclaredFailure",
                    "message": control["reason"],
                    "llm_call_index": llm_calls,
                }
            turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
            turns.append(turn)
            break
        yield {
            "type": "tool_start",
            "tool_calls": tool_calls,
            "assistant_content": ai_message.get("content", ""),
            "agent_step": ai_message.get("agent_step"),
            "llm_call_index": llm_calls,
        }
        if execution_mode == "fixture":
            tool_messages = _fixture_tool_messages(
                tool_calls,
                fixture_data["tool_messages"],
            )
        else:
            tool_messages = execute_tool_calls(
                tool_calls,
                str(tools_file),
                runtime["toolset"],
                str(output_dir),
            )
        tool_rounds += 1
        messages.extend(tool_messages)
        all_tool_messages.extend(tool_messages)
        turn["tool_messages"] = tool_messages
        yield {"type": "tool_done", "tool_messages": tool_messages, "llm_call_index": llm_calls}
        turn["latency_ms"] = round((perf_counter() - turn_start) * 1000, 3)
        turns.append(turn)

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
        append_jsonl(
            {
                "timestamp": now_iso(),
                "conversation_id": runtime["conversation_id"],
                "execution_mode": execution_mode,
                "status": trace["status"],
                "llm_mode": mode,
                "tool_rounds_used": tool_rounds,
                "llm_call_count": llm_calls,
                "elapsed_ms": result["elapsed_ms"],
                "streaming": True,
            },
            output_dir / "runtime_log.jsonl",
        )
    yield {"type": "done", "result": result}


def run_agent(
    input_path: str,
    tools_config: str | None,
    memory_config: str | None,
    model_config: str | None,
    outdir: str,
    llm_mode: str | None = None,
) -> dict:
    input_file = Path(input_path).resolve()
    return run(
        read_json(input_file),
        tools_config,
        memory_config,
        model_config,
        outdir,
        llm_mode,
        input_file,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Agent message and tool loop.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--tools_config")
    parser.add_argument("--memory_config")
    parser.add_argument("--model_config")
    parser.add_argument("--llm_mode", choices=["mock", "prompt_json"], default=None)
    parser.add_argument("--outdir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_agent(
            str(resolve_cli_path(args.input)),
            str(resolve_cli_path(args.tools_config)) if args.tools_config else None,
            str(resolve_cli_path(args.memory_config)) if args.memory_config else None,
            str(resolve_cli_path(args.model_config)) if args.model_config else None,
            str(resolve_cli_path(args.outdir)),
            args.llm_mode,
        )
        print(result["final_answer_path"])
        return 0
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
