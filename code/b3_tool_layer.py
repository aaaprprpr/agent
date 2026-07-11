from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any

from common.io_utils import append_jsonl, read_json, read_yaml, write_json
from common.logging_utils import now_iso
from common.path_utils import bootstrap_project_root, resolve_cli_path, resolve_from_file
from common.schemas import make_skill_result, make_tool_message, normalize_tool_call


bootstrap_project_root()


JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}

PYTHON_TO_JSON_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}

INJECTED_PARAMETERS = {"data_root", "output_dir", "allowed_roots", "default_root"}


def _load_tools_config(tools_config: str | Path) -> tuple[Path, dict]:
    config_path = Path(tools_config).resolve()
    config = read_yaml(config_path)
    if not isinstance(config, dict):
        raise ValueError("tools.yaml must contain an object")
    if not isinstance(config.get("tools"), dict) or not isinstance(config.get("toolsets"), dict):
        raise ValueError("tools.yaml must define tools and toolsets")
    return config_path, config


def _resolve_toolset(config: dict, toolset: str | None) -> tuple[str, list[str]]:
    selected = toolset or config.get("default_toolset")
    if not isinstance(selected, str) or selected not in config["toolsets"]:
        raise ValueError(f"toolset does not exist: {selected}")
    names = config["toolsets"][selected]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError(f"toolset {selected} must be a list of tool names")
    return selected, names


def _load_tool_function(tool: dict) -> Any:
    module = importlib.import_module(tool["module"])
    return getattr(module, tool["function"])


def _annotation_to_json_type(annotation: Any, default: Any = inspect._empty) -> str:
    if annotation in PYTHON_TO_JSON_TYPES:
        return PYTHON_TO_JSON_TYPES[annotation]
    origin = getattr(annotation, "__origin__", None)
    if origin in PYTHON_TO_JSON_TYPES:
        return PYTHON_TO_JSON_TYPES[origin]
    if default is not inspect._empty and default is not None:
        for python_type, json_type in PYTHON_TO_JSON_TYPES.items():
            if python_type is int and isinstance(default, bool):
                continue
            if isinstance(default, python_type):
                return json_type
    return "string"


def _tool_with_inferred_schema(tool: dict) -> tuple[dict, dict]:
    enriched = deepcopy(tool)
    parameters = deepcopy(enriched.get("parameters", {}))
    required = list(enriched.get("required", []))
    inference = {
        "schema_source": "yaml",
        "auto_inferred_parameters": [],
        "code_signature": None,
        "error": None,
    }
    if not isinstance(parameters, dict):
        parameters = {}
    try:
        function = _load_tool_function(enriched)
        signature = inspect.signature(function)
        inference["code_signature"] = f"{enriched['module']}.{enriched['function']}{signature}"
        for name, parameter in signature.parameters.items():
            if name in INJECTED_PARAMETERS or parameter.kind in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }:
                continue
            if name not in parameters:
                schema = {
                    "type": _annotation_to_json_type(parameter.annotation, parameter.default),
                    "description": "根据函数签名自动推断。",
                }
                if schema["type"] == "array":
                    schema["items"] = {"type": "string"}
                parameters[name] = schema
                inference["auto_inferred_parameters"].append(name)
            if parameter.default is inspect._empty and name not in required:
                required.append(name)
        if inference["auto_inferred_parameters"]:
            inference["schema_source"] = "yaml+python_signature"
    except Exception as exc:
        inference["error"] = {"type": type(exc).__name__, "message": str(exc)}
    enriched["parameters"] = parameters
    enriched["required"] = required
    return enriched, inference


