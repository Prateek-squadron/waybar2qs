"""JSONC (JSON with comments and trailing commas) parser and Waybar config loader."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def _strip_comments(text: str) -> str:
    """Strip // and /* */ comments outside double-quoted strings, preserving line numbers."""
    out: list[str] = []
    n = len(text)
    i = 0
    line = 1
    col = 1

    in_string = False
    escaped = False

    while i < n:
        ch = text[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            col += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                # Line comment: consume until newline, preserve newline.
                i += 2
                col += 2
                while i < n and text[i] != "\n":
                    i += 1
                    col += 1
                continue
            if nxt == "*":
                start_line = line
                start_col = col
                out.append("  ")
                i += 2
                col += 2
                closed = False
                while i < n:
                    c = text[i]
                    if c == "*" and i + 1 < n and text[i + 1] == "/":
                        out.append("  ")
                        i += 2
                        col += 2
                        closed = True
                        break
                    if c == "\n":
                        out.append("\n")
                        line += 1
                        col = 1
                    else:
                        out.append(" ")
                        col += 1
                    i += 1
                if not closed:
                    raise ValueError(
                        f"Unterminated block comment starting at line {start_line}, column {start_col}"
                    )
                continue

        out.append(ch)
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1
        i += 1

    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Strip trailing commas before } or ] outside double-quoted strings."""
    out: list[str] = []
    n = len(text)
    i = 0
    in_string = False
    escaped = False

    while i < n:
        ch = text[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in ("}", "]"):
                # Replace trailing comma with space so line/col offsets remain intact.
                out.append(" ")
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def parse_jsonc(text: str) -> Any:
    """Parse JSONC text (comments + trailing commas) into Python objects.

    Raises ValueError with line and column information on invalid syntax.
    """
    if text.startswith("\ufeff"):
        text = text[1:]

    cleaned = _strip_trailing_commas(_strip_comments(text))
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSONC at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _merge_config_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge overlay dict into base dict, letting overlay keys win without mutating inputs."""
    merged = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _merge_config_dicts(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _resolve_includes_for_dict(
    data: dict[str, Any],
    base_dir: Path,
    stack: frozenset[Path],
    warnings: list[str],
) -> dict[str, Any]:
    """Resolve Waybar 'include' entries for a config dict without overwriting explicit keys."""
    explicit = {k: v for k, v in data.items() if k != "include"}
    includes_raw = data.get("include")
    if includes_raw is None:
        return explicit

    if isinstance(includes_raw, str):
        include_list = [includes_raw]
    elif isinstance(includes_raw, list):
        include_list = [item for item in includes_raw if isinstance(item, str)]
        if len(include_list) != len(includes_raw):
            warnings.append("Ignored non-string entry in Waybar 'include' list.")
    else:
        warnings.append("Ignored invalid 'include' value (expected string or list of strings).")
        return explicit

    merged_includes: dict[str, Any] = {}
    for inc in include_list:
        inc_path = Path(inc).expanduser()
        if not inc_path.is_absolute():
            inc_path = base_dir / inc_path
        resolved = inc_path.resolve()

        if resolved in stack:
            warnings.append(f"Detected circular 'include' reference: {inc_path}")
            continue

        if not resolved.is_file():
            warnings.append(f"Included Waybar config not found: {inc_path}")
            continue

        try:
            inc_text = resolved.read_text(encoding="utf-8")
            inc_parsed = parse_jsonc(inc_text)
        except (OSError, ValueError) as exc:
            warnings.append(f"Failed to load included config '{inc_path}': {exc}")
            continue

        if isinstance(inc_parsed, list):
            if len(inc_parsed) == 1 and isinstance(inc_parsed[0], dict):
                inc_parsed = inc_parsed[0]
            else:
                warnings.append(
                    f"Included config '{inc_path}' has a top-level list; expected an object."
                )
                continue
        elif not isinstance(inc_parsed, dict):
            warnings.append(
                f"Included config '{inc_path}' did not parse to a JSON object."
            )
            continue

        resolved_inc = _resolve_includes_for_dict(
            inc_parsed,
            resolved.parent,
            stack | {resolved},
            warnings,
        )
        merged_includes = _merge_config_dicts(merged_includes, resolved_inc)

    return _merge_config_dicts(merged_includes, explicit)


def load_waybar_config(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load a Waybar config/config.jsonc file and resolve any 'include' files.

    Returns (bars_raw, warnings) where bars_raw is a list of bar config dicts.
    """
    resolved_root = path.expanduser().resolve()
    text = resolved_root.read_text(encoding="utf-8")
    parsed = parse_jsonc(text)
    warnings: list[str] = []

    if isinstance(parsed, dict):
        raw_bars = [parsed]
    elif isinstance(parsed, list):
        if not all(isinstance(item, dict) for item in parsed):
            raise ValueError(
                f"Waybar config '{path}' top-level array must contain only objects."
            )
        raw_bars = parsed
    else:
        raise ValueError(
            f"Waybar config '{path}' must be a JSON object or array of objects."
        )

    stack = frozenset({resolved_root})
    resolved_bars = [
        _resolve_includes_for_dict(bar, resolved_root.parent, stack, warnings)
        for bar in raw_bars
    ]
    return resolved_bars, warnings
