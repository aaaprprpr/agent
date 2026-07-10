from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_CONFIG_PATH = PROJECT_ROOT / "configs" / "model.yaml"
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8012
MODEL_CONFIG_PATH = DEFAULT_MODEL_CONFIG_PATH
API_KEY: str | None = os.environ.get("B4_LLM_API_KEY") or None

_MODEL_CACHE: dict[tuple[str, ...], tuple[Any, Any, str]] = {}


app = FastAPI(title="B4 Raw LLM FastAPI Server", version="2.0.0")


def read_yaml(path: str | Path) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required; install requirements.txt") from exc
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def resolve_path(path: str | Path, base_dir: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base_dir) / candidate
    return candidate.resolve()


def resolve_from_file(path: str | Path, containing_file: str | Path) -> Path:
    return resolve_path(path, Path(containing_file).resolve().parent)


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


def _select_loader(transformers_module: Any, model_path: Path, model_config: dict[str, Any]) -> tuple[Any, Any, str]:
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


def _from_pretrained_with_dtype(cls: Any, path: Path, kwargs: dict[str, Any], dtype: Any) -> Any:
    try:
        return cls.from_pretrained(str(path), dtype=dtype, **kwargs)
    except TypeError:
        return cls.from_pretrained(str(path), torch_dtype=dtype, **kwargs)


def _load_model_bundle(
    model_path: Path,
    tokenizer_path: Path,
    local_only: bool,
    trust_remote_code: bool,
    dtype: Any,
    device_map: Any,
    max_memory: Any,
    model_config: dict[str, Any],
) -> tuple[Any, Any, str]:
    import transformers

    processor_cls, model_cls, loader_name = _select_loader(transformers, model_path, model_config)
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
        return cached

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
    _MODEL_CACHE[cache_key] = (processor, model, loader_name)
    return processor, model, loader_name


def _api_error(status_code: int, message: str, error_type: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": None,
            }
        },
    )


@app.exception_handler(HTTPException)
def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": str(exc.detail),
                "type": "server_error",
                "param": None,
                "code": None,
            }
        },
    )


def _check_auth(request: Request) -> None:
    if not API_KEY:
        return
    if request.headers.get("authorization", "") != f"Bearer {API_KEY}":
        raise _api_error(401, "invalid authorization token", "invalid_request_error")


def _model_config_path() -> Path:
    return Path(MODEL_CONFIG_PATH).expanduser().resolve()


def _load_config(path: Path) -> dict[str, Any]:
    config = read_yaml(path)
    if not isinstance(config, dict):
        raise ValueError("model.yaml must contain an object")
    return config


def _validate_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"message {index} must be an object")
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"message {index} has invalid role: {role}")
        if not isinstance(message.get("content", ""), str):
            raise ValueError(f"message {index} content must be a string")
    return messages


def _validate_generation_options(options: Any) -> dict[str, Any]:
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("generation must be an object")
    result = {
        "max_new_tokens": int(options.get("max_new_tokens", 1024)),
        "do_sample": bool(options.get("do_sample", False)),
    }
    if result["max_new_tokens"] <= 0:
        raise ValueError("generation.max_new_tokens must be positive")
    if result["do_sample"]:
        for name in ("temperature", "top_p", "top_k", "repetition_penalty"):
            if name in options and options[name] is not None:
                result[name] = options[name]
    return result


def _max_input_tokens(config: dict[str, Any]) -> int | None:
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


def _apply_chat_template(processor: Any, messages: list[dict[str, Any]]) -> Any:
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


class RawModelServer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._loaded_key: str | None = None
        self._processor: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._loader_name: str | None = None
        self._max_input_tokens: int | None = None

    def load(self) -> tuple[Any, Any, Any, str, int | None]:
        path = _model_config_path()
        key = str(path)
        with self._lock:
            if self._loaded_key == key and self._processor is not None and self._model is not None:
                return self._processor, self._model, self._torch, self._loader_name or "unknown", self._max_input_tokens

            try:
                import torch
            except ImportError as exc:
                raise RuntimeError("install torch and transformers before starting the server") from exc

            config = _load_config(path)
            model_config = config.get("model", {})
            if not isinstance(model_config, dict):
                raise ValueError("model config must contain a model object")
            model_setting = model_config.get("model_name_or_path")
            tokenizer_setting = model_config.get("tokenizer_name_or_path", model_setting)
            if not isinstance(model_setting, str) or not isinstance(tokenizer_setting, str):
                raise ValueError("model_name_or_path and tokenizer_name_or_path are required")

            model_path = resolve_from_file(model_setting, path)
            tokenizer_path = resolve_from_file(tokenizer_setting, path)
            if not model_path.exists() or not tokenizer_path.exists():
                raise FileNotFoundError(f"local model path does not exist: {model_path}")

            dtype = _dtype_value(torch, str(model_config.get("torch_dtype", "auto")))
            processor, model, loader_name = _load_model_bundle(
                model_path,
                tokenizer_path,
                bool(model_config.get("local_files_only", True)),
                bool(model_config.get("trust_remote_code", False)),
                dtype,
                model_config.get("device_map", "auto"),
                model_config.get("max_memory"),
                model_config,
            )
            model.eval()
            self._loaded_key = key
            self._processor = processor
            self._model = model
            self._torch = torch
            self._loader_name = loader_name
            self._max_input_tokens = _max_input_tokens(config)
            return processor, model, torch, loader_name, self._max_input_tokens

    def generate(self, messages: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
        processor, model, torch, loader_name, max_input_tokens = self.load()
        with self._generate_lock:
            inputs = _apply_chat_template(processor, messages)
            input_length = int(inputs["input_ids"].shape[-1])
            if max_input_tokens is not None and input_length > max_input_tokens:
                raise ValueError(
                    f"prompt has {input_length} tokens, exceeding context.max_input_tokens={max_input_tokens}"
                )
            device = next(model.parameters()).device
            inputs = _move_inputs_to_device(inputs, device)
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
            raw_text = _decode_new_tokens(processor, new_tokens)
            return {
                "raw_text": raw_text,
                "loader": loader_name,
                "usage": {
                    "prompt_tokens": input_length,
                    "completion_tokens": int(new_tokens.shape[-1]),
                    "total_tokens": input_length + int(new_tokens.shape[-1]),
                },
            }


MODEL_SERVER = RawModelServer()


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "b4_raw_llm",
        "endpoints": ["/health", "/generate"],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "b4_raw_llm",
        "model_config": str(_model_config_path()),
        "auth_enabled": bool(API_KEY),
    }


@app.post("/generate")
def generate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    _check_auth(request)
    try:
        messages = _validate_messages(payload.get("messages"))
        options = _validate_generation_options(payload.get("generation"))
        return MODEL_SERVER.generate(messages, options)
    except ValueError as exc:
        raise _api_error(400, str(exc), "invalid_request_error") from exc
    except Exception as exc:
        raise _api_error(500, str(exc), "server_error") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve Qwen/Transformers generation for B4 over FastAPI.")
    parser.add_argument("--model_config", default=str(DEFAULT_MODEL_CONFIG_PATH))
    parser.add_argument("--host", default=DEFAULT_SERVER_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    parser.add_argument(
        "--api_key",
        default=None,
        help="Optional bearer token. If omitted, B4_LLM_API_KEY environment variable is used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    global MODEL_CONFIG_PATH, API_KEY
    args = build_parser().parse_args(argv)
    MODEL_CONFIG_PATH = Path(args.model_config).expanduser().resolve()
    if args.api_key is not None:
        API_KEY = args.api_key or None

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
