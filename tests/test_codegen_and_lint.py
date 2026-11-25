"""Tests for QML code generation across all fixtures and Qt 6 qmllint verification."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from waybar2qs.codegen import generate_quickshell_project
from waybar2qs.css_parser import load_waybar_css
from waybar2qs.ir import ConversionReport, ThemeTokens
from waybar2qs.jsonc import load_waybar_config
from waybar2qs.normalizer import build_bar_specs

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
QMLLINT_BIN = Path("/usr/lib/qt6/bin/qmllint")


def _generate_from_fixture(
    fixture_name: str, out_dir: Path, compositor: str = "auto"
) -> tuple[dict[str, str], ConversionReport]:
    fixture_path = FIXTURES_DIR / fixture_name
    config_path = fixture_path / "config.jsonc"
    style_path = fixture_path / "style.css"

    raw_bars, jsonc_warnings = load_waybar_config(config_path)
    tokens = load_waybar_css(style_path)
    bars, norm_warnings = build_bar_specs(raw_bars, tokens, compositor=compositor)

    report = ConversionReport(
        source_config=str(config_path),
        source_style=str(style_path),
        output_dir=str(out_dir),
        bar_count=len(bars),
        compositor_target=compositor,
        unsupported_css=list(tokens.unsupported_css),
        config_warnings=[*jsonc_warnings, *norm_warnings],
    )
    files = generate_quickshell_project(bars, tokens, out_dir, report)
    return files, report


@pytest.mark.parametrize(
    ("fixture_name", "expected_components"),
    [
        (
            "omarchy_hyprland",
            {
                "components/CustomModuleWidget.qml",
                "components/HyprlandWorkspaces.qml",
                "components/ClockWidget.qml",
                "components/TrayWidget.qml",
                "components/NetworkWidget.qml",
                "components/PulseaudioWidget.qml",
                "components/BatteryWidget.qml",
            },
        ),
        (
            "niri_scrollable",
            {
                "components/NiriWorkspaces.qml",
                "components/ClockWidget.qml",
                "components/CustomModuleWidget.qml",
                "components/PulseaudioWidget.qml",
                "components/NetworkWidget.qml",
                "components/BatteryWidget.qml",
            },
        ),
        (
            "catppuccin_pill",
            {
                "components/CustomModuleWidget.qml",
                "components/HyprlandWorkspaces.qml",
                "components/ClockWidget.qml",
                "components/TrayWidget.qml",
                "components/PulseaudioWidget.qml",
                "components/NetworkWidget.qml",
                "components/BatteryWidget.qml",
            },
        ),
    ],
)
def test_fixture_generation_files_and_bindings(
    tmp_path: Path, fixture_name: str, expected_components: set[str]
) -> None:
    out_dir = tmp_path / fixture_name
    files, report = _generate_from_fixture(fixture_name, out_dir)

    expected_base = {"qmldir", "Theme.qml", "shell.qml"}
    assert set(files.keys()) == expected_base | expected_components
    assert set(report.generated_files) == set(files.keys())

    for rel in files:
        assert (out_dir / rel).is_file()

    assert "singleton Theme 1.0 Theme.qml" in files["qmldir"]
    assert "pragma Singleton" in files["Theme.qml"]
    assert "ShellRoot" in files["shell.qml"]


def test_emitted_component_qml_bindings(tmp_path: Path) -> None:
    omarchy_dir = tmp_path / "omarchy"
    omarchy_files, _ = _generate_from_fixture("omarchy_hyprland", omarchy_dir)

    assert "PwObjectTracker" in omarchy_files["components/PulseaudioWidget.qml"]
    assert "percentage * 100" in omarchy_files["components/BatteryWidget.qml"]

    clock_qml = omarchy_files["components/ClockWidget.qml"]
    assert "SystemClock" in clock_qml
    assert "Qt.formatDateTime" in clock_qml
    assert 'qtFormat: "dddd\' \'HH\':\'mm"' in omarchy_files["shell.qml"]

    assert "Hyprland.workspaces" in omarchy_files["components/HyprlandWorkspaces.qml"]
    assert "SystemTray.items" in omarchy_files["components/TrayWidget.qml"]
    assert "Networking.devices" in omarchy_files["components/NetworkWidget.qml"]

    custom_qml = omarchy_files["components/CustomModuleWidget.qml"]
    assert "Process" in custom_qml
    assert "JSON.parse" in custom_qml
    assert "onExited" in custom_qml
    assert ".exitCode" not in custom_qml

    niri_dir = tmp_path / "niri"
    niri_files, _ = _generate_from_fixture("niri_scrollable", niri_dir, compositor="niri")
    assert '"niri", "msg"' in niri_files["components/NiriWorkspaces.qml"]


def test_unknown_modules_emit_stub_widget_and_stub_note(tmp_path: Path) -> None:
    raw_bars = [
        {
            "modules-left": ["cpu", "mpris"],
            "cpu": {"format": "CPU {usage}%", "on-click": "btop"},
            "mpris": {"format": "{player_icon}"},
        }
    ]
    tokens = ThemeTokens()
    bars, _ = build_bar_specs(raw_bars, tokens)
    out_dir = tmp_path / "stub_test"
    report = ConversionReport(
        source_config="inline.jsonc",
        source_style=None,
        output_dir=str(out_dir),
        bar_count=1,
    )
    files = generate_quickshell_project(bars, tokens, out_dir, report)

    assert "components/StubModuleWidget.qml" in files
    assert (out_dir / "components/StubModuleWidget.qml").is_file()
    assert "StubModuleWidget" in files["shell.qml"]

    notes_by_name = {n.raw_name: n for n in report.module_notes}
    assert notes_by_name["cpu"].support_level == "stub"
    assert notes_by_name["cpu"].component_file == "components/StubModuleWidget.qml"
    assert notes_by_name["mpris"].support_level == "stub"


@pytest.mark.parametrize("fixture_name", ["omarchy_hyprland", "niri_scrollable", "catppuccin_pill"])
def test_qmllint_passes_on_all_fixtures(tmp_path: Path, fixture_name: str) -> None:
    if not QMLLINT_BIN.is_file():
        pytest.skip(f"{QMLLINT_BIN} not installed on this machine")

    out_dir = tmp_path / fixture_name
    _generate_from_fixture(fixture_name, out_dir)
    qml_files = sorted(out_dir.rglob("*.qml"))
    assert qml_files

    proc = subprocess.run(
        [
            str(QMLLINT_BIN),
            "--uncreatable-type",
            "disable",
            "-W",
            "0",
            "-I",
            str(out_dir),
            *(str(p) for p in qml_files),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"qmllint failed for {fixture_name}:\n{proc.stdout}\n{proc.stderr}"
