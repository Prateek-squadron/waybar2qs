"""Tests for GTK CSS parsing, color resolution, StyleProps extraction, and unsupported CSS auditing."""

from __future__ import annotations

from pathlib import Path

from waybar2qs.css_parser import load_waybar_css, parse_waybar_css


def test_define_color_chained_and_hex_formats() -> None:
    css = """
    @define-color c3 #f0a;
    @define-color c4 #f0a8;
    @define-color c6 #112233;
    @define-color c8 #11223380;
    @define-color alias1 @c6;
    @define-color alias2 @alias1;
    @define-color forward @later;
    @define-color later #abcdef;
    """
    tokens = parse_waybar_css(css)
    nc = tokens.named_colors
    assert nc["c3"] == "#ff00aa"
    assert nc["c4"] == "#88ff00aa"
    assert nc["c6"] == "#112233"
    assert nc["c8"] == "#80112233"
    assert nc["alias1"] == "#112233"
    assert nc["alias2"] == "#112233"
    assert nc["forward"] == "#abcdef"


def test_color_functions_rgb_rgba_alpha_shade_lighter_darker_mix() -> None:
    css = """
    @define-color base #4080c0;
    @define-color other #c04020;
    @define-color rgb_fn rgb(255, 16, 0);
    @define-color rgba_fn rgba(255, 16, 0, 0.5);
    @define-color rgba_space rgba(10 20 30 / 0.5);
    @define-color alpha_fn alpha(@base, 0.5);
    @define-color shade_up shade(@base, 1.2);
    @define-color shade_down shade(@base, 0.5);
    @define-color light_fn lighter(@base);
    @define-color dark_fn darker(@base);
    @define-color mix_fn mix(@base, @other, 0.5);
    """
    tokens = parse_waybar_css(css)
    nc = tokens.named_colors
    assert nc["rgb_fn"] == "#ff1000"
    assert nc["rgba_fn"] == "#80ff1000"
    assert nc["rgba_space"] == "#800a141e"
    assert nc["alpha_fn"] == "#804080c0"
    assert nc["mix_fn"] == "#806070"

    # lighter/shade(>1) should produce a brighter color than base; darker/shade(<1) dimmer
    def _luma(hx: str) -> int:
        raw = hx.lstrip("#")
        if len(raw) == 8:
            raw = raw[2:]
        return int(raw[0:2], 16) + int(raw[2:4], 16) + int(raw[4:6], 16)

    assert _luma(nc["shade_up"]) > _luma(nc["base"])
    assert _luma(nc["light_fn"]) > _luma(nc["base"])
    assert _luma(nc["shade_down"]) < _luma(nc["base"])
    assert _luma(nc["dark_fn"]) < _luma(nc["base"])


def test_waybar_selectors_and_state_styles() -> None:
    css = """
    * { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 13px; color: #ffffff; }
    window#waybar { background-color: #11111b; min-height: 30px; }
    .modules-left { margin-left: 4px; }
    .modules-center { margin-left: 8px; }
    .modules-right { margin-right: 6px; }
    #workspaces { background-color: #181825; }
    #workspaces button { padding: 2px 6px; color: #aaaaaa; }
    #workspaces button.active { background-color: #89b4fa; color: #11111b; }
    #workspaces button.urgent { background-color: #f38ba8; color: #11111b; }
    #clock { color: #cdd6f4; }
    #pulseaudio.muted { color: #6c7086; background-color: #313244; }
    #battery.warning { color: #f9e2af; }
    #battery.critical { color: #f38ba8; }
    #custom-update { color: #a6e3a1; }
    """
    tokens = parse_waybar_css(css)
    assert tokens.global_style.font_family == "JetBrainsMono Nerd Font"
    assert tokens.global_style.font_size == 13
    assert tokens.global_style.color == "#ffffff"

    assert tokens.bar_style.background == "#11111b"
    assert tokens.bar_style.min_height == 30

    assert tokens.section_styles["left"].margin_left == 4
    assert tokens.section_styles["center"].margin_left == 8
    assert tokens.section_styles["right"].margin_right == 6

    assert tokens.module_styles["workspaces"].background == "#181825"
    assert tokens.module_styles["workspaces_button"].padding_top == 2
    assert tokens.module_styles["workspaces_button"].padding_left == 6
    assert tokens.state_styles["workspaces"]["active"].background == "#89b4fa"
    assert tokens.state_styles["workspaces"]["urgent"].background == "#f38ba8"

    assert tokens.module_styles["clock"].color == "#cdd6f4"
    assert tokens.state_styles["pulseaudio"]["muted"].color == "#6c7086"
    assert tokens.state_styles["pulseaudio"]["muted"].background == "#313244"
    assert tokens.state_styles["battery"]["warning"].color == "#f9e2af"
    assert tokens.state_styles["battery"]["critical"].color == "#f38ba8"
    assert tokens.module_styles["custom/update"].color == "#a6e3a1"


