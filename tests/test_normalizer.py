"""Tests for IR normalization (BarSpec, ModuleSpec, compositor target, instance suffixes)."""

from __future__ import annotations

from waybar2qs.ir import StyleProps, ThemeTokens
from waybar2qs.normalizer import build_bar_specs


def test_bar_normalization_defaults_and_height_fallback_from_bar_style() -> None:
    tokens = ThemeTokens(bar_style=StyleProps(min_height=42))
    raw_bars = [
        {
            "position": "bottom",
            "layer": "overlay",
            "margin": "4 8 6",
            "exclusive": False,
            "output": "DP-1",
            "spacing": 10,
            "modules-left": ["clock"],
        }
    ]
    bars, warnings = build_bar_specs(raw_bars, tokens)
    assert warnings == []
    assert len(bars) == 1
    bar = bars[0]
    assert bar.name == "main"
    assert bar.position == "bottom"
    assert bar.layer == "overlay"
    assert bar.height == 42
    assert (bar.margin_top, bar.margin_right, bar.margin_bottom, bar.margin_left) == (
        4,
        8,
        6,
        8,
    )
    assert bar.exclusive is False
    assert bar.outputs == ["DP-1"]
    assert bar.spacing == 10


def test_bar_normalization_output_list_and_per_side_margin_override() -> None:
    tokens = ThemeTokens(bar_style=StyleProps(min_height=40))
    raw_bars = [
        {
            "name": "secondary",
            "height": 28,
            "margin": 5,
            "margin-top": 12,
            "output": ["eDP-1", "HDMI-A-1"],
        }
    ]
    bars, warnings = build_bar_specs(raw_bars, tokens)
    assert warnings == []
    bar = bars[0]
    assert bar.name == "secondary"
    assert bar.height == 28
    assert (bar.margin_top, bar.margin_right, bar.margin_bottom, bar.margin_left) == (
        12,
        5,
        5,
        5,
    )
    assert bar.outputs == ["eDP-1", "HDMI-A-1"]


def test_vertical_bar_position_emits_warning() -> None:
    for pos in ("left", "right"):
        bars, warnings = build_bar_specs([{"position": pos}], ThemeTokens())
        assert bars[0].position == pos
        assert any("vertical position" in w.lower() for w in warnings)


def test_invalid_position_and_layer_default_with_warnings() -> None:
    bars, warnings = build_bar_specs(
        [{"position": "diagonal", "layer": "middle"}],
        ThemeTokens(),
    )
    assert bars[0].position == "top"
    assert bars[0].layer == "top"
    assert len(warnings) == 2


def test_module_instance_suffixes_unique_ids_and_config_fallback() -> None:
    tokens = ThemeTokens(
        global_style=StyleProps(font_family="Monospace", font_size=12, color="#eeeeee"),
        module_styles={
            "clock": StyleProps(color="#aabbcc"),
            "custom/foo": StyleProps(background="#112233"),
        },
    )
    raw_bars = [
        {
            "modules-left": ["clock", "clock#2", "clock#2"],
            "modules-right": ["custom/foo#bar"],
            "clock": {"format": "{:%H:%M}", "tooltip": False},
            "clock#2": {"format": "{:%Y-%m-%d}"},
            "custom/foo": {"exec": "echo hi", "interval": 10},
        }
    ]
    bars, warnings = build_bar_specs(raw_bars, tokens)
    assert warnings == []
    left = bars[0].modules_left
    right = bars[0].modules_right

    assert [m.instance_id for m in left] == ["clock", "clock_2", "clock_2_2"]
    assert left[0].config == {"format": "{:%H:%M}", "tooltip": False}
    assert left[1].config == {"format": "{:%Y-%m-%d}"}

    # custom/foo#bar has no exact config key, so it falls back to custom/foo config & style
    foo_bar = right[0]
    assert foo_bar.raw_name == "custom/foo#bar"
    assert foo_bar.kind == "custom"
    assert foo_bar.instance_id == "custom_foo_bar"
    assert foo_bar.config == {"exec": "echo hi", "interval": 10}
    assert foo_bar.style.background == "#112233"
    assert foo_bar.style.font_family == "Monospace"


def test_compositor_override_hyprland_niri_and_auto() -> None:
    raw = [{"modules-left": ["workspaces"]}]

    bars_hypr, warn_hypr = build_bar_specs(raw, ThemeTokens(), compositor="hyprland")
    assert bars_hypr[0].modules_left[0].kind == "hyprland/workspaces"
    assert warn_hypr == []

    bars_niri, warn_niri = build_bar_specs(raw, ThemeTokens(), compositor="niri")
    assert bars_niri[0].modules_left[0].kind == "niri/workspaces"
    assert warn_niri == []

    bars_auto, warn_auto = build_bar_specs(raw, ThemeTokens(), compositor="auto")
    assert bars_auto[0].modules_left[0].kind == "hyprland/workspaces"
    assert any("generic 'workspaces'" in w for w in warn_auto)

    # Mismatched explicit workspace module emits warning
    _, warn_mismatch_niri = build_bar_specs(
        [{"modules-left": ["hyprland/workspaces"]}],
        ThemeTokens(),
        compositor="niri",
    )
    assert any("hyprland/workspaces" in w and "niri" in w for w in warn_mismatch_niri)

    _, warn_mismatch_hypr = build_bar_specs(
        [{"modules-left": ["niri/workspaces"]}],
        ThemeTokens(),
        compositor="hyprland",
    )
    assert any("niri/workspaces" in w and "hyprland" in w for w in warn_mismatch_hypr)
