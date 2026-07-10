from __future__ import annotations

from skills import format_workspace_source, resolve_workspace_path


SUPPORTED_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".py",
    ".log",
}
MAX_CHARS_LIMIT = 50000


def _slice_lines(text: str, start_line: int | None, end_line: int | None) -> tuple[str, int, int, int]:
    lines = text.splitlines()
    line_count = len(lines)
    if line_count == 0:
        return "", 0, 0, 0
    start = 1 if start_line is None else start_line
    end = line_count if end_line is None else end_line
    if not isinstance(start, int) or isinstance(start, bool) or start <= 0:
        raise ValueError("start_line must be a positive integer")
    if not isinstance(end, int) or isinstance(end, bool) or end <= 0:
        raise ValueError("end_line must be a positive integer")
    if start > end:
        raise ValueError("start_line must not be greater than end_line")
    selected = lines[start - 1 : end]
    return "\n".join(selected), start, min(end, line_count), line_count


def file_reader(
    path: str,
    max_chars: int = 2000,
    start_line: int | None = None,
    end_line: int | None = None,
    *,
    data_root: str | None = None,
    allowed_roots: dict[str, str] | None = None,
    default_root: str = "data",
) -> dict:
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if max_chars > MAX_CHARS_LIMIT:
        raise ValueError(f"max_chars must not exceed {MAX_CHARS_LIMIT}")
    source, root, root_alias = resolve_workspace_path(
        path,
        data_root=data_root,
        allowed_roots=allowed_roots,
        default_root=default_root,
    )
    if source.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_TEXT_SUFFIXES))
        raise ValueError(f"file_reader only supports text-like files: {supported}")
    if not source.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    original = source.read_text(encoding="utf-8")
    selected_text, actual_start, actual_end, line_count = _slice_lines(original, start_line, end_line)
    content = selected_text[:max_chars]
    source_text, relative_path = format_workspace_source(source, root, root_alias)
    return {
        "content": content,
        "num_chars": len(content),
        "source": source_text,
        "relative_path": relative_path,
        "root_alias": root_alias,
        "suffix": source.suffix.lower(),
        "line_count": line_count,
        "line_start": actual_start,
        "line_end": actual_end,
        "truncated": len(selected_text) > len(content),
    }
