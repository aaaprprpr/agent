from __future__ import annotations

import argparse
import codecs
import json
import re
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from common.io_utils import append_jsonl, read_json, read_yaml, write_json
from common.logging_utils import now_iso
from common.path_utils import resolve_cli_path, resolve_from_file
from common.schemas import make_ai_message, validate_ai_message, validate_messages


PARSE_ERROR_CONTENT = "模型输出解析失败，无法生成有效工具调用或最终回答。"
_MODEL_CACHE: dict[tuple[str, ...], tuple[Any, Any]] = {}


def _load_model_config(model_config: str | Path) -> tuple[Path, dict]:
    path = Path(model_config).resolve()
    config = read_yaml(path)
    if not isinstance(config, dict):
        raise ValueError("model.yaml must contain an object")
    return path, config


def _llm_source(config: dict) -> str:
    runtime = config.get("runtime", {})
    source = runtime.get("llm_source", "local") if isinstance(runtime, dict) else "local"
    if source in {"local", "transformers"}:
        return "local"
    if source in {"fastapi", "api"}:
        return "fastapi"
    raise ValueError("runtime.llm_source must be local or fastapi")


def _generation_options(config: dict) -> dict:
    generation_config = config.get("generation", {})
    if not isinstance(generation_config, dict):
        generation_config = {}
    result = {
        "max_new_tokens": int(generation_config.get("max_new_tokens", 1024)),
        "do_sample": bool(generation_config.get("do_sample", False)),
    }
    if result["max_new_tokens"] <= 0:
        raise ValueError("generation.max_new_tokens must be positive")
    if result["do_sample"]:
        for name in ("temperature", "top_p", "top_k", "repetition_penalty"):
            if name in generation_config and generation_config[name] is not None:
                result[name] = generation_config[name]
    return result


def _max_input_tokens(config: dict) -> int | None:
    context = config.get("context", {})
    if not isinstance(context, dict):
        return None
    value = context.get("max_input_tokens")
    if value is None:
        return None
    value = int(value)
    if value <= 0:
        raise ValueError("context.max_input_tokens must be positive")
    return value


def _fastapi_config(config: dict) -> dict:
    api_config = config.get("fastapi", {})
    if not isinstance(api_config, dict):
        raise ValueError("fastapi config must be an object")
    base_url = api_config.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("fastapi.base_url is required when runtime.llm_source=fastapi")
    generate_path = api_config.get("generate_path", "/generate")
    if not isinstance(generate_path, str) or not generate_path.startswith("/"):
        raise ValueError("fastapi.generate_path must start with /")
    stream_path = api_config.get("stream_path", "/generate_stream")
    if not isinstance(stream_path, str) or not stream_path.startswith("/"):
        raise ValueError("fastapi.stream_path must start with /")
    timeout = float(api_config.get("timeout_seconds", 600))
    if timeout <= 0:
        raise ValueError("fastapi.timeout_seconds must be positive")
    return {
        "base_url": base_url.rstrip("/"),
        "generate_path": generate_path,
        "stream_path": stream_path,
        "timeout_seconds": timeout,
        "api_key": api_config.get("api_key"),
        "model": api_config.get("model"),
    }


def _artifact_paths(artifact_dir: str | Path, stem: str | None) -> tuple[Path, Path, Path]:
    directory = Path(artifact_dir)
    prefix = f"{stem}_" if stem else ""
    return (
        directory / f"{prefix}raw_model_output.json",
        directory / f"{prefix}ai_message.json",
        directory / "llm_run_log.jsonl",
    )


