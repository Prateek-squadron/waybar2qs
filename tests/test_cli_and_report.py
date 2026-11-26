"""Tests for the waybar2qs CLI and Markdown/JSON migration report formatting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from waybar2qs.cli import _find_qt6_qmllint, main
from waybar2qs.ir import ConversionReport, ModuleConversionNote, UnsupportedCssItem
from waybar2qs.report import format_report_json, format_report_text

REPO_ROOT = Path(__file__).resolve().parents[1]
OMARCHY_CFG = REPO_ROOT / "fixtures" / "omarchy_hyprland" / "config.jsonc"
OMARCHY_CSS = REPO_ROOT / "fixtures" / "omarchy_hyprland" / "style.css"


def test_cli_dry_run_lint_and_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "dry-out"
    has_qmllint = _find_qt6_qmllint() is not None
    argv = [
        str(OMARCHY_CFG),
        "--style",
        str(OMARCHY_CSS),
        "-o",
        str(out_dir),
        "--dry-run",
        "--report",
    ]
    if has_qmllint:
        argv.append("--lint")
    rc = main(argv)
    captured = capsys.readouterr()
    assert rc == 0
    # --dry-run must not write project files to disk
    assert not out_dir.exists()
    assert "# waybar2qs Migration Report" in captured.out
    assert "## Module-by-Module Conversion" in captured.out
    if has_qmllint:
        assert "## qmllint Verification" in captured.out
        assert "PASSED" in captured.out


def test_cli_report_json_output_is_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "json-out"
    rc = main(
        [
            str(OMARCHY_CFG),
            "-o",
            str(out_dir),
            "--dry-run",
            "--report-json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["bar_count"] == 1
    assert payload["source_config"] == str(OMARCHY_CFG)
    assert isinstance(payload["mapped_tokens"], list) and payload["mapped_tokens"]
    assert isinstance(payload["module_notes"], list) and payload["module_notes"]
    assert isinstance(payload["unsupported_css"], list) and payload["unsupported_css"]
    assert "shell.qml" in payload["generated_files"]


def test_cli_report_file_writes_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "proj-out"
    report_path = tmp_path / "reports" / "MIGRATION_REPORT.md"
    rc = main(
        [
            str(OMARCHY_CFG),
            "-o",
            str(out_dir),
            "--report-file",
            str(report_path),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert (out_dir / "shell.qml").is_file()
    assert report_path.is_file()
    report_text = report_path.read_text(encoding="utf-8")
    assert "# waybar2qs Migration Report" in report_text
    assert "## Module-by-Module Conversion" in report_text


def test_cli_missing_config_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nonexistent.jsonc"
    rc = main([str(missing)])
    captured = capsys.readouterr()
    assert rc != 0
    assert "not found" in captured.err.lower()


def test_cli_version_flag_subprocess() -> None:
    env = dict(os.environ)
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_path
    proc = subprocess.run(
        [sys.executable, "-m", "waybar2qs.cli", "--version"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0
    assert "waybar2qs 0.1.0" in proc.stdout


def test_format_report_text_includes_modules_tokens_and_css_categories() -> None:
    report = ConversionReport(
        source_config="/tmp/config.jsonc",
        source_style="/tmp/style.css",
        output_dir="/tmp/out",
        bar_count=1,
        compositor_target="hyprland",
        mapped_tokens=["barBg = #1e1e2e", "accent = #89b4fa"],
        module_notes=[
            ModuleConversionNote(
                raw_name="clock",
                component_file="components/ClockWidget.qml",
                support_level="native",
                backend="Quickshell.SystemClock",
                notes=[],
            ),
            ModuleConversionNote(
                raw_name="cpu",
                component_file="components/StubModuleWidget.qml",
                support_level="stub",
                backend="stub",
                notes=["No built-in backend"],
            ),
        ],
        unsupported_css=[
            UnsupportedCssItem(
                selector="#clock",
                feature="transition",
                raw="transition: all 0.2s;",
                line=12,
                category="animation",
                hint="Use QML Behavior.",
            ),
            UnsupportedCssItem(
                selector="#clock:hover",
                feature=":hover",
                raw="#clock:hover { color: #fff; }",
                line=15,
                category="pseudo-selector",
                hint="Use HoverHandler.",
            ),
            UnsupportedCssItem(
                selector="window#waybar",
                feature="box-shadow",
                raw="box-shadow: 0 2px 4px #000;",
                line=20,
                category="effect",
                hint="Use MultiEffect.",
            ),
            UnsupportedCssItem(
                selector="@media (min-width: 100px)",
                feature="@media",
                raw="@media (min-width: 100px) { ... }",
                line=25,
                category="at-rule",
                hint="Not translated.",
            ),
            UnsupportedCssItem(
                selector="window#waybar",
                feature="border-top",
                raw="border-top: 1px solid #fff;",
                line=30,
                category="property",
                hint="Use child Rectangle.",
            ),
        ],
        generated_files=["Theme.qml", "qmldir", "shell.qml"],
        lint_passed=True,
        lint_output="",
    )

    md = format_report_text(report)
    assert "| clock" in md
    assert "| cpu" in md
    assert "barBg = #1e1e2e" in md
    assert "accent = #89b4fa" in md
    assert "### Animations & Transitions (1)" in md
    assert "### Pseudo-Selectors (1)" in md
    assert "### Visual Effects (1)" in md
    assert "### CSS At-Rules (1)" in md
    assert "### Unsupported Properties (1)" in md
    assert "Use QML Behavior." in md

    parsed_json = json.loads(format_report_json(report))
    assert parsed_json["compositor_target"] == "hyprland"
    assert len(parsed_json["unsupported_css"]) == 5