def _parameter_schema(tool: dict) -> dict:
    raw_parameters = tool.get("parameters", {})
    if not isinstance(raw_parameters, dict):
        raise ValueError("tool parameters must be an object")
    properties = {}
    for name, definition in raw_parameters.items():
        if not isinstance(definition, dict) or definition.get("type") not in JSON_TYPES:
            raise ValueError(f"invalid parameter schema for {name}")
        properties[name] = dict(definition)
    required = tool.get("required", [])
    if not isinstance(required, list) or not all(name in properties for name in required):
        raise ValueError("required parameters must reference declared properties")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def get_tools_schema(
    tools_config: str,
    toolset: str,
    outdir: str | None = None,
) -> list[dict]:
    _, config = _load_tools_config(tools_config)
    selected, tool_names = _resolve_toolset(config, toolset)
    schema = []
    details = []
    for name in tool_names:
        tool = config["tools"].get(name)
        if not isinstance(tool, dict):
            raise ValueError(f"toolset references missing tool: {name}")
        for field in ("module", "function", "description", "returns"):
            if field not in tool:
                raise ValueError(f"tool {name} missing {field}")
        returns = tool["returns"]
        if not isinstance(returns, dict):
            raise ValueError(f"tool {name} returns must be an object")
        enriched_tool, inference = _tool_with_inferred_schema(tool)
        schema.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": _parameter_schema(enriched_tool),
                    "x-returns": {"type": "object", "properties": returns},
                },
            }
        )
        details.append({"name": name, **inference})
    if outdir:
        output_dir = Path(outdir)
        write_json(schema, output_dir / "tools_schema.json")
        write_json(
            {
                "status": "success",
                "toolset": selected,
                "tool_count": len(schema),
                "tools": tool_names,
                "schema_details": details,
            },
            output_dir / "tool_schema_report.json",
        )
    return schema


def _validate_args(args: dict, definition: dict) -> None:
    parameter_schema = _parameter_schema(definition)
    properties = parameter_schema["properties"]
    missing = [name for name in parameter_schema["required"] if name not in args]
    if missing:
        raise ValueError(f"missing required parameters: {', '.join(missing)}")
    unknown = sorted(set(args) - set(properties))
    if unknown:
        raise ValueError(f"unknown parameters: {', '.join(unknown)}")
    for name, value in args.items():
        expected_name = properties[name]["type"]
        expected = JSON_TYPES[expected_name]
        if expected_name in {"integer", "number"} and isinstance(value, bool):
            valid = False
        else:
            valid = isinstance(value, expected)
        if not valid:
            raise ValueError(f"parameter {name} must be {expected_name}")
        if expected_name == "array" and "items" in properties[name]:
            item_type = properties[name]["items"].get("type")
            if item_type in JSON_TYPES and not all(isinstance(item, JSON_TYPES[item_type]) for item in value):
                raise ValueError(f"parameter {name} contains invalid items")


def _error_result(name: str, args: dict, exc: Exception, latency_ms: float = 0.0) -> dict:
    return make_skill_result(
        name,
        "error",
        args,
        None,
        {"type": type(exc).__name__, "message": str(exc)},
        latency_ms,
    )


def _retry_settings(config: dict, definition: dict) -> tuple[int, set[str]]:
    retry_config = config.get("settings", {}).get("retry", {})
    if not isinstance(retry_config, dict):
        retry_config = {}
    max_attempts = int(definition.get("max_attempts", retry_config.get("max_attempts", 1)))
    if definition.get("side_effects"):
        max_attempts = 1
    max_attempts = max(1, max_attempts)
    recoverable = retry_config.get("recoverable_errors", ["OSError", "TimeoutError", "ConnectionError"])
    if not isinstance(recoverable, list):
        recoverable = []
    return max_attempts, {str(name) for name in recoverable}


def _cache_settings(config: dict, output_dir: Path | None) -> tuple[bool, set[str]]:
    cache_config = config.get("settings", {}).get("cache", {})
    if not isinstance(cache_config, dict):
        cache_config = {}
    enabled = bool(cache_config.get("enabled", False)) and output_dir is not None
    cacheable = cache_config.get("cacheable_tools", [])
    if not isinstance(cacheable, list):
        cacheable = []
    return enabled, {str(name) for name in cacheable}


