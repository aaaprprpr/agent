from __future__ import annotations

from typing import Any


VALID_ROLES = {"system", "user", "assistant", "tool"}
VALID_AGENT_STATES = {"acting", "replanning", "completed", "failed"}
VALID_AGENT_ACTIONS = {"call_tools", "finish"}


def make_ai_message(
    content: str = "",
    tool_calls: list[dict] | None = None,
    control: dict | None = None,
) -> dict:
    message = {
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls or [],
    }
    if control is not None:
        message["control"] = control
    validate_ai_message(message)
    return message


def make_tool_message(
    tool_call_id: str,
    name: str,
    content: str,
    status: str = "success",
) -> dict:
    if status not in {"success", "error"}:
        raise ValueError(f"invalid tool status: {status}")
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content,
        "status": status,
    }


def make_skill_result(
    skill_name: str,
    status: str,
    input_data: dict,
    output: dict | None = None,
    error: dict | None = None,
    latency_ms: float | None = None,
) -> dict:
    if status not in {"success", "error"}:
        raise ValueError(f"invalid skill status: {status}")
    return {
        "skill_name": skill_name,
        "status": status,
        "input": input_data,
        "output": output,
        "error": error,
        "latency_ms": latency_ms,
    }


def normalize_tool_call(tool_call: dict[str, Any], index: int = 0) -> dict:
    if not isinstance(tool_call, dict):
        raise ValueError("tool call must be an object")
    if "function" in tool_call:
        function = tool_call.get("function") or {}
        name = function.get("name")
        args = function.get("arguments", {})
    else:
        name = tool_call.get("name")
        args = tool_call.get("args", {})
    if isinstance(args, str):
        import json

        args = json.loads(args)
    if not isinstance(name, str) or not name:
        raise ValueError("tool call name must be a non-empty string")
    if not isinstance(args, dict):
        raise ValueError("tool call args must be an object")
    call_id = tool_call.get("id") or f"call_{index + 1:03d}"
    if not isinstance(call_id, str) or not call_id:
        raise ValueError("tool call id must be a non-empty string")
    return {"id": call_id, "name": name, "args": args}


def validate_ai_message(message: dict) -> None:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("AIMessage role must be assistant")
    if not isinstance(message.get("content"), str):
        raise ValueError("AIMessage content must be a string")
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        raise ValueError("AIMessage tool_calls must be a list")
    normalized = [normalize_tool_call(call, index) for index, call in enumerate(tool_calls)]
    message["tool_calls"] = normalized
    if not message["content"] and not normalized:
        raise ValueError("AIMessage must contain content or tool_calls")
    default_control = {
        "state": "acting" if normalized else "completed",
        "action": "call_tools" if normalized else "finish",
        "reason": "",
    }
    control = message.setdefault("control", default_control)
    if not isinstance(control, dict):
        raise ValueError("AIMessage control must be an object")
    if set(control) != {"state", "action", "reason"}:
        raise ValueError("AIMessage control must contain exactly state, action, and reason")
    state = control.get("state")
    action = control.get("action")
    reason = control.get("reason")
    if state not in VALID_AGENT_STATES:
        raise ValueError(f"invalid AIMessage control state: {state}")
    if action not in VALID_AGENT_ACTIONS:
        raise ValueError(f"invalid AIMessage control action: {action}")
    if not isinstance(reason, str):
        raise ValueError("AIMessage control reason must be a string")
    if action == "call_tools" and not normalized:
        raise ValueError("AIMessage call_tools action requires tool_calls")
    if action == "finish" and normalized:
        raise ValueError("AIMessage finish action requires an empty tool_calls array")
    if action == "call_tools" and state not in {"acting", "replanning"}:
        raise ValueError("AIMessage call_tools action requires acting or replanning state")
    if action == "finish" and state not in {"completed", "failed"}:
        raise ValueError("AIMessage finish action requires completed or failed state")
    if state == "failed" and not reason.strip():
        raise ValueError("AIMessage failed state requires a reason")


def validate_messages(messages: Any) -> list[dict]:
    if not isinstance(messages, list):
        raise ValueError("messages must be a top-level array")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"message {index} must be an object")
        role = message.get("role")
        if role not in VALID_ROLES:
            raise ValueError(f"message {index} has invalid role: {role}")
        if not isinstance(message.get("content", ""), str):
            raise ValueError(f"message {index} content must be a string")
        if role == "assistant":
            message.setdefault("tool_calls", [])
            validate_ai_message(message)
        if role == "tool":
            for field in ("tool_call_id", "name", "status"):
                if field not in message:
                    raise ValueError(f"tool message {index} missing {field}")
    return messages
