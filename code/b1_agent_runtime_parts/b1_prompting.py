from __future__ import annotations

import json
from copy import deepcopy

from .b1_workspace import (
    _memory_overview,
    _tool_attempts_summary,
    _workspace_history_messages,
    _workspace_memory,
)


def build_llm_prompt_messages(messages: list[dict], tools_schema: list[dict]) -> list[dict]:
    """Build the model-facing prompt for the legacy one-loop Agent path."""
    if not isinstance(tools_schema, list):
        raise ValueError("tools_schema must be an array")
    prompt_messages = deepcopy(messages)
    protocol_instruction = (
        "输出协议：只返回一个 JSON 对象，不要输出 Markdown 或 JSON 之外的文字。\n"
        '顶层键只能是 "content"、"tool_calls"、"control"、"agent_step"。\n'
        'content 是给用户看的自然语言；tool_calls 是工具调用数组；control 只包含 "state"、"action"、"reason"；'
        'agent_step 只包含 "phase"、"plan"、"observation"、"known_facts"、"missing_info"、"next_step"。\n'
        '需要工具时：control.action="call_tools"，control.state 为 "acting" 或 "replanning"，tool_calls 非空。\n'
        '结束时：control.action="finish"，control.state 为 "completed" 或 "failed"，tool_calls=[]。\n'
        "工具名和参数必须来自本轮可用工具结构；不要创造工具。"
    )
    tool_disclosure = (
        "\n\n本轮可用工具结构：\n"
        + json.dumps(_llm_tool_schemas(tools_schema), ensure_ascii=False)
        + "\n\n"
        + protocol_instruction
    )
    if prompt_messages and prompt_messages[0].get("role") == "system":
        prompt_messages[0]["content"] += tool_disclosure
    else:
        prompt_messages.insert(0, {"role": "system", "content": tool_disclosure.strip()})

    if prompt_messages[-1].get("role") == "tool":
        prompt_messages.append(
            {
                "role": "user",
                "content": "根据最新工具结果继续处理，并仍按上面的 JSON 协议输出。",
            }
        )
    return prompt_messages


