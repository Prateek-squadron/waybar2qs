"""Tests for JSONC parsing and Waybar config loading/include resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from waybar2qs.jsonc import load_waybar_config, parse_jsonc


def test_strip_line_and_block_comments_outside_strings() -> None:
    text = """
    // Top-level comment
    {
        /* Block comment before key */
        "layer": "top", // inline comment
        /* Multi-line
           block comment */
        "height": 30 /* trailing inline block */
    }
    // End comment
    """
    parsed = parse_jsonc(text)
    assert parsed == {"layer": "top", "height": 30}


def test_preserves_comment_like_sequences_and_escapes_in_strings() -> None:
    text = r"""
    {
        "url": "https://wttr.in/?format=1",
        "awk_cmd": "awk '/* keep */ { print $1 }' // not-a-comment",
        "quoted": "say \"hello // world /* still string */\"",
        "backslash": "path\\to\\dir\\\\",
        "sed_cmd": "sed 's/a\\/b/c/'",
    }
    """
    parsed = parse_jsonc(text)
    assert parsed["url"] == "https://wttr.in/?format=1"
    assert parsed["awk_cmd"] == "awk '/* keep */ { print $1 }' // not-a-comment"
    assert parsed["quoted"] == 'say "hello // world /* still string */"'
    assert parsed["backslash"] == "path\\to\\dir\\\\"
    assert parsed["sed_cmd"] == "sed 's/a\\/b/c/'"


def test_strip_trailing_commas_in_objects_and_nested_arrays() -> None:
    text = """
    {
        "modules-left": [
            "hyprland/workspaces",
            "clock",
        ],
        "nested": [
            [1, 2, ],
            {"a": 1, "b": [3, 4,],},
        ],
        "last": true,
    }
    """
    parsed = parse_jsonc(text)
    assert parsed == {
        "modules-left": ["hyprland/workspaces", "clock"],
        "nested": [[1, 2], {"a": 1, "b": [3, 4]}],
        "last": True,
    }


def test_utf8_bom_handled_cleanly() -> None:
    text = '\ufeff{"position": "bottom",}\n'
    assert parse_jsonc(text) == {"position": "bottom"}


def test_unterminated_block_comment_raises_value_error_with_location() -> None:
    text = '{\n  "a": 1,\n  /* never closed\n  "b": 2\n}'
    with pytest.raises(ValueError) as exc_info:
        parse_jsonc(text)
    msg = str(exc_info.value)
    assert "Unterminated block comment" in msg
    assert "line 3" in msg
    assert "column 3" in msg


def test_invalid_json_raises_value_error_with_line_and_col() -> None:
    text = '{\n  "a": 1,\n  "b": invalid\n}'
    with pytest.raises(ValueError) as exc_info:
        parse_jsonc(text)
    msg = str(exc_info.value)
    assert "line 3" in msg
    assert "column" in msg


def test_top_level_single_dict_vs_multi_bar_array(tmp_path: Path) -> None:
    single_cfg = tmp_path / "single.jsonc"
    single_cfg.write_text('{"position": "top", "height": 28}', encoding="utf-8")
    bars_single, warnings_single = load_waybar_config(single_cfg)
    assert warnings_single == []
    assert bars_single == [{"position": "top", "height": 28}]

    multi_cfg = tmp_path / "multi.jsonc"
    multi_cfg.write_text(
        '[{"name": "top", "position": "top"}, {"name": "bot", "position": "bottom"}]',
        encoding="utf-8",
    )
    bars_multi, warnings_multi = load_waybar_config(multi_cfg)
    assert warnings_multi == []
    assert len(bars_multi) == 2
    assert bars_multi[0]["name"] == "top"
    assert bars_multi[1]["name"] == "bot"


def test_top_level_non_object_array_raises(tmp_path: Path) -> None:
    bad_cfg = tmp_path / "bad.jsonc"
    bad_cfg.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain only objects"):
        load_waybar_config(bad_cfg)


def test_include_single_string_and_non_overwriting_merge(tmp_path: Path) -> None:
    sub = tmp_path / "modules.jsonc"
    sub.write_text(
        """{
            "height": 40,
            "clock": {"format": "{:%H:%M}", "tooltip": true},
            "pulseaudio": {"scroll-step": 5}
        }""",
        encoding="utf-8",
    )
    main_cfg = tmp_path / "config.jsonc"
    main_cfg.write_text(
        """{
            "include": "modules.jsonc",
            "height": 28,
            "clock": {"format": "{:%H:%M:%S}"}
        }""",
        encoding="utf-8",
    )

    bars, warnings = load_waybar_config(main_cfg)
    assert warnings == []
    assert len(bars) == 1
    bar = bars[0]
    # Explicit key overrides included value
    assert bar["height"] == 28
    # Nested dict merges without losing non-overridden included keys
    assert bar["clock"] == {"format": "{:%H:%M:%S}", "tooltip": True}
    assert bar["pulseaudio"] == {"scroll-step": 5}
    assert "include" not in bar


def test_include_list_relative_paths_and_nested_includes(tmp_path: Path) -> None:
    sub_dir = tmp_path / "conf.d"
    sub_dir.mkdir()
    (sub_dir / "base.jsonc").write_text('{"a": 1, "b": 1}', encoding="utf-8")
    (sub_dir / "first.jsonc").write_text(
        '{"include": "base.jsonc", "b": 2, "c": 2}', encoding="utf-8"
    )
    (sub_dir / "second.jsonc").write_text('{"c": 3, "d": 3}', encoding="utf-8")

    root_cfg = tmp_path / "config.jsonc"
    root_cfg.write_text(
        '{"include": ["conf.d/first.jsonc", "conf.d/second.jsonc"], "d": 4}',
        encoding="utf-8",
    )

    bars, warnings = load_waybar_config(root_cfg)
    assert warnings == []
    assert bars == [{"a": 1, "b": 2, "c": 3, "d": 4}]


def test_include_cycle_detection_and_missing_warning(tmp_path: Path) -> None:
    a_cfg = tmp_path / "a.jsonc"
    b_cfg = tmp_path / "b.jsonc"
    a_cfg.write_text(
        '{"include": ["b.jsonc", "does_not_exist.jsonc"], "from_a": true}',
        encoding="utf-8",
    )
    b_cfg.write_text('{"include": "a.jsonc", "from_b": true}', encoding="utf-8")

    bars, warnings = load_waybar_config(a_cfg)
    assert len(bars) == 1
    assert bars[0]["from_a"] is True
    assert bars[0]["from_b"] is True
    assert any("circular" in w.lower() for w in warnings)
    assert any("not found" in w.lower() for w in warnings)