def _read_cache(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        cache = read_json(path)
    except Exception:
        return {}
    return cache if isinstance(cache, dict) else {}


def _cache_key(name: str, args: dict, context: dict | None = None) -> str:
    raw = json.dumps(
        {"name": name, "args": args, "context": context or {}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _workspace_root_settings(config: dict, config_path: Path, resolved_data_root: Path) -> tuple[dict[str, str], str]:
    settings = config.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    configured = settings.get("workspace_roots", {})
    roots: dict[str, str] = {"data": str(resolved_data_root)}
    if isinstance(configured, dict):
        for alias, raw_path in configured.items():
            if not isinstance(alias, str) or not isinstance(raw_path, str):
                continue
            normalized_alias = alias.strip()
            if not normalized_alias.replace("_", "").replace("-", "").isalnum():
                continue
            roots[normalized_alias] = str(resolve_from_file(raw_path, config_path))
    default_root = settings.get("default_workspace_root", "data")
    if not isinstance(default_root, str) or default_root not in roots:
        default_root = "data"
    return roots, default_root


def _run_configured_tool(
    name: str,
    args: dict,
    definition: dict,
    resolved_data_root: Path,
    allowed_roots: dict[str, str],
    default_root: str,
    output_dir: Path | None,
) -> Any:
    function = _load_tool_function(definition)
    kwargs = dict(args)
    signature = inspect.signature(function)
    if "data_root" in signature.parameters:
        kwargs["data_root"] = str(resolved_data_root)
    if "allowed_roots" in signature.parameters:
        kwargs["allowed_roots"] = allowed_roots
    if "default_root" in signature.parameters:
        kwargs["default_root"] = default_root
    if "output_dir" in signature.parameters:
        kwargs["output_dir"] = str(output_dir) if output_dir else None
    return function(**kwargs)


def _stats_from_records(records: list[dict]) -> dict:
    by_tool: dict[str, dict] = {}
    for record in records:
        name = record["name"]
        entry = by_tool.setdefault(
            name,
            {
                "count": 0,
                "success_count": 0,
                "error_count": 0,
                "cache_hit_count": 0,
                "latency_ms_total": 0.0,
            },
        )
        entry["count"] += 1
        if record["status"] == "success":
            entry["success_count"] += 1
        else:
            entry["error_count"] += 1
        if record.get("cache_hit"):
            entry["cache_hit_count"] += 1
        entry["latency_ms_total"] += float(record.get("latency_ms") or 0.0)
    for entry in by_tool.values():
        count = entry["count"] or 1
        entry["avg_latency_ms"] = round(entry["latency_ms_total"] / count, 3)
        entry["failure_rate"] = round(entry["error_count"] / count, 4)
        entry.pop("latency_ms_total", None)
    return {
        "generated_at": now_iso(),
        "total_calls": len(records),
        "success_count": sum(1 for record in records if record["status"] == "success"),
        "error_count": sum(1 for record in records if record["status"] == "error"),
        "cache_hit_count": sum(1 for record in records if record.get("cache_hit")),
        "by_tool": by_tool,
    }


def execute_tool_calls(
    tool_calls: list[dict],
    tools_config: str,
    toolset: str | None = None,
    outdir: str | None = None,
) -> list[dict]:
    config_path, config = _load_tools_config(tools_config)
    selected, allowed_tools = _resolve_toolset(config, toolset)
    if not isinstance(tool_calls, list):
        raise ValueError("tool_calls must be a list")
    data_root_setting = config.get("settings", {}).get("data_root", "../data")
    resolved_data_root = resolve_from_file(data_root_setting, config_path)
    allowed_roots, default_root = _workspace_root_settings(config, config_path, resolved_data_root)
    tool_context = {
        "data_root": str(resolved_data_root),
        "allowed_roots": allowed_roots,
        "default_root": default_root,
    }
    tool_messages = []
    log_records = []
    output_dir = Path(outdir) if outdir else None
    cache_enabled, cacheable_tools = _cache_settings(config, output_dir)
    cache_path = output_dir / "tool_result_cache.json" if output_dir else None
    cache = _read_cache(cache_path) if cache_enabled and cache_path else {}
    cache_dirty = False
    for index, raw_call in enumerate(tool_calls):
        start = perf_counter()
        attempts_used = 0
        cache_hit = False
        try:
            call = normalize_tool_call(raw_call, index)
        except Exception as exc:
            call = {"id": f"call_{index + 1:03d}", "name": "unknown", "args": {}}
            result = _error_result(call["name"], call["args"], exc)
        else:
            name = call["name"]
            args = call["args"]
            if name not in allowed_tools or name not in config["tools"]:
                result = _error_result(name, args, ValueError(f"tool is not available in {selected}: {name}"))
            else:
                definition, _ = _tool_with_inferred_schema(config["tools"][name])
                try:
                    _validate_args(args, definition)
                    key = _cache_key(name, args, tool_context)
                    if cache_enabled and name in cacheable_tools and key in cache:
                        cached = cache[key]
                        if isinstance(cached, dict) and isinstance(cached.get("skill_result"), dict):
                            result = deepcopy(cached["skill_result"])
                            result["latency_ms"] = 0.0
                            cache_hit = True
                        else:
                            raise ValueError("invalid cached tool result")
                    else:
                        max_attempts, recoverable_errors = _retry_settings(config, definition)
                        last_exc: Exception | None = None
                        for attempt in range(1, max_attempts + 1):
                            attempts_used = attempt
                            try:
                                output = _run_configured_tool(
                                    name,
                                    args,
                                    definition,
                                    resolved_data_root,
                                    allowed_roots,
                                    default_root,
                                    output_dir,
                                )
                                latency_ms = round((perf_counter() - start) * 1000, 3)
                                result = make_skill_result(name, "success", args, output, None, latency_ms)
                                if cache_enabled and name in cacheable_tools:
                                    cache[key] = {
                                        "created_at": now_iso(),
                                        "skill_result": result,
                                    }
                                    cache_dirty = True
                                break
                            except Exception as exc:
                                last_exc = exc
                                if type(exc).__name__ not in recoverable_errors or attempt >= max_attempts:
                                    raise
                        else:
                            raise last_exc or RuntimeError("tool execution failed")
                except Exception as exc:
                    latency_ms = round((perf_counter() - start) * 1000, 3)
                    result = _error_result(name, args, exc, latency_ms)
        content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        message = make_tool_message(call["id"], call["name"], content, result["status"])
        tool_messages.append(message)
        log_records.append(
            {
                "timestamp": now_iso(),
                "toolset": selected,
                "tool_call_id": call["id"],
                "name": call["name"],
                "status": result["status"],
                "args": call["args"],
                "skill_result": result,
                "latency_ms": result["latency_ms"],
                "attempts": attempts_used,
                "cache_hit": cache_hit,
                "allowed_roots": allowed_roots,
            }
        )
    if outdir:
        write_json(tool_messages, output_dir / "tool_messages.json")
        for record in log_records:
            append_jsonl(record, output_dir / "tool_call_log.jsonl")
        write_json(_stats_from_records(log_records), output_dir / "tool_stats.json")
        if cache_enabled and cache_dirty and cache_path:
            write_json(cache, cache_path)
    return tool_messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate tool schema or execute tool calls.")
    parser.add_argument("--tools_config", required=True)
    parser.add_argument("--toolset", default=None)
    parser.add_argument("--tool_calls")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--export_schema", action="store_true")
    action.add_argument("--execute", action="store_true")
    parser.add_argument("--outdir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config_path = resolve_cli_path(args.tools_config)
        outdir = resolve_cli_path(args.outdir)
        if args.export_schema:
            if not args.toolset:
                _, config = _load_tools_config(config_path)
                args.toolset = config.get("default_toolset")
            get_tools_schema(str(config_path), args.toolset, str(outdir))
            print(outdir / "tools_schema.json")
        else:
            if not args.tool_calls:
                raise ValueError("--tool_calls is required with --execute")
            payload = read_json(resolve_cli_path(args.tool_calls))
            tool_calls = payload.get("tool_calls") if isinstance(payload, dict) else payload
            execute_tool_calls(tool_calls, str(config_path), args.toolset, str(outdir))
            print(outdir / "tool_messages.json")
        return 0
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
