"""Intermediate representation (IR) and report models for waybar2qs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StyleProps:
    """Resolved QML-mappable CSS properties for a selector or module."""

    background: str | None = None
    color: str | None = None
    border_radius: int | None = None
    border_width: int | None = None
    border_color: str | None = None
    font_family: str | None = None
    font_size: int | None = None
    font_weight: str | None = None
    padding_top: int | None = None
    padding_right: int | None = None
    padding_bottom: int | None = None
    padding_left: int | None = None
    margin_top: int | None = None
    margin_right: int | None = None
    margin_bottom: int | None = None
    margin_left: int | None = None
    min_height: int | None = None
    min_width: int | None = None
    opacity: float | None = None


@dataclass
class UnsupportedCssItem:
    """An unsupported CSS rule, animation, or pseudo-selector needing manual QML polish."""

    selector: str
    feature: str
    raw: str
    line: int
    category: str  # "animation" | "pseudo-selector" | "effect" | "at-rule" | "property"
    hint: str


@dataclass
class ThemeTokens:
    """Design tokens extracted from Waybar style.css."""

    named_colors: dict[str, str] = field(default_factory=dict)
    global_style: StyleProps = field(default_factory=StyleProps)
    bar_style: StyleProps = field(default_factory=StyleProps)
    section_styles: dict[str, StyleProps] = field(default_factory=dict)
    module_styles: dict[str, StyleProps] = field(default_factory=dict)
    state_styles: dict[str, dict[str, StyleProps]] = field(default_factory=dict)
    unsupported_css: list[UnsupportedCssItem] = field(default_factory=list)


@dataclass
class ModuleSpec:
    """Normalized representation of a single Waybar module instance."""

    raw_name: str  # e.g. "hyprland/workspaces", "custom/media#2", "clock"
    kind: str  # canonical kind: "hyprland/workspaces", "niri/workspaces", "clock", "pulseaudio", "battery", "network", "tray", "custom", or fallback raw base
    instance_id: str  # sanitized QML-safe identifier, e.g. "custom_media_2"
    section: str  # "left" | "center" | "right"
    config: dict[str, Any] = field(default_factory=dict)
    style: StyleProps = field(default_factory=StyleProps)
    states: dict[str, StyleProps] = field(default_factory=dict)


@dataclass
class BarSpec:
    """Normalized representation of a Waybar bar configuration."""

    name: str = "main"
    position: str = "top"  # "top" | "bottom" | "left" | "right"
    layer: str = "top"  # "top" | "bottom" | "overlay" | "background"
    height: int = 34
    width: int | None = None
    spacing: int = 6
    exclusive: bool = True
    outputs: list[str] = field(default_factory=list)
    margin_top: int = 0
    margin_right: int = 0
    margin_bottom: int = 0
    margin_left: int = 0
    modules_left: list[ModuleSpec] = field(default_factory=list)
    modules_center: list[ModuleSpec] = field(default_factory=list)
    modules_right: list[ModuleSpec] = field(default_factory=list)

    @property
    def all_modules(self) -> list[ModuleSpec]:
        return [*self.modules_left, *self.modules_center, *self.modules_right]


@dataclass
class ModuleConversionNote:
    """Status and caveats for a single transpiled module."""

    raw_name: str
    component_file: str
    support_level: str  # "native" | "process" | "partial" | "stub"
    backend: str
    notes: list[str] = field(default_factory=list)


@dataclass
class ConversionReport:
    """Structured audit report produced alongside QML generation."""

    source_config: str
    source_style: str | None
    output_dir: str
    bar_count: int = 1
    compositor_target: str = "auto"
    mapped_tokens: list[str] = field(default_factory=list)
    module_notes: list[ModuleConversionNote] = field(default_factory=list)
    unsupported_css: list[UnsupportedCssItem] = field(default_factory=list)
    config_warnings: list[str] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)
    lint_passed: bool | None = None
    lint_output: str = ""
