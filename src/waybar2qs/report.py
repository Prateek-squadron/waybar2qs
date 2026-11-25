"""Migration report formatters (text/Markdown and JSON) for waybar2qs."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import json

from .ir import ConversionReport, ModuleConversionNote, UnsupportedCssItem

_SUPPORT_ORDER: tuple[tuple[str, str], ...] = (
    ("native", "native"),
    ("process", "process-backed"),
    ("partial", "partial"),
    ("stub", "stub"),
)

_CATEGORY_ORDER: tuple[tuple[str, str], ...] = (
    ("animation", "Animations & Transitions"),
    ("pseudo-selector", "Pseudo-Selectors"),
    ("effect", "Visual Effects"),
    ("at-rule", "CSS At-Rules"),
    ("property", "Unsupported Properties"),
)


def _escape_md_cell(value: str) -> str:
    """Sanitize a string so it stays on one line inside a Markdown table cell."""
    return " ".join(value.splitlines()).replace("|", r"\|").strip()


def _format_support_breakdown(module_notes: list[ModuleConversionNote]) -> str:
    """Summarize module counts by support_level."""
    total = len(module_notes)
    if total == 0:
        return "0 total"

    counts = Counter(note.support_level for note in module_notes)
    parts: list[str] = []
    seen: set[str] = set()
    for key, label in _SUPPORT_ORDER:
        seen.add(key)
        parts.append(f"{counts.get(key, 0)} {label}")

    for key in sorted(k for k in counts if k not in seen):
        parts.append(f"{counts[key]} {key}")

    return f"{total} total ({', '.join(parts)})"


def _format_module_table(module_notes: list[ModuleConversionNote]) -> list[str]:
    """Render module conversion notes as an aligned Markdown table."""
    if not module_notes:
        return ["_No modules configured._"]

    headers = ("Module", "Component", "Support", "Backend", "Notes")
    rows: list[tuple[str, str, str, str, str]] = []
    for note in module_notes:
        notes_text = "; ".join(note.notes) if note.notes else "-"
        rows.append(
            (
                _escape_md_cell(note.raw_name),
                _escape_md_cell(note.component_file),
                _escape_md_cell(note.support_level),
                _escape_md_cell(note.backend),
                _escape_md_cell(notes_text),
            )
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]

    def _fmt_row(cols: tuple[str, ...]) -> str:
        padded = " | ".join(col.ljust(widths[i]) for i, col in enumerate(cols))
        return f"| {padded} |"

    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    lines = [_fmt_row(headers), sep]
    lines.extend(_fmt_row(row) for row in rows)
    return lines


def _format_unsupported_css(items: list[UnsupportedCssItem]) -> list[str]:
    """Group unsupported CSS items by category with selector, line, raw CSS, and QML hints."""
    if not items:
        return ["_None detected._"]

    grouped: dict[str, list[UnsupportedCssItem]] = defaultdict(list)
    for item in items:
        grouped[item.category].append(item)

    lines: list[str] = []
    ordered_categories: list[tuple[str, str]] = list(_CATEGORY_ORDER)
    known_keys = {key for key, _ in _CATEGORY_ORDER}
    for extra_key in sorted(k for k in grouped if k not in known_keys):
        ordered_categories.append((extra_key, extra_key.replace("-", " ").title()))

    first_group = True
    for key, label in ordered_categories:
        cat_items = grouped.get(key)
        if not cat_items:
            continue
        if not first_group:
            lines.append("")
        first_group = False
        lines.append(f"### {label} ({len(cat_items)})")
        for item in sorted(cat_items, key=lambda entry: (entry.line, entry.selector)):
            raw_inline = " ".join(item.raw.splitlines()).strip()
            lines.append(
                f"- **Line {item.line}** `{item.selector}` ({item.feature}): `{raw_inline}`"
            )
            lines.append(f"  - QML hint: {item.hint}")

    return lines


def format_report_text(report: ConversionReport) -> str:
    """Format a ConversionReport as a structured Markdown/terminal migration report."""
    lint_summary = (
        "not run"
        if report.lint_passed is None
        else ("PASSED" if report.lint_passed else "FAILED")
    )

    sections: list[str] = []

    summary_lines = [
        "# waybar2qs Migration Report",
        "",
        "## Summary",
        f"- **Source config**: `{report.source_config}`",
        f"- **Source style**: `{report.source_style}`"
        if report.source_style
        else "- **Source style**: _(none)_",
        f"- **Output directory**: `{report.output_dir}`",
        f"- **Compositor target**: `{report.compositor_target}`",
        f"- **Bars**: {report.bar_count}",
        f"- **Generated files**: {len(report.generated_files)}",
        f"- **Module support**: {_format_support_breakdown(report.module_notes)}",
        f"- **Unsupported CSS items**: {len(report.unsupported_css)}",
        f"- **Config warnings**: {len(report.config_warnings)}",
        f"- **qmllint**: {lint_summary}",
    ]
    sections.append("\n".join(summary_lines))

    token_lines = ["## Mapped CSS Design Tokens"]
    if report.mapped_tokens:
        token_lines.extend(f"- {token}" for token in report.mapped_tokens)
    else:
        token_lines.append("_None (no CSS design tokens mapped)._")
    sections.append("\n".join(token_lines))

    module_lines = ["## Module-by-Module Conversion"]
    module_lines.extend(_format_module_table(report.module_notes))
    sections.append("\n".join(module_lines))

    css_lines = ["## Unsupported CSS Features Needing Manual QML Polish"]
    css_lines.extend(_format_unsupported_css(report.unsupported_css))
    sections.append("\n".join(css_lines))

    warning_lines = ["## Config Warnings"]
    if report.config_warnings:
        warning_lines.extend(f"- {warning}" for warning in report.config_warnings)
    else:
        warning_lines.append("_None._")
    sections.append("\n".join(warning_lines))

    if report.generated_files:
        file_lines = ["## Generated Files"]
        file_lines.extend(f"- `{path}`" for path in report.generated_files)
        sections.append("\n".join(file_lines))

    if report.lint_passed is not None:
        status = "PASSED" if report.lint_passed else "FAILED"
        lint_lines = [
            "## qmllint Verification",
            f"- **Status**: {status}",
        ]
        cleaned_output = report.lint_output.strip()
        if cleaned_output:
            lint_lines.extend(["", "```text", cleaned_output, "```"])
        elif report.lint_passed:
            lint_lines.append("- _No warnings or errors reported._")
        sections.append("\n".join(lint_lines))

    return "\n\n".join(sections) + "\n"


def format_report_json(report: ConversionReport) -> str:
    """Serialize a ConversionReport to a formatted JSON string."""
    return json.dumps(asdict(report), indent=2)
