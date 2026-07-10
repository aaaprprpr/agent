from __future__ import annotations

import json
import threading
from queue import Empty
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_CONFIG_PATH = PROJECT_ROOT / "configs" / "model.yaml"
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8012
API_KEY: str | None = None
_MODEL_CACHE: dict[tuple[str, ...], tuple[Any, Any]] = {}


app = FastAPI(title="B4 Raw LLM FastAPI Server", version="1.0.0")


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


def _model_cache_key(
    model_path: Path,
    tokenizer_path: Path,
    local_only: bool,
    trust_remote_code: bool,
    dtype: Any,
    device_map: Any,
    max_memory: Any,
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
    )


def _load_model_bundle(
    auto_model: Any,
    auto_tokenizer: Any,
    model_path: Path,
    tokenizer_path: Path,
    local_only: bool,
    trust_remote_code: bool,
    dtype: Any,
    device_map: Any,
    max_memory: Any,
) -> tuple[Any, Any]:
    cache_key = _model_cache_key(
        model_path,
        tokenizer_path,
        local_only,
        trust_remote_code,
        dtype,
        device_map,
        max_memory,
    )
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached
    tokenizer = auto_tokenizer.from_pretrained(
        str(tokenizer_path),
        local_files_only=local_only,
        trust_remote_code=trust_remote_code,
    )
    model = auto_model.from_pretrained(
        str(model_path),
        local_files_only=local_only,
        trust_remote_code=trust_remote_code,
        dtype=dtype,
        device_map=device_map,
        max_memory=max_memory,
    )
    _MODEL_CACHE[cache_key] = (tokenizer, model)
    return tokenizer, model


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
    for name in ("temperature", "top_p", "top_k", "repetition_penalty"):
        if name in options:
            result[name] = options[name]
    return result


class RawModelServer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._loaded_key: str | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None

    def load(self) -> tuple[Any, Any, Any]:
        path = _model_config_path()
        key = str(path)
        with self._lock:
            if self._loaded_key == key and self._tokenizer is not None and self._model is not None:
                return self._tokenizer, self._model, self._torch

            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
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
            tokenizer, model = _load_model_bundle(
                AutoModelForCausalLM,
                AutoTokenizer,
                model_path,
                tokenizer_path,
                bool(model_config.get("local_files_only", True)),
                bool(model_config.get("trust_remote_code", False)),
                dtype,
                model_config.get("device_map", "auto"),
                model_config.get("max_memory"),
            )
            model.eval()
            self._loaded_key = key
            self._tokenizer = tokenizer
            self._model = model
            self._torch = torch
            return tokenizer, model, torch

    def generate(self, messages: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
        tokenizer, model, torch = self.load()
        with self._generate_lock:
            inputs = self._apply_chat_template(tokenizer, messages)
            device = next(model.parameters()).device
            inputs = inputs.to(device)
            input_length = int(inputs["input_ids"].shape[-1])
            if getattr(tokenizer, "pad_token_id", None) is not None:
                options.setdefault("pad_token_id", tokenizer.pad_token_id)
            elif getattr(tokenizer, "eos_token_id", None) is not None:
                options.setdefault("pad_token_id", tokenizer.eos_token_id)
            with torch.no_grad():
                generated = model.generate(**inputs, **options)
            new_tokens = generated[0][input_length:]
            raw_text = tokenizer.decode(new_tokens, skip_special_tokens=True)
            return {
                "raw_text": raw_text,
                "usage": {
                    "prompt_tokens": input_length,
                    "completion_tokens": int(new_tokens.shape[-1]),
                    "total_tokens": input_length + int(new_tokens.shape[-1]),
                },
            }

    def generate_stream(self, messages: list[dict[str, Any]], options: dict[str, Any]) -> Iterator[str]:
        tokenizer, model, torch = self.load()
        try:
            from transformers import TextIteratorStreamer
        except ImportError as exc:
            raise RuntimeError("transformers TextIteratorStreamer is required for streaming") from exc

        with self._generate_lock:
            inputs = self._apply_chat_template(tokenizer, messages)
            device = next(model.parameters()).device
            inputs = inputs.to(device)
            if getattr(tokenizer, "pad_token_id", None) is not None:
                options.setdefault("pad_token_id", tokenizer.pad_token_id)
            elif getattr(tokenizer, "eos_token_id", None) is not None:
                options.setdefault("pad_token_id", tokenizer.eos_token_id)

            streamer = TextIteratorStreamer(
                tokenizer,
                skip_prompt=True,
                skip_special_tokens=True,
                timeout=1.0,
            )
            generation_options = dict(options)
            generation_options["streamer"] = streamer
            errors: list[BaseException] = []

            def run_generation() -> None:
                try:
                    with torch.no_grad():
                        model.generate(**inputs, **generation_options)
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run_generation, daemon=True)
            worker.start()
            while worker.is_alive():
                try:
                    chunk = next(streamer)
                except Empty:
                    continue
                except StopIteration:
                    break
                if chunk:
                    yield chunk
            worker.join()
            while True:
                try:
                    chunk = next(streamer)
                except (Empty, StopIteration):
                    break
                if chunk:
                    yield chunk
            if errors:
                yield f"\n[stream_error] {type(errors[0]).__name__}: {errors[0]}"

    @staticmethod
    def _apply_chat_template(tokenizer: Any, messages: list[dict[str, Any]]) -> Any:
        kwargs = {
            "tokenize": True,
            "add_generation_prompt": True,
            "return_tensors": "pt",
            "return_dict": True,
        }
        try:
            return tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
        except TypeError:
            return tokenizer.apply_chat_template(messages, **kwargs)


MODEL_SERVER = RawModelServer()


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "b4_raw_llm",
        "endpoints": ["/health", "/generate", "/generate_stream"],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "b4_raw_llm",
        "model_config": str(_model_config_path()),
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


@app.post("/generate_stream")
def generate_stream(payload: dict[str, Any], request: Request) -> StreamingResponse:
    _check_auth(request)
    try:
        messages = _validate_messages(payload.get("messages"))
        options = _validate_generation_options(payload.get("generation"))
        stream = MODEL_SERVER.generate_stream(messages, options)
        return StreamingResponse(stream, media_type="text/plain; charset=utf-8")
    except ValueError as exc:
        raise _api_error(400, str(exc), "invalid_request_error") from exc
    except Exception as exc:
        raise _api_error(500, str(exc), "server_error") from exc


def main() -> int:
    import uvicorn

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
