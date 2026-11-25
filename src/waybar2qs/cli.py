"""Command-line interface for waybar2qs."""

from __future__ import annotations

import argparse
from collections import Counter
import inspect
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from . import __version__
from .codegen import generate_quickshell_project
from .css_parser import load_waybar_css
from .ir import BarSpec, ConversionReport, ThemeTokens
from .jsonc import load_waybar_config
from .normalizer import build_bar_specs
from .report import format_report_json, format_report_text

_QT6_VERSION_RE = re.compile(r"\b6\.\d+")
_DEFAULT_CONFIG_CANDIDATES: tuple[Path, ...] = (
    Path("~/.config/waybar/config.jsonc"),
    Path("~/.config/waybar/config"),
)


def _build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="waybar2qs",
        description=(
            "Transpile Waybar (config.jsonc + style.css) into a modular "
            "Quickshell (shell.qml) project."
        ),
    )
    parser.add_argument(
        "config",
        nargs="?",
        help=(
            "Path to Waybar config.jsonc or config "
            "(auto-discovers ~/.config/waybar/config.jsonc or config if omitted)"
        ),
    )
    parser.add_argument(
        "-s",
        "--style",
        default=None,
        help="Path to Waybar style.css (auto-discovers sibling style.css if omitted)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="./quickshell-bar",
        help="Output directory for the generated Quickshell project (default: ./quickshell-bar)",
    )
    parser.add_argument(
        "--compositor",
        choices=("auto", "hyprland", "niri"),
        default="auto",
        help="Target compositor backend (default: auto)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the full Markdown migration report to stdout",
    )
    parser.add_argument(
        "--report-file",
        default=None,
        metavar="PATH",
        help="Write the Markdown migration report to PATH (e.g. MIGRATION_REPORT.md)",
    )
    parser.add_argument(
        "--report-json",
        action="store_true",
        help="Print the machine-readable JSON migration report to stdout",
    )
    parser.add_argument(
        "--lint",
        action="store_true",
        help="Run Qt 6 qmllint on generated .qml files and record the result",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, transpile, and report without writing files to disk",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _resolve_config_path(raw_config: str | None) -> Path:
    """Resolve explicit or default Waybar configuration path."""
    if raw_config is not None:
        candidate = Path(raw_config).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"Waybar config file not found: {candidate}")
        return candidate

    expanded = [p.expanduser() for p in _DEFAULT_CONFIG_CANDIDATES]
    for candidate in expanded:
        if candidate.is_file():
            return candidate

    checked = ", ".join(str(p) for p in expanded)
    raise FileNotFoundError(
        f"No Waybar config found (checked: {checked}). Pass a CONFIG path explicitly."
    )


def _resolve_style_path(raw_style: str | None, config_path: Path) -> Path | None:
    """Resolve explicit or sibling style.css path."""
    if raw_style is not None:
        candidate = Path(raw_style).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"Waybar style.css file not found: {candidate}")
        return candidate

    sibling = config_path.parent / "style.css"
    return sibling if sibling.is_file() else None


def _is_qt6_qmllint(executable: str) -> bool:
    """Return True if the given qmllint binary reports Qt 6."""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return False
    except subprocess.TimeoutExpired:
        return False

    version_text = f"{proc.stdout}\n{proc.stderr}"
    return bool(_QT6_VERSION_RE.search(version_text))


def _find_qt6_qmllint() -> str | None:
    """Auto-detect Qt 6 qmllint binary without falling back to Qt 5 qmllint."""
    candidates: list[str] = []
    qt6_usr = Path("/usr/lib/qt6/bin/qmllint")
    if qt6_usr.is_file():
        candidates.append(str(qt6_usr))

    for name in ("qmllint6", "qmllint"):
        found = shutil.which(name)
        if found and found not in candidates:
            candidates.append(found)

    for candidate in candidates:
        if _is_qt6_qmllint(candidate):
            return candidate
    return None


