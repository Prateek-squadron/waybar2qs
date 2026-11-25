"""Normalization layer converting raw Waybar dicts + ThemeTokens into BarSpec IR."""

from __future__ import annotations

import copy
import re
from dataclasses import fields
from typing import Any

from .ir import BarSpec, ModuleSpec, StyleProps, ThemeTokens

_VALID_POSITIONS = frozenset({"top", "bottom", "left", "right"})
_VALID_LAYERS = frozenset({"top", "bottom", "overlay", "background"})
_CANONICAL_MODULES = frozenset({
    "hyprland/workspaces",
    "niri/workspaces",
    "clock",
    "pulseaudio",
    "battery",
    "network",
    "tray",
})
_INHERITED_STYLE_FIELDS = ("font_family", "font_size", "font_weight", "color")


def _coerce_int(val: Any, default: int | None = None) -> int | None:
    if isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return int(round(val))
    if isinstance(val, str):
        cleaned = val.strip().lower().removesuffix("px")
        try:
            return int(round(float(cleaned)))
        except ValueError:
            return default
    return default


def _parse_margin_box(raw: Any) -> tuple[int, int, int, int] | None:
    """Parse Waybar 'margin' (int or 1-4 space-separated ints) into (top, right, bottom, left)."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        v = int(round(raw))
        return (v, v, v, v)
    if isinstance(raw, str):
        parts = [p for p in raw.strip().split() if p]
        if not (1 <= len(parts) <= 4):
            return None
        nums: list[int] = []
        for p in parts:
            n = _coerce_int(p)
            if n is None:
                return None
            nums.append(n)
        if len(nums) == 1:
            return (nums[0], nums[0], nums[0], nums[0])
        if len(nums) == 2:
            return (nums[0], nums[1], nums[0], nums[1])
        if len(nums) == 3:
            return (nums[0], nums[1], nums[2], nums[1])
        return (nums[0], nums[1], nums[2], nums[3])
    return None


def _normalize_outputs(raw: Any, bar_label: str, warnings: list[str]) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        val = raw.strip()
        return [val] if val else []
    if isinstance(raw, list):
        outputs: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                outputs.append(item.strip())
            else:
                warnings.append(
                    f"Bar '{bar_label}': ignored invalid entry {item!r} in 'output'."
                )
        return outputs
    warnings.append(f"Bar '{bar_label}': ignored invalid 'output' value {raw!r}.")
    return []


def _sanitize_instance_id(raw_name: str, used_ids: set[str]) -> str:
    """Build a unique QML-safe identifier from a Waybar module name."""
    base = re.sub(r"[^A-Za-z0-9_]+", "_", raw_name).strip("_")
    if not base:
        base = "module"
    if base[0].isdigit():
        base = f"m_{base}"

    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _resolve_module_kind(
    base_name: str,
    compositor: str,
    bar_label: str,
    warnings: list[str],
) -> str:
    """Determine canonical ModuleSpec.kind with compositor-aware mapping."""
    comp = compositor.strip().lower()

    if base_name.startswith("custom/"):
        return "custom"

    if base_name == "hyprland/workspaces":
        if comp == "niri":
            warnings.append(
                f"Bar '{bar_label}': module 'hyprland/workspaces' used with target compositor 'niri'."
            )
        return "hyprland/workspaces"

    if base_name == "niri/workspaces":
        if comp == "hyprland":
            warnings.append(
                f"Bar '{bar_label}': module 'niri/workspaces' used with target compositor 'hyprland'."
            )
        return "niri/workspaces"

    if base_name in _CANONICAL_MODULES:
        return base_name

    if base_name == "workspaces":
        if comp == "niri":
            return "niri/workspaces"
        if comp == "hyprland":
            return "hyprland/workspaces"
        warnings.append(
            f"Bar '{bar_label}': generic 'workspaces' module mapped to 'hyprland/workspaces' (pass compositor='niri' for Niri)."
        )
        return "hyprland/workspaces"

    if base_name in ("sway/workspaces", "river/tags", "dwl/tags"):
        if comp == "hyprland":
            warnings.append(
                f"Bar '{bar_label}': mapped '{base_name}' to 'hyprland/workspaces' for compositor 'hyprland'."
            )
            return "hyprland/workspaces"
        if comp == "niri":
            warnings.append(
                f"Bar '{bar_label}': mapped '{base_name}' to 'niri/workspaces' for compositor 'niri'."
            )
            return "niri/workspaces"
        warnings.append(
            f"Bar '{bar_label}': module '{base_name}' has no native Quickshell backend in '{compositor}' mode; emitting fallback."
        )
        return base_name

    return base_name


def _copy_style(src: StyleProps) -> StyleProps:
    return StyleProps(**{f.name: getattr(src, f.name) for f in fields(StyleProps)})


def _lookup_module_style(
    raw_name: str,
    base_name: str,
    kind: str,
    tokens: ThemeTokens,
) -> tuple[StyleProps, dict[str, StyleProps]]:
    """Resolve StyleProps and state styles for a module, inheriting global font/color defaults."""
    candidates: list[str] = [raw_name]
    if base_name not in candidates:
        candidates.append(base_name)
    if "#" in raw_name:
        dash_variant = raw_name.replace("#", "-")
        if dash_variant not in candidates:
            candidates.append(dash_variant)
    if kind in ("hyprland/workspaces", "niri/workspaces") or base_name in (
        "workspaces",
        "sway/workspaces",
    ):
        if "workspaces" not in candidates:
            candidates.append("workspaces")

    matched_style = StyleProps()
    for key in candidates:
        if key in tokens.module_styles:
            matched_style = _copy_style(tokens.module_styles[key])
            break

    # Cascade global -> bar -> module for font/foreground defaults.
    for attr in _INHERITED_STYLE_FIELDS:
        if getattr(matched_style, attr) is None:
            bar_val = getattr(tokens.bar_style, attr)
            global_val = getattr(tokens.global_style, attr)
            fallback = bar_val if bar_val is not None else global_val
            if fallback is not None:
                setattr(matched_style, attr, fallback)

    matched_states: dict[str, StyleProps] = {}
    for key in candidates:
        if key in tokens.state_styles:
            matched_states = {
                state: _copy_style(sp)
                for state, sp in tokens.state_styles[key].items()
            }
            break

    return matched_style, matched_states


def _normalize_section_modules(
    bar_raw: dict[str, Any],
    section_key: str,
    section_name: str,
    bar_label: str,
    tokens: ThemeTokens,
    compositor: str,
    used_ids: set[str],
    warnings: list[str],
) -> list[ModuleSpec]:
    raw_list = bar_raw.get(section_key)
    if raw_list is None:
        return []
    if not isinstance(raw_list, list):
        warnings.append(
            f"Bar '{bar_label}': expected list for '{section_key}', got {type(raw_list).__name__}."
        )
        return []

    modules: list[ModuleSpec] = []
    for entry in raw_list:
        if not isinstance(entry, str) or not entry.strip():
            warnings.append(
                f"Bar '{bar_label}': ignored invalid module entry {entry!r} in '{section_key}'."
            )
            continue

        raw_name = entry.strip()
        base_name, _, _ = raw_name.partition("#")
        kind = _resolve_module_kind(base_name, compositor, bar_label, warnings)
        instance_id = _sanitize_instance_id(raw_name, used_ids)

        # Config lookup: exact raw_name first, falling back to base_name.
        mod_cfg: dict[str, Any] = {}
        if raw_name in bar_raw:
            if isinstance(bar_raw[raw_name], dict):
                mod_cfg = copy.deepcopy(bar_raw[raw_name])
            else:
                warnings.append(
                    f"Bar '{bar_label}': config for '{raw_name}' is not an object; using defaults."
                )
        elif base_name in bar_raw:
            if isinstance(bar_raw[base_name], dict):
                mod_cfg = copy.deepcopy(bar_raw[base_name])
            else:
                warnings.append(
                    f"Bar '{bar_label}': config for '{base_name}' is not an object; using defaults."
                )

        style, states = _lookup_module_style(raw_name, base_name, kind, tokens)
        modules.append(
            ModuleSpec(
                raw_name=raw_name,
                kind=kind,
                instance_id=instance_id,
                section=section_name,
                config=mod_cfg,
                style=style,
                states=states,
            )
        )

    return modules


def build_bar_specs(
    bars_raw: list[dict[str, Any]],
    tokens: ThemeTokens,
    compositor: str = "auto",
) -> tuple[list[BarSpec], list[str]]:
    """Normalize raw Waybar bar dicts and ThemeTokens into BarSpec IR models."""
    specs: list[BarSpec] = []
    warnings: list[str] = []

    for idx, bar_raw in enumerate(bars_raw):
        raw_name = bar_raw.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            bar_name = raw_name.strip()
        else:
            bar_name = "main" if idx == 0 else f"bar_{idx}"

        raw_pos = bar_raw.get("position", "top")
        position = raw_pos.strip().lower() if isinstance(raw_pos, str) else "top"
        if position not in _VALID_POSITIONS:
            warnings.append(
                f"Bar '{bar_name}': unsupported position '{raw_pos}'; defaulting to 'top'."
            )
            position = "top"
        elif position in ("left", "right"):
            warnings.append(
                f"Bar '{bar_name}': vertical position '{position}' has limited layout support "
                "(horizontal RowLayout is default; ColumnLayout orientation may need manual QML adjustment)."
            )

        raw_layer = bar_raw.get("layer", "top")
        layer = raw_layer.strip().lower() if isinstance(raw_layer, str) else "top"
        if layer not in _VALID_LAYERS:
            warnings.append(
                f"Bar '{bar_name}': unknown layer '{raw_layer}'; defaulting to 'top'."
            )
            layer = "top"

        default_height = (
            tokens.bar_style.min_height
            if tokens.bar_style.min_height and tokens.bar_style.min_height > 0
            else 34
        )
        height = _coerce_int(bar_raw.get("height"), default=default_height)
        if height is None or height <= 0:
            if "height" in bar_raw:
                warnings.append(
                    f"Bar '{bar_name}': invalid height {bar_raw.get('height')!r}; using {default_height}px."
                )
            height = default_height

        width = _coerce_int(bar_raw.get("width"), default=None)
        if width is not None and width <= 0:
            warnings.append(
                f"Bar '{bar_name}': ignoring non-positive width {bar_raw.get('width')!r}."
            )
            width = None

        spacing = _coerce_int(bar_raw.get("spacing"), default=6)
        if spacing is None or spacing < 0:
            spacing = 6

        raw_exclusive = bar_raw.get("exclusive", True)
        exclusive = bool(raw_exclusive) if isinstance(raw_exclusive, bool) else True

        outputs = _normalize_outputs(bar_raw.get("output"), bar_name, warnings)

        m_top = m_right = m_bottom = m_left = 0
        if "margin" in bar_raw:
            parsed_margin = _parse_margin_box(bar_raw["margin"])
            if parsed_margin is not None:
                m_top, m_right, m_bottom, m_left = parsed_margin
            else:
                warnings.append(
                    f"Bar '{bar_name}': could not parse 'margin' value {bar_raw['margin']!r}."
                )

        m_top = _coerce_int(bar_raw.get("margin-top"), default=m_top) or 0
        m_right = _coerce_int(bar_raw.get("margin-right"), default=m_right) or 0
        m_bottom = _coerce_int(bar_raw.get("margin-bottom"), default=m_bottom) or 0
        m_left = _coerce_int(bar_raw.get("margin-left"), default=m_left) or 0

        used_ids: set[str] = set()
        modules_left = _normalize_section_modules(
            bar_raw, "modules-left", "left", bar_name, tokens, compositor, used_ids, warnings
        )
        modules_center = _normalize_section_modules(
            bar_raw, "modules-center", "center", bar_name, tokens, compositor, used_ids, warnings
        )
        modules_right = _normalize_section_modules(
            bar_raw, "modules-right", "right", bar_name, tokens, compositor, used_ids, warnings
        )

        specs.append(
            BarSpec(
                name=bar_name,
                position=position,
                layer=layer,
                height=height,
                width=width,
                spacing=spacing,
                exclusive=exclusive,
                outputs=outputs,
                margin_top=m_top,
                margin_right=m_right,
                margin_bottom=m_bottom,
                margin_left=m_left,
                modules_left=modules_left,
                modules_center=modules_center,
                modules_right=modules_right,
            )
        )

    return specs, warnings