def _json_block(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _short_tool_description(description: object) -> str:
    text = str(description or "").strip()
    for marker in (
        "\n工具执行结果会封装",
        "工具执行结果会封装",
        "\n主要 output 字段",
        "主要 output 字段",
    ):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    return text


def _compact_parameter_schema(parameters: object) -> dict:
    if not isinstance(parameters, dict):
        return {"type": "object", "properties": {}, "required": []}
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    compact_properties = {}
    for name, definition in properties.items():
        if not isinstance(definition, dict):
            continue
        entry = {}
        for key in ("type", "description", "enum"):
            if key in definition:
                entry[key] = definition[key]
        if definition.get("type") == "array" and isinstance(definition.get("items"), dict):
            item_type = definition["items"].get("type")
            entry["items"] = {"type": item_type} if item_type else definition["items"]
        compact_properties[name] = entry
    required = parameters.get("required", [])
    if not isinstance(required, list):
        required = []
    return {
        "type": "object",
        "properties": compact_properties,
        "required": [name for name in required if name in compact_properties],
    }


def _compact_returns_schema(function: dict) -> dict:
    raw_returns = function.get("x-returns")
    properties = raw_returns.get("properties") if isinstance(raw_returns, dict) else None
    if not isinstance(properties, dict):
        return {}
    compact = {}
    for name, definition in properties.items():
        if not isinstance(definition, dict):
            continue
        entry = {}
        for key in ("type", "description"):
            if key in definition:
                entry[key] = definition[key]
        compact[name] = entry
    return compact


def _llm_tool_schemas(tools_schema: list[dict]) -> list[dict]:
    """Return a compact model-facing tool view."""
    compact = []
    for tool in tools_schema:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = function.get("name") or tool.get("name")
        if not name:
            continue
        entry = {
            "name": name,
            "description": _short_tool_description(function.get("description") or tool.get("description")),
            "parameters": _compact_parameter_schema(function.get("parameters") or tool.get("parameters")),
        }
        returns = _compact_returns_schema(function)
        if returns:
            entry["returns"] = returns
        compact.append(entry)
    return compact


def _tool_briefs(tools_schema: list[dict]) -> list[dict]:
    briefs = []
    for function in _llm_tool_schemas(tools_schema):
        entry = {
            "name": function.get("name"),
            "description": function.get("description", ""),
        }
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                entry["args"] = list(properties)
        briefs.append(entry)
    return briefs


def _stage_messages(system_prompt: str, stage_name: str, instruction: str, payload: dict) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\n你正在处理本轮对话的一个内部步骤。"
                "只完成当前步骤要求，不要在最终回答或中间说明里提到模块名、内部架构、调度器等实现细节。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"阶段：{stage_name}\n"
                f"{instruction}\n\n"
                "本轮状态如下：\n"
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
    history_messages = _workspace_history_messages(runtime)
    payload = {
        "user_input": runtime["user_input"],
        "input_images_count": len(runtime.get("input_images", [])),
        "history_messages": history_messages,
        "history_policy": {
            "source": "recent_history_messages" if isinstance(runtime.get("recent_history_messages"), list) else "history_messages",
            "full_history_message_count": len(runtime.get("history_messages", [])),
            "workspace_history_message_count": len(history_messages),
        },
        "legacy_memory": _memory_overview(selected_memory),
        "workspace_memory": _workspace_memory(selected_memory, runtime.get("workspace_memory_context")),
        "available_tools": _tool_briefs(tools_schema),
    }
    return _stage_messages(
        system_prompt,
        "planning",
        (
            "判断用户本轮到底要什么，并决定是否需要工具。"
            "打招呼、闲聊、普通问答、让你记住一句话或数字时，通常直接 answering；"
            "记忆会由系统在对话结束后保存，不存在也不得创造 memory_writer、memory_write、save_memory 等工具。"
            "只有需要读取文件、搜索网页、获取当前时间、计算、写真实文件、分析表格或格式转换时，才写 tool_calling。"
            "如果可以直接回答，next_stage 写 answering；如果确实无法推进，写 failed。不要调用工具。"
            "JSON 键：user_goal、requirements、plan、known_facts、missing_info、next_stage、reason。"
            "known_facts 和 missing_info 只写和用户目标直接相关的信息，不要列工具清单、内部模块或实现细节。"
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
        "available_tools_schema": _llm_tool_schemas(tools_schema),
    }
    return [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\n你正在决定是否执行一个真实可用的工具动作。"
                "只能使用本轮提供的工具 schema 中明确存在的工具名；不得创造工具。"
                "如果没有合适工具，结束并说明原因，不要输出不存在的工具调用。"
                "不要输出最终答案，不要把工具结果当成已经存在的信息。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据本轮状态选择下一步工具动作。\n"
                "只输出 AIMessage JSON 对象，顶层键只能是 content、tool_calls、control、agent_step。\n"
                "tool_calls 必须是顶层字段，不能放在 control 内；control 里只能有 state、action、reason。\n"
                "如果确实需要工具，返回至少一个 tool_call：control.action=call_tools，tool_calls 填写要调用的工具。\n"
                "tool_calls[*].name 必须逐字匹配 available_tools_schema 中已有工具名。\n"
                "如果用户只是让你记住信息、打招呼或普通对话，不要调用工具，返回 finish/completed。\n"
                "如果已有失败尝试，必须根据失败原因调整工具、参数或路径；不要无变化地重复同一调用。\n"
                "如果确认没有任何可用工具能推进任务，返回 control.action=finish、control.state=failed、tool_calls=[]，并在 reason 写清原因。\n"
                "不能用 content 代替工具调用；content 只写极短工具前说明，不能写最终答案、完整代码、文件内容或完成声明。\n\n"
                f"本轮状态如下：\n{_json_block(payload)}"
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
            "无效、错误或偏题的信息放入 rejected_evidence；仍需要的信息放入 missing_info。"
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
        "workspace_memory": workspace["memory"],
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
                + "\n\n你正在生成最终回复。"
                "只面向用户输出最终答案。不要泄露工具 JSON、内部阶段名、内部状态结构、调度过程、解析异常或内部错误细节。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据用户任务、可用证据和已知事实生成最终回答。\n"
                "如果信息不足，直接说明还需要什么；不要编造。"
                "只有 accepted_evidence 或成功工具结果中明确出现的信息，才能声明为已经完成。"
                "没有成功的写文件工具结果时，不得说文件已生成；没有下载接口或下载工具时，不得说已经可以直接下载；"
                "文件生成成功时，面向用户优先说明文件名和下载入口；不要展示 generated_file_path 或本地绝对路径，除非用户明确要求本地路径。"
                "没有成功 file_reader/search/calculator 等结果时，不得声称已经读取、搜索或计算完成。\n"
                "只输出 AIMessage JSON 对象，顶层键只能是 content、tool_calls、control、agent_step。\n"
                "必须满足：tool_calls=[]，control.action=finish，control.state 为 completed 或 failed，"
                "agent_step.phase=final。\n\n"
                f"本轮状态如下：\n{_json_block(payload)}"
            ),
        },
    ]


def _workspace_stage_failure_answer_messages(
    system_prompt: str,
    workspace: dict,
    failed_stage: str,
    error: dict | None,
    raw_text: str | None = None,
) -> list[dict]:
    payload = {
        "user_input": workspace["input"]["user_input"],
        "history_messages": workspace["input"].get("history_messages", []),
        "workspace_memory": workspace["memory"],
        "task": workspace["task"],
        "accepted_evidence": workspace["tools"].get("accepted_evidence", []),
        "rejected_evidence": workspace["tools"].get("rejected_evidence", []),
        "known_facts": workspace["draft"].get("known_facts", []),
        "missing_info": workspace["draft"].get("missing_info", []),
        "tool_attempts": _tool_attempts_summary(workspace),
        "observations": workspace["tools"].get("observations", []),
        "result_policy": {
            "only_successful_tool_results_are_evidence": True,
            "do_not_claim_completion_without_evidence": True,
        },
    }
    del raw_text
    return [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\n你正在生成最终回复。"
                "你需要基于用户目标、已有证据和可靠工具结果给出面向用户的回复。"
                "不要泄露工具 JSON、内部阶段名、内部状态结构、调度过程、解析异常或内部错误细节。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据本轮状态生成最终回答。\n"
                "如果已有工具结果或证据足够完成用户任务，就直接完成。"
                "如果信息不足或没有可靠工具结果，说明还缺什么或下一步需要什么。"
                "不要使用固定兜底文案，不要编造已经完成的文件、下载、读取、搜索或写入结果。\n"
                "文件生成成功时，面向用户优先说明文件名和下载入口；不要展示 generated_file_path 或本地绝对路径，除非用户明确要求本地路径。\n"
                "只输出 AIMessage JSON 对象，顶层键只能是 content、tool_calls、control、agent_step。\n"
                "必须满足：tool_calls=[]，control.action=finish，control.state 为 completed 或 failed，agent_step.phase=final。\n\n"
                f"本轮状态如下：\n{_json_block(payload)}"
            ),
        },
    ]

