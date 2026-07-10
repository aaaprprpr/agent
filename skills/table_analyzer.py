from __future__ import annotations

import csv
import statistics

from skills import format_workspace_source, resolve_workspace_path


def table_analyzer(
    path: str,
    max_rows_preview: int = 5,
    describe: bool = True,
    *,
    data_root: str | None = None,
    allowed_roots: dict[str, str] | None = None,
    default_root: str = "data",
) -> dict:
    if not isinstance(max_rows_preview, int) or isinstance(max_rows_preview, bool) or max_rows_preview < 0:
        raise ValueError("max_rows_preview must be a non-negative integer")
    source, root, root_alias = resolve_workspace_path(
        path,
        data_root=data_root,
        allowed_roots=allowed_roots,
        default_root=default_root,
    )
    if source.suffix.lower() not in {".csv", ".tsv"}:
        raise ValueError("table_analyzer only supports .csv and .tsv files")
    if not source.is_file():
        raise FileNotFoundError(f"table file not found: {path}")
    delimiter = "\t" if source.suffix.lower() == ".tsv" else ","
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("table must contain a header row")
        rows = list(reader)
        columns = list(reader.fieldnames)
    column_profiles: dict[str, dict] = {}
    for column in columns:
        values = [row.get(column, "") for row in rows]
        stripped_values = [value.strip() for value in values]
        non_empty = [value for value in stripped_values if value != ""]
        column_profiles[column] = {
            "missing_count": len(stripped_values) - len(non_empty),
            "non_empty_count": len(non_empty),
            "unique_count": len(set(non_empty)),
        }
    stats: dict[str, dict] = {}
    if describe:
        for column in columns:
            raw_values = [row.get(column, "").strip() for row in rows if row.get(column, "").strip() != ""]
            if not raw_values:
                continue
            try:
                values = [float(value) for value in raw_values]
            except ValueError:
                continue
            column_stats = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
            }
            if len(values) >= 2:
                column_stats["stdev"] = statistics.stdev(values)
            stats[column] = column_stats
    source_text, relative_path = format_workspace_source(source, root, root_alias)
    return {
        "path": source_text,
        "relative_path": relative_path,
        "root_alias": root_alias,
        "num_rows": len(rows),
        "num_columns": len(columns),
        "columns": columns,
        "preview": rows[:max_rows_preview],
        "column_profiles": column_profiles,
        "describe": stats,
    }