def _extract_tool_result(message: dict) -> dict:
    try:
        result = json.loads(message["content"])
    except (KeyError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("ToolMessage content is not a SkillResult JSON string") from exc
    if not isinstance(result, dict):
        raise ValueError("ToolMessage content must decode to an object")
    return result


def _three_points(text: str) -> list[str]:
    parts = [part.strip(" \t\r\n。") for part in re.split(r"\n+|(?<=[。！？!?])", text) if part.strip()]
    points = []
    for part in parts:
        if part not in points:
            points.append(part)
        if len(points) == 3:
            break
    while len(points) < 3:
        points.append("工具结果未提供更多可提取内容")
    return points


def _mock_generate(messages: list[dict]) -> dict:
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    if not tool_messages:
        return make_ai_message(
            "",
            [
                {
                    "id": "call_001",
                    "name": "file_reader",
                    "args": {"path": "docs/agent_intro.txt", "max_chars": 2000},
                }
            ],
        )
    latest = tool_messages[-1]
    result = _extract_tool_result(latest)
    if latest.get("status") != "success" or result.get("status") != "success":
        error = result.get("error") or {}
        detail = error.get("message", "未知工具错误") if isinstance(error, dict) else str(error)
        return make_ai_message(f"工具调用失败，无法完成请求：{detail}", [])
    output = result.get("output") or {}
    content = output.get("content") if isinstance(output, dict) else None
    if not isinstance(content, str) or not content.strip():
        content = json.dumps(output, ensure_ascii=False)
    points = _three_points(content)
    answer = "三条中文要点如下：\n" + "\n".join(f"{index}. {point}" for index, point in enumerate(points, 1))
    return make_ai_message(answer, [])


def _parse_tool_calls_fragment(raw_text: str, original_error: json.JSONDecodeError) -> dict:
    markers = ['"tool_calls":[', '\\"tool_calls\\":[']
    marker_index = -1
    marker = ""
    for item in markers:
        marker_index = raw_text.find(item)
        if marker_index != -1:
            marker = item
            break
    if marker_index == -1:
        raise original_error
    array_start = marker_index + marker.index("[")
    array_end = raw_text.rfind("]")
    if array_end < array_start:
        raise ValueError("model output contains tool_calls marker but no closing array")
    array_text = raw_text[array_start : array_end + 1]
    try:
        tool_calls = json.loads(array_text)
    except json.JSONDecodeError:
        tool_calls = json.loads(array_text.replace('\\"', '"'))
    if not isinstance(tool_calls, list) or not tool_calls:
        raise original_error
    return {"content": "", "tool_calls": tool_calls}


def _parse_json_with_backtick_tail(raw_text: str, original_error: json.JSONDecodeError) -> dict:
    text = raw_text.strip()
    try:
        candidate, end_index = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        raise original_error
    trailing = text[end_index:].strip()
    if trailing and set(trailing) <= {"`", '"'}:
        return candidate
    raise original_error


def _decode_partial_json_string(fragment: str) -> str:
    text = fragment.rstrip()
    while text.endswith("\\"):
        text = text[:-1]
    while text:
        try:
            return json.loads(f'"{text}"')
        except json.JSONDecodeError:
            text = text[:-1]
    return fragment


def _parse_content_fragment(raw_text: str, original_error: json.JSONDecodeError) -> dict:
    match = re.search(r'"content"\s*:\s*"', raw_text)
    if not match:
        raise original_error
    chars = []
    escaped = False
    for char in raw_text[match.end() :]:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            chars.append(char)
            escaped = True
            continue
        if char == '"':
            break
        chars.append(char)
    content = _decode_partial_json_string("".join(chars)).strip()
    if not content:
        raise original_error
    return {"content": content, "tool_calls": []}


def _streaming_content_prefix(raw_text: str) -> str:
    match = re.search(r'"content"\s*:\s*"', raw_text)
    if not match:
        return ""
    chars = []
    escaped = False
    for char in raw_text[match.end() :]:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            chars.append(char)
            escaped = True
            continue
        if char == '"':
            break
        chars.append(char)
    return _decode_partial_json_string("".join(chars))


def _candidate_to_message(candidate: dict) -> tuple[dict, dict]:
    if not isinstance(candidate, dict):
        raise ValueError("model output JSON must be an object")
    expected_keys = {"content", "tool_calls", "control"}
    unknown_keys = set(candidate) - expected_keys
    if unknown_keys:
        raise ValueError(f"model output JSON contains unknown keys: {', '.join(sorted(unknown_keys))}")
    message = {
        "role": "assistant",
        "content": candidate.get("content", ""),
        "tool_calls": candidate.get("tool_calls", []),
    }
    if "control" in candidate:
        message["control"] = candidate["control"]
    validate_ai_message(message)
    parsed_candidate = {
        "content": message["content"],
        "tool_calls": message["tool_calls"],
        "control": message["control"],
    }
    return parsed_candidate, message


def _parse_model_output(raw_text: str) -> tuple[dict, dict]:
    try:
        candidate = json.loads(raw_text.strip())
    except json.JSONDecodeError as exc:
        try:
            candidate = _parse_json_with_backtick_tail(raw_text, exc)
        except json.JSONDecodeError:
            try:
                candidate = _parse_tool_calls_fragment(raw_text, exc)
            except Exception:
                candidate = _parse_content_fragment(raw_text, exc)
    return _candidate_to_message(candidate)


def _dtype_value(torch_module: Any, configured: str) -> Any:
    if configured == "auto":
        return "auto"
    mapping = {
        "bfloat16": torch_module.bfloat16,
        "float16": torch_module.float16,
        "float32": torch_module.float32,
    }
    if configured not in mapping:
        raise ValueError(f"unsupported torch_dtype: {configured}")
    return mapping[configured]


def _read_model_metadata(model_path: Path) -> dict[str, Any]:
    config_path = model_path / "config.json"
    if not config_path.is_file():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _select_loader(transformers_module: Any, model_path: Path, model_config: dict) -> tuple[Any, Any, str]:
    requested = str(model_config.get("model_loader", "auto")).lower()
    metadata = _read_model_metadata(model_path)
    architectures = metadata.get("architectures") or []
    model_type = metadata.get("model_type")
    is_qwen35 = model_type == "qwen3_5" or "Qwen3_5ForConditionalGeneration" in architectures

    if requested in {"qwen3_5", "qwen35", "multimodal"} or (requested == "auto" and is_qwen35):
        processor_cls = getattr(transformers_module, "AutoProcessor", None)
        model_cls = getattr(transformers_module, "AutoModelForMultimodalLM", None)
        if processor_cls is not None and model_cls is not None:
            return processor_cls, model_cls, "multimodal"
        direct_cls = getattr(transformers_module, "Qwen3_5ForConditionalGeneration", None)
        if processor_cls is not None and direct_cls is not None:
            return processor_cls, direct_cls, "qwen3_5_direct"
        if requested != "auto":
            raise RuntimeError("transformers does not provide Qwen3.5 multimodal loader classes")

    tokenizer_cls = getattr(transformers_module, "AutoTokenizer")
    causal_cls = getattr(transformers_module, "AutoModelForCausalLM")
    return tokenizer_cls, causal_cls, "causal_lm"


def _from_pretrained_with_dtype(cls: Any, path: Path, kwargs: dict, dtype: Any) -> Any:
    try:
        return cls.from_pretrained(str(path), dtype=dtype, **kwargs)
    except TypeError:
        return cls.from_pretrained(str(path), torch_dtype=dtype, **kwargs)


def _move_inputs_to_device(inputs: Any, device: Any) -> Any:
    if hasattr(inputs, "to"):
        return inputs.to(device)
    if isinstance(inputs, dict):
        return {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
    raise TypeError("chat template output must be a tensor batch or dict")


def _decode_new_tokens(processor: Any, new_tokens: Any) -> str:
    if hasattr(processor, "decode"):
        return processor.decode(new_tokens, skip_special_tokens=True)
    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is not None and hasattr(tokenizer, "decode"):
        return tokenizer.decode(new_tokens, skip_special_tokens=True)
    if hasattr(processor, "batch_decode"):
        return processor.batch_decode([new_tokens], skip_special_tokens=True)[0]
    raise TypeError("processor/tokenizer does not provide decode or batch_decode")


def _apply_chat_template(processor: Any, messages: list[dict]) -> Any:
    kwargs = {
        "tokenize": True,
        "add_generation_prompt": True,
        "return_tensors": "pt",
        "return_dict": True,
    }
    try:
        return processor.apply_chat_template(messages, enable_thinking=False, **kwargs)
    except TypeError:
        return processor.apply_chat_template(messages, **kwargs)


def _model_cache_key(
    model_path: Path,
    tokenizer_path: Path,
    local_only: bool,
    trust_remote_code: bool,
    dtype: Any,
    device_map: Any,
    max_memory: Any,
    loader_name: str,
) -> tuple[str, ...]:
    try:
        device_map_key = json.dumps(device_map, sort_keys=True, separators=(",", ":"))
    except TypeError:
        device_map_key = repr(device_map)
    try:
        max_memory_key = json.dumps(max_memory, sort_keys=True, separators=(",", ":"))
    except TypeError:
        max_memory_key = repr(max_memory)
    return (
        str(model_path),
        str(tokenizer_path),
        str(local_only),
        str(trust_remote_code),
        str(dtype),
        device_map_key,
        max_memory_key,
        loader_name,
    )


def _load_model_bundle(
    transformers_module: Any,
    model_path: Path,
    tokenizer_path: Path,
    local_only: bool,
    trust_remote_code: bool,
    dtype: Any,
    device_map: Any,
    max_memory: Any,
    model_config: dict,
) -> tuple[Any, Any]:
    processor_cls, model_cls, loader_name = _select_loader(transformers_module, model_path, model_config)
    cache_key = _model_cache_key(
        model_path,
        tokenizer_path,
        local_only,
        trust_remote_code,
        dtype,
        device_map,
        max_memory,
        loader_name,
    )
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        print("model_cache=hit", file=sys.stderr, flush=True)
        return cached

    print("model_cache=miss", file=sys.stderr, flush=True)
    processor = processor_cls.from_pretrained(
        str(tokenizer_path),
        local_files_only=local_only,
        trust_remote_code=trust_remote_code,
    )
    model_kwargs = {
        "local_files_only": local_only,
        "trust_remote_code": trust_remote_code,
        "device_map": device_map,
    }
    if max_memory is not None:
        model_kwargs["max_memory"] = max_memory
    model = _from_pretrained_with_dtype(model_cls, model_path, model_kwargs, dtype)
    _MODEL_CACHE[cache_key] = (processor, model)
    return processor, model


def _build_prompt_messages(messages: list[dict], tools_schema: list[dict]) -> list[dict]:
    prompt_messages = deepcopy(messages)
    format_instruction = (
        "IMPORTANT OUTPUT FORMAT:\n"
        "You must return exactly one valid JSON object.\n"
        "Do not output markdown.\n"
        "Do not output text outside the JSON object.\n"
        "Do not output code fences or backticks.\n"
        'The first output character must be "{" and the last output character must be "}".\n\n'
        "Successful final-answer example:\n"
        '{"content":"final answer text","tool_calls":[],"control":'
        '{"state":"completed","action":"finish","reason":"task completed"}}\n\n'
        "Failed final-answer example:\n"
        '{"content":"I need the missing filename before I can continue.","tool_calls":[],"control":'
        '{"state":"failed","action":"finish","reason":"required filename is missing"}}\n\n'
        "Tool-call example:\n"
        '{"content":"I will read the file first.","tool_calls":[{"id":"call_001","name":"file_reader",'
        '"args":{"path":"docs/agent_intro.txt","max_chars":2000}}],"control":'
        '{"state":"acting","action":"call_tools","reason":"need file contents"}}\n\n'
        "The top-level keys must be exactly:\n"
        "- content: string\n"
        "- tool_calls: array\n"
        "- control: object with exactly state, action, and reason\n\n"
        "Use action call_tools with non-empty tool_calls and state acting or replanning.\n"
        "After ToolMessages, analyze progress and either call tools again with state replanning or finish.\n"
        "Use action finish with empty tool_calls and state completed or failed.\n"
        "A failed state must include a concrete reason.\n"
        "Never put tool_calls inside content.\n"
        'Never output {"content":"tool_calls": ...}.'
    )
    envelope_reminder = (
        "IMPORTANT OUTPUT FORMAT: Output the JSON object now. "
        'Your first output character must be "{" and your last output character must be "}". '
        "Never output a backtick, Markdown, a code block, an explanation, or text outside the JSON. "
        'Use exactly the top-level keys "content" (string), "tool_calls" (array), and "control" (object). '
        "Set control.action to call_tools when requesting tools, or finish when ending the loop. "
        "Set control.state to acting, replanning, completed, or failed. "
        "When finishing after failure, include the reason in control.reason. "
        'Never put tool_calls inside content. Never output {"content":"tool_calls": ...}.'
    )
    system_instruction = (
        "\n\nAvailable tools JSON schema:\n"
        + json.dumps(tools_schema, ensure_ascii=False)
        + "\n"
        + format_instruction
    )
    if prompt_messages and prompt_messages[0].get("role") == "system":
        prompt_messages[0]["content"] += system_instruction
    else:
        prompt_messages.insert(0, {"role": "system", "content": system_instruction.strip()})

    for message in reversed(prompt_messages):
        if message.get("role") == "user":
            message["content"] += "\n\n" + envelope_reminder
            break
    if prompt_messages[-1].get("role") == "tool":
        prompt_messages.append(
            {
                "role": "user",
                "content": (
                    envelope_reminder
                    + " The latest ToolMessage already contains a tool result. If it provides the requested "
                    "information, finish with state completed. Otherwise analyze the result and choose another "
                    "tool call with state replanning, or finish with state failed and a concrete reason."
                ),
            }
        )
    return prompt_messages


def _prompt_json_generate(config_path: Path, config: dict, messages: list[dict], tools_schema: list[dict]) -> str:
    try:
        import torch
        import transformers
    except ImportError as exc:
        raise RuntimeError("prompt_json mode requires requirements-llm.txt") from exc
    model_config = config.get("model", {})
    model_setting = model_config.get("model_name_or_path")
    tokenizer_setting = model_config.get("tokenizer_name_or_path", model_setting)
    if not isinstance(model_setting, str) or not isinstance(tokenizer_setting, str):
        raise ValueError("model_name_or_path and tokenizer_name_or_path are required")
    model_path = resolve_from_file(model_setting, config_path)
    tokenizer_path = resolve_from_file(tokenizer_setting, config_path)
    if not model_path.exists() or not tokenizer_path.exists():
        raise FileNotFoundError(f"local model path does not exist: {model_path}")
    local_only = bool(model_config.get("local_files_only", True))
    trust_remote_code = bool(model_config.get("trust_remote_code", False))
    dtype = _dtype_value(torch, str(model_config.get("torch_dtype", "auto")))
    processor, model = _load_model_bundle(
        transformers,
        model_path,
        tokenizer_path,
        local_only,
        trust_remote_code,
        dtype,
        model_config.get("device_map", "auto"),
        model_config.get("max_memory"),
        model_config,
    )
    prompt_messages = _build_prompt_messages(messages, tools_schema)
    inputs = _apply_chat_template(processor, prompt_messages)
    input_length = int(inputs["input_ids"].shape[-1])
    max_input_tokens = _max_input_tokens(config)
    if max_input_tokens is not None and input_length > max_input_tokens:
        raise ValueError(f"prompt has {input_length} tokens, exceeding context.max_input_tokens={max_input_tokens}")
    device = next(model.parameters()).device
    inputs = _move_inputs_to_device(inputs, device)
    options = _generation_options(config)
    eos_token_id = getattr(processor, "eos_token_id", None)
    pad_token_id = getattr(processor, "pad_token_id", None)
    tokenizer = getattr(processor, "tokenizer", None)
    if pad_token_id is None and tokenizer is not None:
        pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if eos_token_id is None and tokenizer is not None:
        eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if pad_token_id is not None:
        options.setdefault("pad_token_id", pad_token_id)
    elif eos_token_id is not None:
        options.setdefault("pad_token_id", eos_token_id)
    with torch.no_grad():
        generated = model.generate(**inputs, **options)
    new_tokens = generated[0][input_length:]
    return _decode_new_tokens(processor, new_tokens)


def _fastapi_prompt_json_generate(config_path: Path, config: dict, messages: list[dict], tools_schema: list[dict]) -> str:
    del config_path
    api_config = _fastapi_config(config)
    prompt_messages = _build_prompt_messages(messages, tools_schema)
    payload = {
        "messages": prompt_messages,
        "generation": _generation_options(config),
    }
    if isinstance(api_config["model"], str) and api_config["model"].strip():
        payload["model"] = api_config["model"]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if isinstance(api_config["api_key"], str) and api_config["api_key"]:
        headers["Authorization"] = f"Bearer {api_config['api_key']}"
    request = urllib.request.Request(
        url=api_config["base_url"] + api_config["generate_path"],
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=api_config["timeout_seconds"]) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FastAPI LLM request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"FastAPI LLM request failed: {exc}") from exc
    if not isinstance(response_data, dict) or not isinstance(response_data.get("raw_text"), str):
        raise ValueError("FastAPI LLM response must contain raw_text string")
    return response_data["raw_text"]


def _iter_fastapi_text_response(request: urllib.request.Request, timeout_seconds: float) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            while True:
                chunk = response.read(1)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    yield text
            tail = decoder.decode(b"", final=True)
            if tail:
                yield tail
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FastAPI LLM stream request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"FastAPI LLM stream request failed: {exc}") from exc


