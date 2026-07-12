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
    """Build the complete model-facing prompt for one Agent loop step.

    The runtime owns message flow. B4 may keep a standalone fallback, but the
    integrated Agent path should disclose tools and protocol here before calling B4.
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
                    + " 最新工具消息已经包含工具结果。必须在 agent_step.observation 中概括工具结果、有效事实和仍需信息；"
                    "足够则 completed 并给最终回答，不足则 replanning 继续调用工具，无法继续则 failed 并说明原因。"
                ),
            }
        )
    return prompt_messages


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
        "available_tools_schema": tools_schema,
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
                "只面向用户输出最终答案。不要泄露工具 JSON、内部阶段名、内部状态结构或调度过程。"
            ),
        },
        {
            "role": "user",
            "content": (
                "根据用户任务、可用证据和已知事实生成最终回答。\n"
                "如果信息不足，直接说明还需要什么；不要编造。"
                "只有 accepted_evidence 或成功工具结果中明确出现的信息，才能声明为已经完成。"
                "没有成功的 file_writer 结果时，不得说文件已生成；没有下载接口或下载工具时，不得说已经可以直接下载；"
                "没有成功 file_reader/search/calculator 等结果时，不得声称已经读取、搜索或计算完成。\n"
                "只输出 AIMessage JSON 对象，顶层键只能是 content、tool_calls、control、agent_step。\n"
                "必须满足：tool_calls=[]，control.action=finish，control.state 为 completed 或 failed，"
                "agent_step.phase=final。\n\n"
                f"本轮状态如下：\n{_json_block(payload)}"
            ),
        },
    ]