def _run_qmllint(qmllint_bin: str, project_dir: Path, qml_files: list[Path]) -> tuple[bool, str]:
    """Run Qt 6 qmllint across generated QML files and return (passed, output)."""
    if not qml_files:
        return False, "No generated .qml files found to lint."

    cmd = [
        qmllint_bin,
        "--uncreatable-type",
        "disable",
        "-W",
        "0",
        "-I",
        str(project_dir),
        *(str(p) for p in sorted(qml_files)),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError as exc:
        return False, f"Failed to execute {qmllint_bin}: {exc}"
    except subprocess.TimeoutExpired:
        return False, f"Timed out running {qmllint_bin}"

    combined = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
    return proc.returncode == 0, combined


def _collect_qml_files(project_dir: Path, generated_files: list[str]) -> list[Path]:
    """Resolve generated .qml files on disk under project_dir."""
    qml_paths: list[Path] = []
    for entry in generated_files:
        if not entry.endswith(".qml"):
            continue
        p = Path(entry)
        candidate = p if p.is_absolute() else (project_dir / p)
        if candidate.is_file():
            qml_paths.append(candidate)

    if not qml_paths and project_dir.is_dir():
        qml_paths = sorted(project_dir.rglob("*.qml"))
    return qml_paths


def _call_build_bar_specs(
    raw_bars: Any,
    theme: ThemeTokens,
    compositor: str,
    jsonc_warnings: list[str],
) -> tuple[list[BarSpec], list[str]]:
    """Invoke normalizer.build_bar_specs across supported parameter conventions."""
    sig = inspect.signature(build_bar_specs)
    params = sig.parameters
    kwargs: dict[str, Any] = {}
    if "compositor" in params:
        kwargs["compositor"] = compositor
    elif "compositor_target" in params:
        kwargs["compositor_target"] = compositor
    if "warnings" in params:
        kwargs["warnings"] = list(jsonc_warnings)

    result = build_bar_specs(raw_bars, theme, **kwargs)
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], list):
        return result[0], list(result[1])
    return result, []


def _call_codegen(
    bars: list[BarSpec],
    theme: ThemeTokens,
    output_dir: Path,
    *,
    source_config: str,
    source_style: str | None,
    compositor: str,
    dry_run: bool,
) -> ConversionReport:
    """Invoke codegen.generate_quickshell_project and return the populated report."""
    report = ConversionReport(
        source_config=source_config,
        source_style=source_style,
        output_dir=str(output_dir),
        bar_count=len(bars),
        compositor_target=compositor,
        unsupported_css=list(theme.unsupported_css),
    )
    sig = inspect.signature(generate_quickshell_project)
    params = sig.parameters
    kwargs: dict[str, Any] = {}
    if "dry_run" in params:
        kwargs["dry_run"] = dry_run

    supports_dry_run = "dry_run" in params
    if dry_run and not supports_dry_run:
        with tempfile.TemporaryDirectory(prefix="waybar2qs-dryrun-") as tmp:
            tmp_dir = Path(tmp)
            generate_quickshell_project(bars, theme, tmp_dir, report, **kwargs)
            tmp_prefix = str(tmp_dir)
            report.generated_files = [
                f.replace(tmp_prefix, str(output_dir), 1) if f.startswith(tmp_prefix) else f
                for f in report.generated_files
            ]
    else:
        generate_quickshell_project(bars, theme, output_dir, report, **kwargs)

    return report