def _fastapi_prompt_json_stream(config_path: Path, config: dict, messages: list[dict], tools_schema: list[dict]) -> Iterator[str]:
    del config_path
    api_config = _fastapi_config(config)
    prompt_messages = _build_prompt_messages(messages, tools_schema)
    payload = {
        "messages": prompt_messages,
        "generation": _generation_options(config),
    }
    if isinstance(api_config["model"], str) and api_config["model"].strip():
        payload["model"] = api_config["model"]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if isinstance(api_config["api_key"], str) and api_config["api_key"]:
        headers["Authorization"] = f"Bearer {api_config['api_key']}"
    request = urllib.request.Request(
        url=api_config["base_url"] + api_config["stream_path"],
        data=data,
        headers=headers,
        method="POST",
    )
    yield from _iter_fastapi_text_response(request, api_config["timeout_seconds"])


def _write_generation_artifacts(
    mode: str,
    backend: str,
    source: str,
    raw_text: str,
    prompt_messages: list[dict] | None,
    parsed_candidate: dict | None,
    ai_message: dict,
    status: str,
    error: dict | None,
    generated_at: str,
    artifact_dir: str | None,
    artifact_stem: str | None,
) -> None:
    if not artifact_dir:
        return
    raw_record = {
        "mode": mode,
        "backend": backend,
        "llm_source": source,
        "raw_text": raw_text,
        "prompt_messages": prompt_messages,
        "parsed_candidate": parsed_candidate,
        "status": status,
        "error": error,
        "generated_at": generated_at,
    }
    raw_path, message_path, log_path = _artifact_paths(artifact_dir, artifact_stem)
    write_json(raw_record, raw_path)
    write_json(ai_message, message_path)
    append_jsonl(
        {
            "timestamp": generated_at,
            "mode": mode,
            "status": status,
            "raw_output_path": str(raw_path),
            "ai_message_path": str(message_path),
            "error": error,
        },
        log_path,
    )