def test_style_props_padding_margin_1_to_4_and_box_props() -> None:
    css = """
    #clock { padding: 5px; margin: 1px; border: 2px solid #abcdef; border-radius: 10px; opacity: 0.85; }
    #network { padding: 2px 8px; margin: 3px 6px; border: none; }
    #battery { padding: 1px 2px 3px; margin: 4px 5px 6px; font-family: 'Inter', sans-serif; font-size: 12pt; }
    #tray { padding: 1px 2px 3px 4px; margin: 5px 6px 7px 8px; }
    window#waybar { background: linear-gradient(90deg, #112233 0%, #445566 100%); }
    """
    tokens = parse_waybar_css(css)

    c = tokens.module_styles["clock"]
    assert (c.padding_top, c.padding_right, c.padding_bottom, c.padding_left) == (5, 5, 5, 5)
    assert (c.margin_top, c.margin_right, c.margin_bottom, c.margin_left) == (1, 1, 1, 1)
    assert c.border_width == 2
    assert c.border_color == "#abcdef"
    assert c.border_radius == 10
    assert c.opacity == 0.85

    n = tokens.module_styles["network"]
    assert (n.padding_top, n.padding_right, n.padding_bottom, n.padding_left) == (2, 8, 2, 8)
    assert (n.margin_top, n.margin_right, n.margin_bottom, n.margin_left) == (3, 6, 3, 6)
    assert n.border_width == 0

    b = tokens.module_styles["battery"]
    assert (b.padding_top, b.padding_right, b.padding_bottom, b.padding_left) == (1, 2, 3, 2)
    assert (b.margin_top, b.margin_right, b.margin_bottom, b.margin_left) == (4, 5, 6, 5)
    assert b.font_family == "Inter"
    assert b.font_size == 16  # 12pt -> 16px

    t = tokens.module_styles["tray"]
    assert (t.padding_top, t.padding_right, t.padding_bottom, t.padding_left) == (1, 2, 3, 4)
    assert (t.margin_top, t.margin_right, t.margin_bottom, t.margin_left) == (5, 6, 7, 8)

    # Gradient fallback keeps first resolvable stop
    assert tokens.bar_style.background == "#112233"


def test_unsupported_css_auditing_lines_categories_and_hints() -> None:
    css = "\n".join(
        [
            "/* comment line 1 */",
            "#workspaces button:hover {",
            "  background-color: #292e42;",
            "  transition: background-color 0.2s ease;",
            "}",
            "#workspaces button:not(.active) {",
            "  opacity: 0.7;",
            "}",
            "#workspaces button:nth-child(2) {",
            "  color: #ffffff;",
            "}",
            "window#waybar {",
            "  background: linear-gradient(90deg, #11111b 0%, #1e1e2e 100%);",
            "  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);",
            "}",
            "#custom-update {",
            "  animation: pulse 1s infinite;",
            "}",
            "@keyframes pulse {",
            "  0% { opacity: 1; }",
            "  100% { opacity: 0.5; }",
            "}",
        ]
    )
    tokens = parse_waybar_css(css)
    items = tokens.unsupported_css
    by_feat = {(item.feature, item.line): item for item in items}

    assert (":hover", 2) in by_feat
    assert by_feat[(":hover", 2)].category == "pseudo-selector"
    assert "HoverHandler" in by_feat[(":hover", 2)].hint

    assert ("transition", 4) in by_feat
    assert by_feat[("transition", 4)].category == "animation"
    assert "Behavior" in by_feat[("transition", 4)].hint

    assert (":not(...)", 6) in by_feat
    assert by_feat[(":not(...)", 6)].category == "pseudo-selector"
    assert by_feat[(":not(...)", 6)].hint

    assert (":nth-child(...)", 9) in by_feat
    assert by_feat[(":nth-child(...)", 9)].category == "pseudo-selector"
    assert by_feat[(":nth-child(...)", 9)].hint

    assert ("linear-gradient", 13) in by_feat
    assert by_feat[("linear-gradient", 13)].category == "effect"
    assert "Gradient" in by_feat[("linear-gradient", 13)].hint

    assert ("box-shadow", 14) in by_feat
    assert by_feat[("box-shadow", 14)].category == "effect"
    assert "MultiEffect" in by_feat[("box-shadow", 14)].hint

    assert ("animation", 17) in by_feat
    assert by_feat[("animation", 17)].category == "animation"
    assert "Behavior" in by_feat[("animation", 17)].hint

    assert ("@keyframes", 19) in by_feat
    assert by_feat[("@keyframes", 19)].category == "animation"
    assert "SequentialAnimation" in by_feat[("@keyframes", 19)].hint


def test_load_waybar_css_resolves_local_import(tmp_path: Path) -> None:
    colors = tmp_path / "colors.css"
    colors.write_text("@define-color bg #223344;\n", encoding="utf-8")
    style = tmp_path / "style.css"
    style.write_text(
        '@import "colors.css";\nwindow#waybar { background-color: @bg; }\n',
        encoding="utf-8",
    )

    tokens = load_waybar_css(style)
    assert tokens.named_colors["bg"] == "#223344"
    assert tokens.bar_style.background == "#223344"