def _merge_warnings(existing: list[str], *extra_lists: list[str]) -> list[str]:
    """Deduplicate warnings while preserving insertion order."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in (existing, *extra_lists):
        for msg in group:
            if msg not in seen:
                seen.add(msg)
                merged.append(msg)
    return merged


def _format_brief_summary(report: ConversionReport, *, dry_run: bool) -> str:
    """Build a concise terminal summary when --report / --report-json are not set."""
    counts = Counter(note.support_level for note in report.module_notes)
    prefix = "[dry-run] " if dry_run else ""
    lines = [
        f"{prefix}waybar2qs: {report.source_config} -> {report.output_dir}",
        (
            f"  Bars: {report.bar_count} | Target: {report.compositor_target} | "
            f"Modules: {len(report.module_notes)} "
            f"(native={counts.get('native', 0)}, process={counts.get('process', 0)}, "
            f"partial={counts.get('partial', 0)}, stub={counts.get('stub', 0)})"
        ),
        (
            f"  Unsupported CSS: {len(report.unsupported_css)} | "
            f"Warnings: {len(report.config_warnings)} | "
            f"Files: {len(report.generated_files)}"
        ),
    ]
    if report.lint_passed is not None:
        status = "PASSED" if report.lint_passed else "FAILED"
        lines.append(f"  qmllint: {status}")
        if not report.lint_passed and report.lint_output.strip():
            lines.append(report.lint_output.strip())
    if not dry_run:
        lines.append(f"  Run: quickshell -p {report.output_dir}")
    lines.append("  Tip: pass --report for the full migration audit.")
    return "\n".join(lines) + "\n"


def _lint_project(
    bars: list[BarSpec],
    theme: ThemeTokens,
    output_dir: Path,
    report: ConversionReport,
    *,
    source_config: str,
    source_style: str | None,
    compositor: str,
    dry_run: bool,
) -> None:
    """Locate Qt 6 qmllint and run it on generated QML files."""
    qmllint_bin = _find_qt6_qmllint()
    if qmllint_bin is None:
        report.lint_passed = False
        report.lint_output = (
            "Qt 6 qmllint not found (checked /usr/lib/qt6/bin/qmllint, qmllint6, qmllint)."
        )
        return

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="waybar2qs-lint-") as tmp:
            tmp_dir = Path(tmp)
            tmp_report = _call_codegen(
                bars,
                theme,
                tmp_dir,
                source_config=source_config,
                source_style=source_style,
                compositor=compositor,
                dry_run=False,
            )
            qml_files = _collect_qml_files(tmp_dir, tmp_report.generated_files)
            passed, output = _run_qmllint(qmllint_bin, tmp_dir, qml_files)
            output = output.replace(str(tmp_dir), str(output_dir))
    else:
        qml_files = _collect_qml_files(output_dir, report.generated_files)
        passed, output = _run_qmllint(qmllint_bin, output_dir, qml_files)

    report.lint_passed = passed
    report.lint_output = output


def main(argv: list[str] | None = None) -> int:
    """Entry point for the waybar2qs CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config_path = _resolve_config_path(args.config)
        style_path = _resolve_style_path(args.style, config_path)
        output_dir = Path(args.output).expanduser()

        raw_loaded = load_waybar_config(config_path)
        if (
            isinstance(raw_loaded, tuple)
            and len(raw_loaded) == 2
            and isinstance(raw_loaded[1], list)
        ):
            raw_bars, jsonc_warnings = raw_loaded
        else:
            raw_bars, jsonc_warnings = raw_loaded, []

        theme = load_waybar_css(style_path) if style_path is not None else ThemeTokens()
        bars, norm_warnings = _call_build_bar_specs(
            raw_bars, theme, args.compositor, jsonc_warnings
        )

        source_style_str = str(style_path) if style_path is not None else None
        report = _call_codegen(
            bars,
            theme,
            output_dir,
            source_config=str(config_path),
            source_style=source_style_str,
            compositor=args.compositor,
            dry_run=args.dry_run,
        )
        report.config_warnings = _merge_warnings(
            jsonc_warnings, norm_warnings, report.config_warnings
        )

        if args.lint:
            _lint_project(
                bars,
                theme,
                output_dir,
                report,
                source_config=str(config_path),
                source_style=source_style_str,
                compositor=args.compositor,
                dry_run=args.dry_run,
            )

        if args.report_file is not None:
            if args.dry_run:
                print(
                    f"Note: skipped writing --report-file ({args.report_file}) due to --dry-run.",
                    file=sys.stderr,
                )
            else:
                report_path = Path(args.report_file).expanduser()
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(format_report_text(report), encoding="utf-8")

        if args.report_json:
            print(format_report_json(report))
        elif args.report:
            print(format_report_text(report), end="")
        else:
            print(_format_brief_summary(report, dry_run=args.dry_run), end="")

        if args.lint and report.lint_passed is False:
            return 1
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