def generate_ai_message(
    model_config: str,
    messages: list[dict],
    tools_schema: list[dict],
    mode: str = "prompt_json",
    artifact_dir: str | None = None,
    artifact_stem: str | None = None,
) -> dict:
    config_path, config = _load_model_config(model_config)
    messages = validate_messages(deepcopy(messages))
    if not isinstance(tools_schema, list):
        raise ValueError("tools_schema must be an array")
    generated_at = now_iso()
    source = "mock" if mode == "mock" else _llm_source(config)
    backend = "mock" if mode == "mock" else source
    prompt_messages = None
    if mode == "mock":
        ai_message = _mock_generate(messages)
        parsed_candidate = {
            "content": ai_message["content"],
            "tool_calls": ai_message["tool_calls"],
            "control": ai_message["control"],
        }
        raw_text = json.dumps(parsed_candidate, ensure_ascii=False)
        status = "success"
        error = None
    elif mode == "prompt_json":
        prompt_messages = _build_prompt_messages(messages, tools_schema)
        if source == "local":
            raw_text = _prompt_json_generate(config_path, config, messages, tools_schema)
        else:
            raw_text = _fastapi_prompt_json_generate(config_path, config, messages, tools_schema)
        try:
            parsed_candidate, ai_message = _parse_model_output(raw_text)
            status = "success"
            error = None
        except Exception as exc:
            parsed_candidate = None
            ai_message = make_ai_message(PARSE_ERROR_CONTENT, [])
            status = "error"
            error = {"type": type(exc).__name__, "message": str(exc)}
    else:
        raise ValueError("mode must be mock or prompt_json")
    if artifact_dir:
        _write_generation_artifacts(
            mode,
            backend,
            source,
            raw_text,
            prompt_messages,
            parsed_candidate,
            ai_message,
            status,
            error,
            generated_at,
            artifact_dir,
            artifact_stem,
        )
    return {
        "ai_message": ai_message,
        "status": status,
        "error": error,
        "prompt_messages": prompt_messages,
    }


def stream_ai_message(
    model_config: str,
    messages: list[dict],
    tools_schema: list[dict],
    mode: str = "prompt_json",
    artifact_dir: str | None = None,
    artifact_stem: str | None = None,
) -> Iterator[dict]:
    config_path, config = _load_model_config(model_config)
    messages = validate_messages(deepcopy(messages))
    if not isinstance(tools_schema, list):
        raise ValueError("tools_schema must be an array")
    generated_at = now_iso()
    source = "mock" if mode == "mock" else _llm_source(config)
    backend = "mock" if mode == "mock" else source
    prompt_messages = None
    parsed_candidate = None
    status = "success"
    error = None

    if mode == "mock":
        ai_message = _mock_generate(messages)
        parsed_candidate = {
            "content": ai_message["content"],
            "tool_calls": ai_message["tool_calls"],
            "control": ai_message["control"],
        }
        raw_text = json.dumps(parsed_candidate, ensure_ascii=False)
        if ai_message["content"]:
            yield {"type": "delta", "text": ai_message["content"]}
    elif mode == "prompt_json":
        prompt_messages = _build_prompt_messages(messages, tools_schema)
        if source == "fastapi":
            raw_parts = []
            emitted_chars = 0
            for chunk in _fastapi_prompt_json_stream(config_path, config, messages, tools_schema):
                raw_parts.append(chunk)
                content = _streaming_content_prefix("".join(raw_parts))
                if len(content) > emitted_chars:
                    delta = content[emitted_chars:]
                    emitted_chars = len(content)
                    if delta:
                        yield {"type": "delta", "text": delta}
            raw_text = "".join(raw_parts)
        elif source == "local":
            raw_text = _prompt_json_generate(config_path, config, messages, tools_schema)
        else:
            raise ValueError("runtime.llm_source must be local or fastapi")
        try:
            parsed_candidate, ai_message = _parse_model_output(raw_text)
            if source == "local" and ai_message["content"]:
                yield {"type": "delta", "text": ai_message["content"]}
        except Exception as exc:
            ai_message = make_ai_message(PARSE_ERROR_CONTENT, [])
            status = "error"
            error = {"type": type(exc).__name__, "message": str(exc)}
    else:
        raise ValueError("mode must be mock or prompt_json")

    _write_generation_artifacts(
        mode,
        backend,
        source,
        raw_text,
        prompt_messages,
        parsed_candidate,
        ai_message,
        status,
        error,
        generated_at,
        artifact_dir,
        artifact_stem,
    )
    yield {
        "type": "done",
        "result": {
            "ai_message": ai_message,
            "status": status,
            "error": error,
            "prompt_messages": prompt_messages,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate one AIMessage with a local or mock LLM.")
    parser.add_argument("--model_config", required=True)
    parser.add_argument("--messages", required=True)
    parser.add_argument("--tools_schema", required=True)
    parser.add_argument("--mode", choices=["mock", "prompt_json"], required=True)
    parser.add_argument("--outdir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outdir = resolve_cli_path(args.outdir)
        generate_ai_message(
            str(resolve_cli_path(args.model_config)),
            read_json(resolve_cli_path(args.messages)),
            read_json(resolve_cli_path(args.tools_schema)),
            args.mode,
            str(outdir),
        )
        print(outdir / "ai_message.json")
        return 0
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
