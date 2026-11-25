"""QML code generator for converting Waybar IR into a Quickshell 0.3.2 project."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from waybar2qs.ir import (
    BarSpec,
    ConversionReport,
    ModuleConversionNote,
    ModuleSpec,
    StyleProps,
    ThemeTokens,
)

_QML_RESERVED_WORDS = frozenset(
    {
        "alias",
        "as",
        "await",
        "break",
        "case",
        "catch",
        "class",
        "component",
        "const",
        "continue",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "implements",
        "import",
        "in",
        "instanceof",
        "interface",
        "let",
        "new",
        "null",
        "objectName",
        "on",
        "package",
        "pragma",
        "private",
        "property",
        "protected",
        "public",
        "readonly",
        "required",
        "return",
        "signal",
        "static",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)

_CORE_THEME_PROPS = frozenset(
    {
        "barBg",
        "barFg",
        "accent",
        "urgent",
        "warning",
        "critical",
        "moduleBg",
        "moduleFg",
        "moduleRadius",
        "barRadius",
        "barBorderWidth",
        "barBorderColor",
        "fontFamily",
        "fontSize",
        "barHeight",
        "spacing",
        "modulePaddingH",
        "modulePaddingV",
    }
)

_VALID_LAYERS = {
    "top": "WlrLayer.Top",
    "bottom": "WlrLayer.Bottom",
    "overlay": "WlrLayer.Overlay",
    "background": "WlrLayer.Background",
}

_STRFTIME_TO_QT: dict[str, tuple[str, bool]] = {
    "%Y": ("yyyy", False),
    "%y": ("yy", False),
    "%m": ("MM", False),
    "%b": ("MMM", False),
    "%h": ("MMM", False),
    "%B": ("MMMM", False),
    "%d": ("dd", False),
    "%e": ("d", False),
    "%H": ("HH", False),
    "%k": ("H", False),
    "%I": ("hh", False),
    "%l": ("h", False),
    "%M": ("mm", False),
    "%S": ("ss", True),
    "%p": ("AP", False),
    "%P": ("ap", False),
    "%a": ("ddd", False),
    "%A": ("dddd", False),
    "%T": ("HH:mm:ss", True),
    "%R": ("HH:mm", False),
    "%X": ("HH:mm:ss", True),
    "%F": ("yyyy-MM-dd", False),
    "%D": ("MM/dd/yy", False),
}

_COLOR_FUNC_RE = re.compile(
    r"^(rgba?)\(\s*([^)]+)\s*\)$",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_FIRST_COLOR_IN_EXPR_RE = re.compile(
    r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))",
    re.IGNORECASE,
)


@dataclass
class _ResolvedTheme:
    """Computed scalar and color tokens emitted into Theme.qml."""

    bar_bg: str
    bar_fg: str
    accent: str
    urgent: str
    warning: str
    critical: str
    module_bg: str
    module_fg: str
    module_radius: int
    bar_radius: int
    bar_border_width: int
    bar_border_color: str
    font_family: str
    font_size: int
    bar_height: int
    spacing: int
    module_padding_h: int
    module_padding_v: int
    helper_colors: dict[str, str]


def _qml_str(value: str) -> str:
    """Serialize a Python string into a safe QML double-quoted string literal."""
    escaped = json.dumps(value, ensure_ascii=False)
    return escaped.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _qml_literal(value: Any) -> str:
    """Serialize a Python dict/list/scalar into a valid QML property binding expression."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _qml_str(value)
    if isinstance(value, dict):
        dumped = json.dumps(value, ensure_ascii=False)
        dumped = dumped.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        return f"({dumped})"
    if isinstance(value, (list, tuple)):
        dumped = json.dumps(list(value), ensure_ascii=False)
        dumped = dumped.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        return dumped
    return _qml_str(str(value))


def _sanitize_theme_prop(name: str, used: set[str]) -> str:
    """Convert an arbitrary @define-color name into a unique valid QML property name."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.replace("-", "_").replace(".", "_"))
    cleaned = cleaned.lstrip("_")
    if not cleaned:
        cleaned = "colorToken"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    cleaned = cleaned[0].lower() + cleaned[1:]
    if cleaned in _QML_RESERVED_WORDS or cleaned in _CORE_THEME_PROPS:
        cleaned = f"color_{cleaned}"
    candidate = cleaned
    suffix = 2
    while candidate in used:
        candidate = f"{cleaned}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _parse_channel(raw: str, is_alpha: bool = False) -> int:
    """Parse a CSS rgb/rgba color channel (0-255, 0-1 alpha, or percentage)."""
    token = raw.strip()
    if token.endswith("%"):
        pct = float(token[:-1])
        scaled = (pct / 100.0) * 255.0
        return max(0, min(255, round(scaled)))
    val = float(token)
    if is_alpha:
        if val <= 1.0:
            return max(0, min(255, round(val * 255.0)))
        return max(0, min(255, round(val)))
    return max(0, min(255, round(val)))


def _normalize_color(
    raw: str | None,
    named_colors: dict[str, str],
    fallback: str = "#cdd6f4",
    _seen: set[str] | None = None,
) -> str:
    """Normalize a CSS color expression into a Qt QML-compatible color string."""
    if raw is None:
        return fallback
    val = raw.strip()
    if not val:
        return fallback
    lower = val.lower()
    if lower in {"none", "transparent"}:
        return "transparent"

    if val.startswith("@"):
        key = val[1:].strip()
        seen = _seen if _seen is not None else set()
        if key in seen:
            return fallback
        if key in named_colors:
            seen.add(key)
            return _normalize_color(named_colors[key], named_colors, fallback, seen)
        return fallback

    hex_match = _HEX_RE.match(val)
    if hex_match:
        digits = hex_match.group(1).lower()
        if len(digits) == 3:
            r, g, b = digits[0] * 2, digits[1] * 2, digits[2] * 2
            return f"#{r}{g}{b}"
        if len(digits) == 4:
            # CSS #RGBA -> Qt #AARRGGBB
            r, g, b, a = digits[0] * 2, digits[1] * 2, digits[2] * 2, digits[3] * 2
            return f"#{a}{r}{g}{b}"
        if len(digits) == 6:
            return f"#{digits}"
        if len(digits) == 8:
            # CSS #RRGGBBAA -> Qt #AARRGGBB
            rr, gg, bb, aa = digits[0:2], digits[2:4], digits[4:6], digits[6:8]
            return f"#{aa}{rr}{gg}{bb}"

    func_match = _COLOR_FUNC_RE.match(val)
    if func_match:
        args_raw = func_match.group(2).replace("/", ",")
        parts = [p for p in re.split(r"[\s,]+", args_raw.strip()) if p]
        try:
            if len(parts) >= 3:
                r = _parse_channel(parts[0])
                g = _parse_channel(parts[1])
                b = _parse_channel(parts[2])
                if len(parts) >= 4:
                    a = _parse_channel(parts[3], is_alpha=True)
                    return f"#{a:02x}{r:02x}{g:02x}{b:02x}"
                return f"#{r:02x}{g:02x}{b:02x}"
        except ValueError:
            return fallback

    if "gradient" in lower:
        embedded = _FIRST_COLOR_IN_EXPR_RE.search(val)
        if embedded:
            return _normalize_color(embedded.group(1), named_colors, fallback, _seen)
        return fallback

    if re.fullmatch(r"[a-zA-Z]+", val):
        return lower

    return fallback


def _clean_font_family(raw: str | None) -> str:
    """Extract the primary font family from a CSS font-family declaration."""
    if not raw:
        return "sans-serif"
    first = raw.split(",")[0].strip().strip("'\"")
    return first or "sans-serif"


def _is_bold_weight(weight: str | None) -> bool:
    """Return True when a CSS font-weight maps to bold."""
    if not weight:
        return False
    low = weight.strip().lower()
    if low in {"bold", "bolder"}:
        return True
    try:
        return int(low) >= 600
    except ValueError:
        return False


def _pick_first_style_attr(styles: list[StyleProps], attr: str) -> Any:
    """Return the first non-None attribute value across a sequence of StyleProps."""
    for st in styles:
        val = getattr(st, attr, None)
        if val is not None:
            return val
    return None


def _lookup_named_color(
    named_colors: dict[str, str],
    candidates: tuple[str, ...],
) -> str | None:
    """Find a named color matching any candidate key (case-insensitive)."""
    lower_map = {k.lower(): v for k, v in named_colors.items()}
    for cand in candidates:
        if cand in lower_map:
            return lower_map[cand]
    return None


def _build_theme_context(bars: list[BarSpec], tokens: ThemeTokens) -> _ResolvedTheme:
    """Resolve Theme.qml properties from ThemeTokens and BarSpec defaults."""
    named = tokens.named_colors
    all_mod_styles = list(tokens.module_styles.values())
    section_vals = list(tokens.section_styles.values())

    bar_bg_raw = _pick_first_style_attr([tokens.bar_style, tokens.global_style], "background")
    bar_fg_raw = _pick_first_style_attr([tokens.bar_style, tokens.global_style], "color")
    mod_bg_raw = _pick_first_style_attr([*all_mod_styles, *section_vals], "background")
    mod_fg_raw = _pick_first_style_attr([*all_mod_styles, *section_vals], "color")

    ws_states = tokens.state_styles.get("workspaces button") or tokens.state_styles.get("workspaces") or {}
    bat_states = tokens.state_styles.get("battery") or {}

    accent_raw = (
        _pick_first_style_attr(
            [ws_states.get("focused", StyleProps()), ws_states.get("active", StyleProps())],
            "background",
        )
        or _lookup_named_color(named, ("accent", "primary", "blue", "mauve", "highlight", "active"))
    )
    urgent_raw = (
        _pick_first_style_attr([ws_states.get("urgent", StyleProps())], "background")
        or _lookup_named_color(named, ("urgent", "red", "error", "alert"))
    )
    warning_raw = (
        _pick_first_style_attr([bat_states.get("warning", StyleProps())], "background")
        or _lookup_named_color(named, ("warning", "yellow", "peach", "orange"))
    )
    critical_raw = (
        _pick_first_style_attr([bat_states.get("critical", StyleProps())], "background")
        or _lookup_named_color(named, ("critical", "red", "danger"))
    )

    bar_bg = _normalize_color(bar_bg_raw, named, "#1e1e2e")
    bar_fg = _normalize_color(bar_fg_raw, named, "#cdd6f4")
    module_bg = _normalize_color(mod_bg_raw, named, "#313244" if bar_bg == "transparent" else bar_bg)
    module_fg = _normalize_color(mod_fg_raw, named, bar_fg)

    module_radius = _pick_first_style_attr([*all_mod_styles, tokens.global_style], "border_radius")
    bar_radius = tokens.bar_style.border_radius if tokens.bar_style.border_radius is not None else 0
    bar_bw = tokens.bar_style.border_width if tokens.bar_style.border_width is not None else 0
    bar_bc = _normalize_color(tokens.bar_style.border_color, named, "transparent")

    font_family_raw = _pick_first_style_attr([tokens.global_style, tokens.bar_style], "font_family")
    font_size_raw = _pick_first_style_attr([tokens.global_style, tokens.bar_style], "font_size")

    pad_h = _pick_first_style_attr(all_mod_styles, "padding_left")
    if pad_h is None:
        pad_h = _pick_first_style_attr(all_mod_styles, "padding_right")
    pad_v = _pick_first_style_attr(all_mod_styles, "padding_top")
    if pad_v is None:
        pad_v = _pick_first_style_attr(all_mod_styles, "padding_bottom")

    first_bar = bars[0] if bars else BarSpec()
    used_props: set[str] = set(_CORE_THEME_PROPS) | set(_QML_RESERVED_WORDS)
    helper_colors: dict[str, str] = {}
    for raw_key, raw_val in named.items():
        prop_name = _sanitize_theme_prop(raw_key, used_props)
        helper_colors[prop_name] = _normalize_color(raw_val, named, "#cdd6f4")

    return _ResolvedTheme(
        bar_bg=bar_bg,
        bar_fg=bar_fg,
        accent=_normalize_color(accent_raw, named, "#89b4fa"),
        urgent=_normalize_color(urgent_raw, named, "#f38ba8"),
        warning=_normalize_color(warning_raw, named, "#f9e2af"),
        critical=_normalize_color(critical_raw, named, "#f38ba8"),
        module_bg=module_bg,
        module_fg=module_fg,
        module_radius=int(module_radius) if module_radius is not None else 6,
        bar_radius=int(bar_radius),
        bar_border_width=int(bar_bw),
        bar_border_color=bar_bc,
        font_family=_clean_font_family(font_family_raw),
        font_size=int(font_size_raw) if font_size_raw is not None else 13,
        bar_height=int(first_bar.height) if first_bar.height > 0 else 34,
        spacing=int(first_bar.spacing) if first_bar.spacing >= 0 else 6,
        module_padding_h=int(pad_h) if pad_h is not None else 10,
        module_padding_v=int(pad_v) if pad_v is not None else 4,
        helper_colors=helper_colors,
    )


def _render_theme_qml(theme: _ResolvedTheme, mapped_tokens: list[str]) -> str:
    """Render Theme.qml and populate report.mapped_tokens."""
    lines = [
        "pragma Singleton",
        "import QtQuick",
        "",
        "QtObject {",
        f"    readonly property color barBg: {_qml_str(theme.bar_bg)}",
        f"    readonly property color barFg: {_qml_str(theme.bar_fg)}",
        f"    readonly property color accent: {_qml_str(theme.accent)}",
        f"    readonly property color urgent: {_qml_str(theme.urgent)}",
        f"    readonly property color warning: {_qml_str(theme.warning)}",
        f"    readonly property color critical: {_qml_str(theme.critical)}",
        f"    readonly property color moduleBg: {_qml_str(theme.module_bg)}",
        f"    readonly property color moduleFg: {_qml_str(theme.module_fg)}",
        f"    readonly property int moduleRadius: {theme.module_radius}",
        f"    readonly property int barRadius: {theme.bar_radius}",
        f"    readonly property int barBorderWidth: {theme.bar_border_width}",
        f"    readonly property color barBorderColor: {_qml_str(theme.bar_border_color)}",
        f"    readonly property string fontFamily: {_qml_str(theme.font_family)}",
        f"    readonly property int fontSize: {theme.font_size}",
        f"    readonly property int barHeight: {theme.bar_height}",
        f"    readonly property int spacing: {theme.spacing}",
        f"    readonly property int modulePaddingH: {theme.module_padding_h}",
        f"    readonly property int modulePaddingV: {theme.module_padding_v}",
    ]

    mapped_tokens.extend(
        [
            f"barBg = {theme.bar_bg}",
            f"barFg = {theme.bar_fg}",
            f"accent = {theme.accent}",
            f"urgent = {theme.urgent}",
            f"warning = {theme.warning}",
            f"critical = {theme.critical}",
            f"moduleBg = {theme.module_bg}",
            f"moduleFg = {theme.module_fg}",
            f"moduleRadius = {theme.module_radius}",
            f"barRadius = {theme.bar_radius}",
            f"barBorderWidth = {theme.bar_border_width}",
            f"barBorderColor = {theme.bar_border_color}",
            f"fontFamily = {theme.font_family}",
            f"fontSize = {theme.font_size}",
            f"barHeight = {theme.bar_height}",
            f"spacing = {theme.spacing}",
            f"modulePaddingH = {theme.module_padding_h}",
            f"modulePaddingV = {theme.module_padding_v}",
        ]
    )

    if theme.helper_colors:
        lines.append("")
        for prop_name, hex_val in theme.helper_colors.items():
            lines.append(f"    readonly property color {prop_name}: {_qml_str(hex_val)}")
            mapped_tokens.append(f"{prop_name} = {hex_val}")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _render_qmldir() -> str:
    """Render the root qmldir file registering Theme as a singleton."""
    return "singleton Theme 1.0 Theme.qml\n"


def _quote_qt_literal(text: str) -> str:
    """Escape literal text segments for Qt.formatDateTime format strings."""
    if not text:
        return ""
    return "'" + text.replace("'", "''") + "'"


def _translate_strftime_segment(segment: str, notes: list[str]) -> tuple[str, bool]:
    """Translate a single strftime format body (inside {:...}) to Qt date/time format."""
    out: list[str] = []
    literal_buf: list[str] = []
    use_seconds = False
    i = 0
    while i < len(segment):
        if segment[i] == "%" and i + 1 < len(segment):
            spec = segment[i : i + 2]
            if spec == "%%":
                literal_buf.append("%")
                i += 2
                continue
            if spec in _STRFTIME_TO_QT:
                if literal_buf:
                    out.append(_quote_qt_literal("".join(literal_buf)))
                    literal_buf.clear()
                qt_tok, needs_sec = _STRFTIME_TO_QT[spec]
                out.append(qt_tok)
                if needs_sec:
                    use_seconds = True
                i += 2
                continue
            notes.append(f"Unsupported strftime specifier '{spec}' omitted from Qt clock format")
            i += 2
            continue
        literal_buf.append(segment[i])
        i += 1

    if literal_buf:
        out.append(_quote_qt_literal("".join(literal_buf)))
    return "".join(out), use_seconds


def _waybar_clock_format_to_qt(fmt: str) -> tuple[str, bool, list[str]]:
    """Convert a Waybar clock format string (e.g. ' {:%H:%M}') into a Qt format string."""
    if not fmt:
        return "HH:mm", False, []

    notes: list[str] = []
    use_seconds = False
    out: list[str] = []
    pos = 0
    found_block = False

    for match in re.finditer(r"\{:([^}]*)\}", fmt):
        found_block = True
        prefix = fmt[pos : match.start()]
        if prefix:
            out.append(_quote_qt_literal(prefix))
        qt_part, needs_sec = _translate_strftime_segment(match.group(1), notes)
        if qt_part:
            out.append(qt_part)
        if needs_sec:
            use_seconds = True
        pos = match.end()

    if not found_block:
        if "%" in fmt:
            qt_part, use_seconds = _translate_strftime_segment(fmt, notes)
            return qt_part or "HH:mm", use_seconds, notes
        return _quote_qt_literal(fmt.replace("{}", "")) or "HH:mm", False, notes

    suffix = fmt[pos:]
    if suffix:
        out.append(_quote_qt_literal(suffix))

    result = "".join(out)
    return (result if result else "HH:mm"), use_seconds, notes


def _component_hyprland_workspaces() -> str:
    return """pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell.Hyprland
import ".."

Rectangle {
    id: root
    property var formatIcons: ({})
    property var persistentIds: []
    property color activeBg: Theme.accent
    property color activeFg: Theme.barBg
    property color focusedBg: Theme.accent
    property color focusedFg: Theme.barBg
    property color urgentBg: Theme.urgent
    property color urgentFg: Theme.barBg
    property color buttonBg: "transparent"
    property color buttonFg: root.fgColor
    property int buttonRadius: Theme.moduleRadius
    property int buttonSpacing: 4
    property bool enableScroll: true
    property bool allOutputs: true
    property string monitorName: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: 4
    property int paddingV: 2
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    color: root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: row.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(row.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    function buildWorkspaceModel() {
        const live = Hyprland.workspaces ? Hyprland.workspaces.values : [];
        const items = [];
        const seen = {};
        for (let i = 0; i < live.length; i++) {
            const ws = live[i];
            if (!ws) continue;
            if (!root.allOutputs && ws.monitor && root.monitorName.length > 0 && ws.monitor.name !== root.monitorName) {
                continue;
            }
            seen[ws.id] = true;
            items.push({
                wsId: ws.id,
                wsName: ws.name || "",
                active: ws.active,
                focused: ws.focused,
                urgent: ws.urgent,
                wsRef: ws
            });
        }
        for (let j = 0; j < root.persistentIds.length; j++) {
            const pid = Number(root.persistentIds[j]);
            if (!seen[pid]) {
                items.push({
                    wsId: pid,
                    wsName: String(pid),
                    active: false,
                    focused: false,
                    urgent: false,
                    wsRef: null
                });
            }
        }
        items.sort(function(a, b) { return a.wsId - b.wsId; });
        return items;
    }

    function workspaceLabel(ws) {
        if (!ws) return "";
        const idKey = String(ws.wsId);
        if (root.formatIcons && root.formatIcons[idKey] !== undefined) return String(root.formatIcons[idKey]);
        if (root.formatIcons && ws.wsName && root.formatIcons[ws.wsName] !== undefined) return String(root.formatIcons[ws.wsName]);
        if (root.formatIcons && root.formatIcons["default"] !== undefined) return String(root.formatIcons["default"]);
        return ws.wsName && ws.wsName.length > 0 ? ws.wsName : idKey;
    }

    WheelHandler {
        onWheel: function(event) {
            if (!root.enableScroll) return;
            if (event.angleDelta.y > 0) Hyprland.dispatch("workspace e-1");
            else if (event.angleDelta.y < 0) Hyprland.dispatch("workspace e+1");
        }
    }

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: root.buttonSpacing

        Repeater {
            model: root.buildWorkspaceModel()
            delegate: Rectangle {
                id: wsBtn
                required property var modelData
                radius: root.buttonRadius
                color: modelData.urgent ? root.urgentBg : (modelData.focused ? root.focusedBg : (modelData.active ? root.activeBg : root.buttonBg))
                implicitWidth: Math.max(wsText.implicitWidth + 12, 24)
                implicitHeight: Math.max(wsText.implicitHeight + 4, 22)

                Text {
                    id: wsText
                    anchors.centerIn: parent
                    text: root.workspaceLabel(wsBtn.modelData)
                    color: wsBtn.modelData.urgent ? root.urgentFg : (wsBtn.modelData.focused ? root.focusedFg : (wsBtn.modelData.active ? root.activeFg : root.buttonFg))
                    font.family: root.fontFamily
                    font.pixelSize: root.fontSize
                    font.bold: root.boldFont || wsBtn.modelData.focused || wsBtn.modelData.active
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (wsBtn.modelData.wsRef) wsBtn.modelData.wsRef.activate();
                        else Hyprland.dispatch("workspace " + String(wsBtn.modelData.wsId));
                    }
                }
            }
        }
    }
}
"""


def _component_niri_workspaces() -> str:
    return """pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import ".."

Rectangle {
    id: root
    property var formatIcons: ({})
    property var workspaces: []
    property color activeBg: Theme.accent
    property color activeFg: Theme.barBg
    property color focusedBg: Theme.accent
    property color focusedFg: Theme.barBg
    property color urgentBg: Theme.urgent
    property color urgentFg: Theme.barBg
    property color buttonBg: "transparent"
    property color buttonFg: root.fgColor
    property int buttonRadius: Theme.moduleRadius
    property int buttonSpacing: 4
    property bool enableScroll: true
    property bool allOutputs: true
    property string monitorName: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: 4
    property int paddingV: 2
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    color: root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: row.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(row.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    function workspaceLabel(ws) {
        if (!ws) return "";
        const idxKey = String(ws.idx);
        if (root.formatIcons && root.formatIcons[idxKey] !== undefined) return String(root.formatIcons[idxKey]);
        if (root.formatIcons && ws.name && root.formatIcons[ws.name] !== undefined) return String(root.formatIcons[ws.name]);
        if (root.formatIcons && root.formatIcons["default"] !== undefined) return String(root.formatIcons["default"]);
        return ws.name && ws.name.length > 0 ? ws.name : idxKey;
    }

    Process {
        id: fetchProc
        command: ["niri", "msg", "--json", "workspaces"]
        running: true
        stdout: StdioCollector {
            id: fetchOut
            waitForEnd: true
        }
        onExited: function(exitCode, exitStatus) {
            if (exitCode !== 0) return;
            try {
                const parsed = JSON.parse(fetchOut.text);
                if (Array.isArray(parsed)) {
                    parsed.sort(function(a, b) { return (a.idx || 0) - (b.idx || 0); });
                    root.workspaces = parsed;
                }
            } catch (e) {}
        }
    }

    Process {
        id: eventProc
        command: ["niri", "msg", "--json", "event-stream"]
        running: true
        stdout: SplitParser {
            onRead: function(line) {
                if (line.indexOf("Workspace") !== -1 && !fetchProc.running) {
                    fetchProc.running = true;
                }
            }
        }
    }

    WheelHandler {
        onWheel: function(event) {
            if (!root.enableScroll) return;
            if (event.angleDelta.y > 0) Quickshell.execDetached(["niri", "msg", "action", "focus-workspace-up"]);
            else if (event.angleDelta.y < 0) Quickshell.execDetached(["niri", "msg", "action", "focus-workspace-down"]);
        }
    }

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: root.buttonSpacing

        Repeater {
            model: root.workspaces
            delegate: Rectangle {
                id: wsBtn
                required property var modelData
                visible: root.allOutputs || !modelData.output || modelData.output === root.monitorName
                radius: root.buttonRadius
                color: modelData.is_urgent ? root.urgentBg : (modelData.is_focused ? root.focusedBg : (modelData.is_active ? root.activeBg : root.buttonBg))
                implicitWidth: Math.max(wsText.implicitWidth + 12, 24)
                implicitHeight: Math.max(wsText.implicitHeight + 4, 22)

                Text {
                    id: wsText
                    anchors.centerIn: parent
                    text: root.workspaceLabel(wsBtn.modelData)
                    color: wsBtn.modelData.is_urgent ? root.urgentFg : (wsBtn.modelData.is_focused ? root.focusedFg : (wsBtn.modelData.is_active ? root.activeFg : root.buttonFg))
                    font.family: root.fontFamily
                    font.pixelSize: root.fontSize
                    font.bold: root.boldFont || wsBtn.modelData.is_focused || wsBtn.modelData.is_active
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Quickshell.execDetached(["niri", "msg", "action", "focus-workspace", String(wsBtn.modelData.idx)])
                }
            }
        }
    }
}
"""


def _component_clock_widget() -> str:
    return """import QtQuick
import Quickshell
import ".."

Rectangle {
    id: root
    property string qtFormat: "HH:mm"
    property string qtFormatAlt: ""
    property bool useSeconds: false
    property bool showingAlt: false
    property string onClickCmd: ""
    property string onClickRightCmd: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    color: root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: label.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(label.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    SystemClock {
        id: clock
        precision: root.useSeconds ? SystemClock.Seconds : SystemClock.Minutes
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: Qt.formatDateTime(clock.date, (root.showingAlt && root.qtFormatAlt.length > 0) ? root.qtFormatAlt : root.qtFormat)
        color: root.fgColor
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: root.boldFont
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: (root.qtFormatAlt.length > 0 || root.onClickCmd.length > 0 || root.onClickRightCmd.length > 0) ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton) {
                if (root.onClickRightCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onClickRightCmd]);
                return;
            }
            if (root.onClickCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onClickCmd]);
            else if (root.qtFormatAlt.length > 0) root.showingAlt = !root.showingAlt;
        }
    }
}
"""


def _component_pulseaudio_widget() -> str:
    return """import QtQuick
import Quickshell
import Quickshell.Services.Pipewire
import ".."

Rectangle {
    id: root
    property string formatStr: "{volume}% {icon}"
    property string formatMuted: " {format_source}"
    property string formatSource: ""
    property var formatIcons: ["", "", ""]
    property real scrollStep: 0.05
    property string onClickCmd: ""
    property string onClickRightCmd: ""
    property string onScrollUpCmd: ""
    property string onScrollDownCmd: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property color mutedBg: Theme.moduleBg
    property color mutedFg: Theme.urgent
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    readonly property var sink: Pipewire.defaultAudioSink
    readonly property bool muted: sink && sink.audio ? sink.audio.muted : false
    readonly property int volume: sink && sink.audio ? Math.round(sink.audio.volume * 100) : 0

    PwObjectTracker {
        objects: Pipewire.defaultAudioSink ? [Pipewire.defaultAudioSink] : []
    }

    function pickIcon() {
        let icons = root.formatIcons;
        if (icons && !Array.isArray(icons) && icons["default"]) icons = icons["default"];
        if (!Array.isArray(icons) || icons.length === 0) return "";
        const clamped = Math.max(0, Math.min(100, root.volume));
        const idx = Math.min(icons.length - 1, Math.floor(clamped * icons.length / 101));
        return String(icons[idx]);
    }

    function formattedText() {
        const tpl = root.muted ? root.formatMuted : root.formatStr;
        return tpl.replace(/\\{volume\\}/g, String(root.volume))
                  .replace(/\\{icon\\}/g, root.pickIcon())
                  .replace(/\\{format_source\\}/g, root.formatSource);
    }

    color: root.muted ? root.mutedBg : root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: label.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(label.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    Text {
        id: label
        anchors.centerIn: parent
        text: root.formattedText()
        color: root.muted ? root.mutedFg : root.fgColor
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: root.boldFont
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function(mouse) {
            if (mouse.button === Qt.RightButton) {
                if (root.onClickRightCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onClickRightCmd]);
                return;
            }
            if (root.onClickCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onClickCmd]);
            else if (root.sink && root.sink.audio) root.sink.audio.muted = !root.sink.audio.muted;
        }
    }

    WheelHandler {
        onWheel: function(event) {
            if (event.angleDelta.y > 0) {
                if (root.onScrollUpCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onScrollUpCmd]);
                else if (root.sink && root.sink.audio) root.sink.audio.volume = Math.min(1.5, Math.max(0.0, root.sink.audio.volume + root.scrollStep));
            } else if (event.angleDelta.y < 0) {
                if (root.onScrollDownCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onScrollDownCmd]);
                else if (root.sink && root.sink.audio) root.sink.audio.volume = Math.min(1.5, Math.max(0.0, root.sink.audio.volume - root.scrollStep));
            }
        }
    }
}
"""


def _component_battery_widget() -> str:
    return """import QtQuick
import Quickshell
import Quickshell.Services.UPower
import ".."

Rectangle {
    id: root
    property string formatStr: "{capacity}% {icon}"
    property string formatCharging: "{capacity}% "
    property string formatPlugged: "{capacity}% "
    property string formatFull: ""
    property var formatIcons: ["", "", "", "", ""]
    property int warningLevel: 30
    property int criticalLevel: 15
    property string onClickCmd: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property color warningBg: Theme.warning
    property color warningFg: Theme.barBg
    property color criticalBg: Theme.critical
    property color criticalFg: Theme.barBg
    property color chargingBg: Theme.moduleBg
    property color chargingFg: Theme.moduleFg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    readonly property var bat: UPower.displayDevice
    readonly property int capacity: bat ? Math.round(bat.percentage * 100) : 0
    readonly property bool isCharging: bat ? bat.state === UPowerDeviceState.Charging : false
    readonly property bool isPlugged: bat ? bat.state === UPowerDeviceState.PendingCharge : false
    readonly property bool isFull: bat ? bat.state === UPowerDeviceState.FullyCharged : false
    readonly property bool isDischarging: !isCharging && !isPlugged && !isFull
    readonly property bool isCritical: isDischarging && capacity <= criticalLevel
    readonly property bool isWarning: isDischarging && !isCritical && capacity <= warningLevel

    visible: bat ? bat.isPresent : false

    function pickIcon() {
        const icons = root.formatIcons;
        if (!Array.isArray(icons) || icons.length === 0) return "";
        const clamped = Math.max(0, Math.min(100, root.capacity));
        const idx = Math.min(icons.length - 1, Math.floor(clamped * icons.length / 101));
        return String(icons[idx]);
    }

    function formatDuration(secs) {
        if (!secs || secs <= 0) return "";
        const mins = Math.round(secs / 60);
        const h = Math.floor(mins / 60);
        const m = mins % 60;
        return String(h) + "h " + (m < 10 ? "0" : "") + String(m) + "m";
    }

    function formattedText() {
        let tpl = root.formatStr;
        if (root.isFull && root.formatFull.length > 0) tpl = root.formatFull;
        else if (root.isCharging && root.formatCharging.length > 0) tpl = root.formatCharging;
        else if (root.isPlugged && root.formatPlugged.length > 0) tpl = root.formatPlugged;
        const secs = root.bat ? (root.isCharging ? root.bat.timeToFull : root.bat.timeToEmpty) : 0;
        const powerVal = root.bat ? Math.abs(root.bat.changeRate).toFixed(1) : "0.0";
        return tpl.replace(/\\{capacity\\}/g, String(root.capacity))
                  .replace(/\\{icon\\}/g, root.pickIcon())
                  .replace(/\\{time\\}/g, root.formatDuration(secs))
                  .replace(/\\{power\\}/g, powerVal);
    }

    color: root.isCritical ? root.criticalBg : (root.isWarning ? root.warningBg : (root.isCharging ? root.chargingBg : root.bgColor))
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: label.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(label.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    Text {
        id: label
        anchors.centerIn: parent
        text: root.formattedText()
        color: root.isCritical ? root.criticalFg : (root.isWarning ? root.warningFg : (root.isCharging ? root.chargingFg : root.fgColor))
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: root.boldFont
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.onClickCmd.length > 0
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: Quickshell.execDetached(["sh", "-c", root.onClickCmd])
    }
}
"""


def _component_network_widget() -> str:
    return """import QtQuick
import Quickshell
import Quickshell.Networking
import ".."

Rectangle {
    id: root
    property string formatWifi: "{essid} ({signalStrength}%) "
    property string formatEthernet: "{ifname} "
    property string formatDisconnected: "Disconnected ⚠"
    property string formatAlt: ""
    property var formatIcons: ["󰤯", "󰤟", "󰤢", "󰤥", "󰤨"]
    property string onClickCmd: ""
    property bool showingAlt: false
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property color disconnectedBg: Theme.moduleBg
    property color disconnectedFg: Theme.urgent
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    function activeState() {
        const devs = Networking.devices ? Networking.devices.values : [];
        let wiredDev = null;
        let wifiDev = null;
        for (let i = 0; i < devs.length; i++) {
            const d = devs[i];
            if (!d) continue;
            if (d.type === DeviceType.Wired && d.connected) wiredDev = d;
            else if (d.type === DeviceType.Wifi && d.connected) wifiDev = d;
        }
        if (wiredDev) {
            return { kind: "wired", ifname: wiredDev.name || "eth", essid: "", signal: 100 };
        }
        if (wifiDev) {
            let essid = "";
            let signal = 0;
            const nets = wifiDev.networks ? wifiDev.networks.values : [];
            for (let j = 0; j < nets.length; j++) {
                const n = nets[j];
                if (n && n.connected) {
                    essid = n.name || "";
                    const s = n.signalStrength || 0;
                    signal = s <= 1.0 ? Math.round(s * 100) : Math.round(s);
                    break;
                }
            }
            return { kind: "wifi", ifname: wifiDev.name || "wlan", essid: essid, signal: signal };
        }
        return { kind: "disconnected", ifname: "", essid: "", signal: 0 };
    }

    function pickIcon(signal) {
        const icons = root.formatIcons;
        if (!Array.isArray(icons) || icons.length === 0) return "";
        const clamped = Math.max(0, Math.min(100, signal));
        const idx = Math.min(icons.length - 1, Math.floor(clamped * icons.length / 101));
        return String(icons[idx]);
    }

    readonly property var netInfo: activeState()
    readonly property bool isDisconnected: netInfo.kind === "disconnected"

    function formattedText() {
        const info = root.netInfo;
        let tpl = root.formatDisconnected;
        if (root.showingAlt && root.formatAlt.length > 0) tpl = root.formatAlt;
        else if (info.kind === "wired") tpl = root.formatEthernet;
        else if (info.kind === "wifi") tpl = root.formatWifi;
        return tpl.replace(/\\{essid\\}/g, info.essid)
                  .replace(/\\{signalStrength\\}/g, String(info.signal))
                  .replace(/\\{ifname\\}/g, info.ifname)
                  .replace(/\\{icon\\}/g, root.pickIcon(info.signal))
                  .replace(/\\{ipaddr\\}/g, "")
                  .replace(/\\{cidr\\}/g, "")
                  .replace(/\\{bandwidthUpBytes\\}/g, "")
                  .replace(/\\{bandwidthDownBytes\\}/g, "")
                  .replace(/\\{bandwidthTotalBytes\\}/g, "");
    }

    color: root.isDisconnected ? root.disconnectedBg : root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: label.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(label.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    Text {
        id: label
        anchors.centerIn: parent
        text: root.formattedText()
        color: root.isDisconnected ? root.disconnectedFg : root.fgColor
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: root.boldFont
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: (root.onClickCmd.length > 0 || root.formatAlt.length > 0) ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: {
            if (root.onClickCmd.length > 0) Quickshell.execDetached(["sh", "-c", root.onClickCmd]);
            else if (root.formatAlt.length > 0) root.showingAlt = !root.showingAlt;
        }
    }
}
"""


def _component_tray_widget() -> str:
    return """pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.SystemTray
import Quickshell.Widgets
import ".."

Rectangle {
    id: root
    property int iconSize: 16
    property int itemSpacing: 6
    property color bgColor: Theme.moduleBg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property real itemOpacity: 1.0

    visible: SystemTray.items.values.length > 0
    color: root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: row.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(row.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: root.itemSpacing

        Repeater {
            model: SystemTray.items
            delegate: Item {
                id: trayItem
                required property var modelData
                implicitWidth: root.iconSize + 4
                implicitHeight: root.iconSize + 4

                IconImage {
                    anchors.centerIn: parent
                    implicitSize: root.iconSize
                    source: trayItem.modelData.icon
                }

                QsMenuAnchor {
                    id: menuAnchor
                    menu: trayItem.modelData.menu
                    anchor.item: trayItem
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: function(mouse) {
                        const item = trayItem.modelData;
                        if (mouse.button === Qt.LeftButton) {
                            if (item.onlyMenu && item.hasMenu) menuAnchor.open();
                            else item.activate();
                        } else if (mouse.button === Qt.RightButton) {
                            if (item.hasMenu) menuAnchor.open();
                            else item.secondaryActivate();
                        } else if (mouse.button === Qt.MiddleButton) {
                            item.secondaryActivate();
                        }
                    }
                }

                WheelHandler {
                    onWheel: function(event) {
                        trayItem.modelData.scroll(event.angleDelta.y, false);
                    }
                }
            }
        }
    }
}
"""


def _component_custom_widget() -> str:
    return """import QtQuick
import Quickshell
import Quickshell.Io
import ".."

Rectangle {
    id: root
    property string execCmd: ""
    property int intervalMs: 0
    property bool continuous: false
    property string returnType: ""
    property string formatStr: "{}"
    property var formatIcons: ({})
    property string onClickCmd: ""
    property string onClickRightCmd: ""
    property string onClickMiddleCmd: ""
    property string onScrollUpCmd: ""
    property string onScrollDownCmd: ""
    property string defaultText: ""
    property string displayText: defaultText
    property string altText: ""
    property string tooltipText: ""
    property string cssClass: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    function formatOutput(textVal, altVal, pctVal) {
        let iconVal = "";
        if (root.formatIcons) {
            if (altVal && root.formatIcons[altVal] !== undefined) iconVal = String(root.formatIcons[altVal]);
            else if (root.formatIcons["default"] !== undefined) iconVal = String(root.formatIcons["default"]);
        }
        return root.formatStr.replace(/\\{\\}/g, textVal)
                             .replace(/\\{text\\}/g, textVal)
                             .replace(/\\{alt\\}/g, altVal)
                             .replace(/\\{icon\\}/g, iconVal)
                             .replace(/\\{percentage\\}/g, pctVal);
    }

    function handleOutput(raw) {
        const trimmed = raw ? raw.trim() : "";
        if (trimmed.length === 0) return;
        if (root.returnType === "json") {
            try {
                const obj = JSON.parse(trimmed);
                const t = obj.text !== undefined ? String(obj.text) : "";
                const a = obj.alt !== undefined ? String(obj.alt) : "";
                const pct = obj.percentage !== undefined ? String(obj.percentage) : "";
                root.altText = a;
                root.tooltipText = obj.tooltip !== undefined ? String(obj.tooltip) : "";
                root.cssClass = obj["class"] !== undefined ? String(obj["class"]) : "";
                root.displayText = root.formatOutput(t, a, pct);
                return;
            } catch (e) {}
        }
        root.displayText = root.formatOutput(trimmed, "", "");
    }

    Component.onCompleted: {
        if (root.execCmd.length > 0 && !root.continuous && root.intervalMs <= 0) {
            pollProc.running = true;
        }
    }

    Timer {
        interval: Math.max(100, root.intervalMs)
        repeat: true
        running: root.execCmd.length > 0 && !root.continuous && root.intervalMs > 0
        triggeredOnStart: true
        onTriggered: {
            if (!pollProc.running) pollProc.running = true;
        }
    }

    Process {
        id: pollProc
        command: root.execCmd.length > 0 ? ["sh", "-c", root.execCmd] : []
        running: false
        stdout: StdioCollector {
            id: pollOut
            waitForEnd: true
        }
        onExited: function(exitCode, exitStatus) {
            if (exitCode === 0) root.handleOutput(pollOut.text);
        }
    }

    Process {
        id: streamProc
        command: root.execCmd.length > 0 ? ["sh", "-c", root.execCmd] : []
        running: root.execCmd.length > 0 && root.continuous
        stdout: SplitParser {
            onRead: function(line) {
                root.handleOutput(line);
            }
        }
    }

    color: root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: label.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(label.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    Text {
        id: label
        anchors.centerIn: parent
        text: root.displayText
        color: root.fgColor
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: root.boldFont
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        cursorShape: (root.onClickCmd.length > 0 || root.onClickRightCmd.length > 0 || root.onClickMiddleCmd.length > 0) ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: function(mouse) {
            let cmd = "";
            if (mouse.button === Qt.LeftButton) cmd = root.onClickCmd;
            else if (mouse.button === Qt.RightButton) cmd = root.onClickRightCmd;
            else if (mouse.button === Qt.MiddleButton) cmd = root.onClickMiddleCmd;
            if (cmd.length > 0) {
                Quickshell.execDetached(["sh", "-c", cmd]);
                if (!root.continuous && root.execCmd.length > 0 && !pollProc.running) {
                    pollProc.running = true;
                }
            }
        }
    }

    WheelHandler {
        onWheel: function(event) {
            if (event.angleDelta.y > 0 && root.onScrollUpCmd.length > 0) {
                Quickshell.execDetached(["sh", "-c", root.onScrollUpCmd]);
            } else if (event.angleDelta.y < 0 && root.onScrollDownCmd.length > 0) {
                Quickshell.execDetached(["sh", "-c", root.onScrollDownCmd]);
            }
        }
    }
}
"""


def _component_stub_widget() -> str:
    return """import QtQuick
import Quickshell
import ".."

Rectangle {
    id: root
    property string moduleName: ""
    property string labelText: ""
    property string onClickCmd: ""
    property color bgColor: Theme.moduleBg
    property color fgColor: Theme.moduleFg
    property int borderRadius: Theme.moduleRadius
    property int borderWidth: 0
    property color borderColor: "transparent"
    property int paddingH: Theme.modulePaddingH
    property int paddingV: Theme.modulePaddingV
    property string fontFamily: Theme.fontFamily
    property int fontSize: Theme.fontSize
    property bool boldFont: false
    property real itemOpacity: 1.0

    color: root.bgColor
    radius: root.borderRadius
    border.width: root.borderWidth
    border.color: root.borderColor
    opacity: root.itemOpacity
    implicitWidth: label.implicitWidth + root.paddingH * 2
    implicitHeight: Math.max(label.implicitHeight + root.paddingV * 2, Theme.barHeight - 8)

    Text {
        id: label
        anchors.centerIn: parent
        text: root.labelText.length > 0 ? root.labelText : ("[" + root.moduleName + "]")
        color: root.fgColor
        font.family: root.fontFamily
        font.pixelSize: root.fontSize
        font.bold: root.boldFont
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.onClickCmd.length > 0
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: Quickshell.execDetached(["sh", "-c", root.onClickCmd])
    }
}
"""


_COMPONENT_GENERATORS = {
    "components/HyprlandWorkspaces.qml": _component_hyprland_workspaces,
    "components/NiriWorkspaces.qml": _component_niri_workspaces,
    "components/ClockWidget.qml": _component_clock_widget,
    "components/PulseaudioWidget.qml": _component_pulseaudio_widget,
    "components/BatteryWidget.qml": _component_battery_widget,
    "components/NetworkWidget.qml": _component_network_widget,
    "components/TrayWidget.qml": _component_tray_widget,
    "components/CustomModuleWidget.qml": _component_custom_widget,
    "components/StubModuleWidget.qml": _component_stub_widget,
}


def _extract_common_style_props(
    style: StyleProps,
    named_colors: dict[str, str],
    include_fg: bool = True,
) -> list[tuple[str, str]]:
    """Convert non-None ModuleSpec.style properties into QML property assignments."""
    props: list[tuple[str, str]] = []
    if style.background is not None:
        props.append(("bgColor", _qml_str(_normalize_color(style.background, named_colors, "transparent"))))
    if include_fg and style.color is not None:
        props.append(("fgColor", _qml_str(_normalize_color(style.color, named_colors, "#cdd6f4"))))
    if style.border_radius is not None:
        props.append(("borderRadius", str(int(style.border_radius))))
    if style.border_width is not None:
        props.append(("borderWidth", str(int(style.border_width))))
    if style.border_color is not None:
        props.append(("borderColor", _qml_str(_normalize_color(style.border_color, named_colors, "transparent"))))

    pad_h = style.padding_left if style.padding_left is not None else style.padding_right
    if pad_h is not None:
        props.append(("paddingH", str(int(pad_h))))
    pad_v = style.padding_top if style.padding_top is not None else style.padding_bottom
    if pad_v is not None:
        props.append(("paddingV", str(int(pad_v))))

    if include_fg and style.font_family is not None:
        props.append(("fontFamily", _qml_str(_clean_font_family(style.font_family))))
    if include_fg and style.font_size is not None:
        props.append(("fontSize", str(int(style.font_size))))
    if include_fg and _is_bold_weight(style.font_weight):
        props.append(("boldFont", "true"))
    if style.opacity is not None:
        props.append(("itemOpacity", str(float(style.opacity))))
    return props


def _extract_persistent_workspace_ids(raw_persistent: Any) -> list[int]:
    """Extract numeric workspace IDs from Waybar persistent-workspaces config."""
    ids: list[int] = []
    if isinstance(raw_persistent, dict):
        for val in raw_persistent.values():
            if isinstance(val, int) and val > 0:
                ids.extend(range(1, val + 1))
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, int):
                        ids.append(item)
                    elif isinstance(item, str) and item.isdigit():
                        ids.append(int(item))
    elif isinstance(raw_persistent, list):
        for item in raw_persistent:
            if isinstance(item, int):
                ids.append(item)
    return sorted(set(ids))


def _apply_workspace_styles(
    props: list[tuple[str, str]],
    mod: ModuleSpec,
    tokens: ThemeTokens,
) -> None:
    """Populate workspace button and state colors from module/tokens state styles."""
    named = tokens.named_colors
    btn_style = (
        tokens.module_styles.get("workspaces_button")
        or tokens.module_styles.get("workspaces button")
        or tokens.module_styles.get("#workspaces button")
        or StyleProps()
    )
    if btn_style.background is not None:
        props.append(("buttonBg", _qml_str(_normalize_color(btn_style.background, named, "transparent"))))
    if btn_style.color is not None:
        props.append(("buttonFg", _qml_str(_normalize_color(btn_style.color, named))))
    if btn_style.border_radius is not None:
        props.append(("buttonRadius", str(int(btn_style.border_radius))))

    merged_states: dict[str, StyleProps] = {}
    for key in ("workspaces", "#workspaces", "workspaces_button", "workspaces button", "#workspaces button"):
        if key in tokens.state_styles:
            merged_states.update(tokens.state_styles[key])
    merged_states.update(mod.states)

    state_prop_map = {
        "active": ("activeBg", "activeFg"),
        "focused": ("focusedBg", "focusedFg"),
        "urgent": ("urgentBg", "urgentFg"),
    }
    for state_name, (bg_prop, fg_prop) in state_prop_map.items():
        st = merged_states.get(state_name)
        if not st:
            continue
        if st.background is not None:
            props.append((bg_prop, _qml_str(_normalize_color(st.background, named))))
        if st.color is not None:
            props.append((fg_prop, _qml_str(_normalize_color(st.color, named))))


def _canonical_module_kind(mod: ModuleSpec) -> str:
    """Resolve canonical module kind from ModuleSpec.kind or raw_name."""
    base = mod.kind.strip().lower()
    raw_base = mod.raw_name.split("#", 1)[0].strip().lower()
    if base in {"hyprland/workspaces", "niri/workspaces", "clock", "pulseaudio", "battery", "network", "tray", "custom"}:
        return base
    if raw_base.startswith("custom/"):
        return "custom"
    if raw_base == "wireplumber":
        return "pulseaudio"
    return raw_base or base


def _emit_module_instance(
    mod: ModuleSpec,
    tokens: ThemeTokens,
    has_outputs_filter: bool,
    bar_window_id: str,
) -> tuple[str, str, ModuleConversionNote]:
    """Build (qml_element_block, component_rel_path, ModuleConversionNote) for a module."""
    kind = _canonical_module_kind(mod)
    cfg = mod.config
    named = tokens.named_colors
    props: list[tuple[str, str]] = []
    notes: list[str] = []

    if kind == "hyprland/workspaces":
        comp_name = "HyprlandWorkspaces"
        comp_file = "components/HyprlandWorkspaces.qml"
        support_level = "native"
        backend = "Quickshell.Hyprland"
        if isinstance(cfg.get("format-icons"), dict):
            props.append(("formatIcons", _qml_literal(cfg["format-icons"])))
        persistent_ids = _extract_persistent_workspace_ids(cfg.get("persistent-workspaces"))
        if persistent_ids:
            props.append(("persistentIds", _qml_literal(persistent_ids)))
        if "all-outputs" in cfg:
            props.append(("allOutputs", _qml_literal(bool(cfg["all-outputs"]))))
        if has_outputs_filter or not bool(cfg.get("all-outputs", True)):
            props.append(("monitorName", f"{bar_window_id}.modelData.name"))
        if cfg.get("disable-scroll") is True:
            props.append(("enableScroll", "false"))
        props.extend(_extract_common_style_props(mod.style, named))
        _apply_workspace_styles(props, mod, tokens)

    elif kind == "niri/workspaces":
        comp_name = "NiriWorkspaces"
        comp_file = "components/NiriWorkspaces.qml"
        support_level = "process"
        backend = "niri msg --json"
        notes.append("Uses niri CLI IPC; optionally upgrade to qml-niri plugin for zero-process IPC")
        if isinstance(cfg.get("format-icons"), dict):
            props.append(("formatIcons", _qml_literal(cfg["format-icons"])))
        if "all-outputs" in cfg:
            props.append(("allOutputs", _qml_literal(bool(cfg["all-outputs"]))))
        if has_outputs_filter or not bool(cfg.get("all-outputs", True)):
            props.append(("monitorName", f"{bar_window_id}.modelData.name"))
        if cfg.get("disable-scroll") is True:
            props.append(("enableScroll", "false"))
        props.extend(_extract_common_style_props(mod.style, named))
        _apply_workspace_styles(props, mod, tokens)

    elif kind == "clock":
        comp_name = "ClockWidget"
        comp_file = "components/ClockWidget.qml"
        support_level = "native"
        backend = "Quickshell.SystemClock"
        fmt_raw = str(cfg.get("format", "{:%H:%M}"))
        qt_fmt, use_sec, fmt_notes = _waybar_clock_format_to_qt(fmt_raw)
        notes.extend(fmt_notes)
        props.append(("qtFormat", _qml_str(qt_fmt)))
        if isinstance(cfg.get("format-alt"), str) and cfg["format-alt"]:
            qt_alt, alt_sec, alt_notes = _waybar_clock_format_to_qt(cfg["format-alt"])
            notes.extend(alt_notes)
            use_sec = use_sec or alt_sec
            props.append(("qtFormatAlt", _qml_str(qt_alt)))
        if use_sec:
            props.append(("useSeconds", "true"))
        if isinstance(cfg.get("on-click"), str) and cfg["on-click"]:
            props.append(("onClickCmd", _qml_str(cfg["on-click"])))
        if isinstance(cfg.get("on-click-right"), str) and cfg["on-click-right"]:
            props.append(("onClickRightCmd", _qml_str(cfg["on-click-right"])))
        props.extend(_extract_common_style_props(mod.style, named))

    elif kind == "pulseaudio":
        comp_name = "PulseaudioWidget"
        comp_file = "components/PulseaudioWidget.qml"
        support_level = "native"
        backend = "Quickshell.Services.Pipewire"
        if isinstance(cfg.get("format"), str):
            props.append(("formatStr", _qml_str(cfg["format"])))
        if isinstance(cfg.get("format-muted"), str):
            props.append(("formatMuted", _qml_str(cfg["format-muted"])))
        if isinstance(cfg.get("format-source"), str):
            props.append(("formatSource", _qml_str(cfg["format-source"])))
        if isinstance(cfg.get("format-icons"), (list, dict)):
            props.append(("formatIcons", _qml_literal(cfg["format-icons"])))
        if cfg.get("scroll-step") is not None:
            try:
                step_val = max(0.005, min(0.5, float(cfg["scroll-step"]) / 100.0))
                props.append(("scrollStep", f"{step_val:.4g}"))
            except (TypeError, ValueError):
                pass
        for cfg_key, prop_key in (
            ("on-click", "onClickCmd"),
            ("on-click-right", "onClickRightCmd"),
            ("on-scroll-up", "onScrollUpCmd"),
            ("on-scroll-down", "onScrollDownCmd"),
        ):
            if isinstance(cfg.get(cfg_key), str) and cfg[cfg_key]:
                props.append((prop_key, _qml_str(cfg[cfg_key])))
        muted_st = mod.states.get("muted") or tokens.state_styles.get("pulseaudio", {}).get("muted")
        if muted_st:
            if muted_st.background is not None:
                props.append(("mutedBg", _qml_str(_normalize_color(muted_st.background, named))))
            if muted_st.color is not None:
                props.append(("mutedFg", _qml_str(_normalize_color(muted_st.color, named))))
        props.extend(_extract_common_style_props(mod.style, named))

    elif kind == "battery":
        comp_name = "BatteryWidget"
        comp_file = "components/BatteryWidget.qml"
        support_level = "native"
        backend = "Quickshell.Services.UPower"
        for cfg_key, prop_key in (
            ("format", "formatStr"),
            ("format-charging", "formatCharging"),
            ("format-plugged", "formatPlugged"),
            ("format-full", "formatFull"),
            ("on-click", "onClickCmd"),
        ):
            if isinstance(cfg.get(cfg_key), str) and cfg[cfg_key]:
                props.append((prop_key, _qml_str(cfg[cfg_key])))
        if isinstance(cfg.get("format-icons"), list):
            props.append(("formatIcons", _qml_literal(cfg["format-icons"])))
        states_cfg = cfg.get("states")
        if isinstance(states_cfg, dict):
            if isinstance(states_cfg.get("warning"), (int, float)):
                props.append(("warningLevel", str(int(states_cfg["warning"]))))
            if isinstance(states_cfg.get("critical"), (int, float)):
                props.append(("criticalLevel", str(int(states_cfg["critical"]))))
        bat_states = {**tokens.state_styles.get("battery", {}), **mod.states}
        for st_name, (bg_p, fg_p) in (
            ("warning", ("warningBg", "warningFg")),
            ("critical", ("criticalBg", "criticalFg")),
            ("charging", ("chargingBg", "chargingFg")),
        ):
            st = bat_states.get(st_name)
            if not st:
                continue
            if st.background is not None:
                props.append((bg_p, _qml_str(_normalize_color(st.background, named))))
            if st.color is not None:
                props.append((fg_p, _qml_str(_normalize_color(st.color, named))))
        props.extend(_extract_common_style_props(mod.style, named))

    elif kind == "network":
        comp_name = "NetworkWidget"
        comp_file = "components/NetworkWidget.qml"
        backend = "Quickshell.Networking"
        unsupported_placeholders = []
        for fmt_key in ("format-wifi", "format-ethernet", "format-alt", "format"):
            fmt_val = cfg.get(fmt_key)
            if isinstance(fmt_val, str):
                for ph in ("{ipaddr}", "{cidr}", "{bandwidthUpBytes}", "{bandwidthDownBytes}", "{bandwidthTotalBytes}"):
                    if ph in fmt_val and ph not in unsupported_placeholders:
                        unsupported_placeholders.append(ph)
        if unsupported_placeholders:
            support_level = "partial"
            notes.append(
                "Quickshell.Networking does not expose "
                + ", ".join(unsupported_placeholders)
                + "; rendered empty"
            )
        else:
            support_level = "native"
        for cfg_key, prop_key in (
            ("format-wifi", "formatWifi"),
            ("format-ethernet", "formatEthernet"),
            ("format-disconnected", "formatDisconnected"),
            ("format-alt", "formatAlt"),
            ("on-click", "onClickCmd"),
        ):
            if isinstance(cfg.get(cfg_key), str) and cfg[cfg_key]:
                props.append((prop_key, _qml_str(cfg[cfg_key])))
        if isinstance(cfg.get("format-icons"), list):
            props.append(("formatIcons", _qml_literal(cfg["format-icons"])))
        disc_st = mod.states.get("disconnected") or tokens.state_styles.get("network", {}).get("disconnected")
        if disc_st:
            if disc_st.background is not None:
                props.append(("disconnectedBg", _qml_str(_normalize_color(disc_st.background, named))))
            if disc_st.color is not None:
                props.append(("disconnectedFg", _qml_str(_normalize_color(disc_st.color, named))))
        props.extend(_extract_common_style_props(mod.style, named))

    elif kind == "tray":
        comp_name = "TrayWidget"
        comp_file = "components/TrayWidget.qml"
        support_level = "native"
        backend = "Quickshell.Services.SystemTray"
        if isinstance(cfg.get("icon-size"), (int, float)):
            props.append(("iconSize", str(int(cfg["icon-size"]))))
        if isinstance(cfg.get("spacing"), (int, float)):
            props.append(("itemSpacing", str(int(cfg["spacing"]))))
        props.extend(_extract_common_style_props(mod.style, named, include_fg=False))

    elif kind == "custom":
        comp_name = "CustomModuleWidget"
        comp_file = "components/CustomModuleWidget.qml"
        support_level = "process"
        backend = "Quickshell.Io.Process"
        if isinstance(cfg.get("exec"), str) and cfg["exec"]:
            props.append(("execCmd", _qml_str(cfg["exec"])))
        interval_val = cfg.get("interval")
        if interval_val == "once" or interval_val is None:
            props.append(("intervalMs", "0"))
            props.append(("continuous", "false"))
        elif isinstance(interval_val, (int, float)):
            if interval_val <= 0:
                props.append(("intervalMs", "0"))
                props.append(("continuous", "true"))
            else:
                props.append(("intervalMs", str(int(float(interval_val) * 1000))))
                props.append(("continuous", "false"))
        if isinstance(cfg.get("return-type"), str) and cfg["return-type"]:
            props.append(("returnType", _qml_str(cfg["return-type"])))
        if isinstance(cfg.get("format"), str):
            props.append(("formatStr", _qml_str(cfg["format"])))
        if isinstance(cfg.get("format-icons"), dict):
            props.append(("formatIcons", _qml_literal(cfg["format-icons"])))
        for cfg_key, prop_key in (
            ("on-click", "onClickCmd"),
            ("on-click-right", "onClickRightCmd"),
            ("on-click-middle", "onClickMiddleCmd"),
            ("on-scroll-up", "onScrollUpCmd"),
            ("on-scroll-down", "onScrollDownCmd"),
        ):
            if isinstance(cfg.get(cfg_key), str) and cfg[cfg_key]:
                props.append((prop_key, _qml_str(cfg[cfg_key])))
        if not cfg.get("exec") and isinstance(cfg.get("format"), str):
            props.append(("defaultText", _qml_str(cfg["format"])))
        if isinstance(cfg.get("exec-if"), str) and cfg["exec-if"]:
            notes.append(f"exec-if guard ({cfg['exec-if']}) not automatically wrapped; add condition if needed")
        props.extend(_extract_common_style_props(mod.style, named))

    else:
        comp_name = "StubModuleWidget"
        comp_file = "components/StubModuleWidget.qml"
        support_level = "stub"
        backend = "stub"
        notes.append(f"No built-in Quickshell mapping for '{mod.raw_name}'; emitted clickable stub badge")
        props.append(("moduleName", _qml_str(mod.raw_name)))
        if isinstance(cfg.get("format"), str) and cfg["format"]:
            props.append(("labelText", _qml_str(cfg["format"])))
        if isinstance(cfg.get("on-click"), str) and cfg["on-click"]:
            props.append(("onClickCmd", _qml_str(cfg["on-click"])))
        props.extend(_extract_common_style_props(mod.style, named))

    # Deduplicate property assignments while keeping later overrides
    deduped: dict[str, str] = {}
    for prop_key, prop_val in props:
        deduped[prop_key] = prop_val

    prop_lines = [f"                        {k}: {v}" for k, v in deduped.items()]
    if prop_lines:
        instance_qml = f"                    {comp_name} {{\n" + "\n".join(prop_lines) + "\n                    }"
    else:
        instance_qml = f"                    {comp_name} {{}}"

    note = ModuleConversionNote(
        raw_name=mod.raw_name,
        component_file=comp_file,
        support_level=support_level,
        backend=backend,
        notes=notes,
    )
    return instance_qml, comp_file, note


def _render_bar_variants(
    bar: BarSpec,
    bar_index: int,
    total_bars: int,
    tokens: ThemeTokens,
    used_components: set[str],
    module_notes_by_name: dict[str, ModuleConversionNote],
) -> str:
    """Render a single Variants + PanelWindow block for one BarSpec."""
    pos = bar.position.lower() if bar.position else "top"
    vertical = pos in {"left", "right"}
    layer_enum = _VALID_LAYERS.get(bar.layer.lower() if bar.layer else "top", "WlrLayer.Top")
    exclusion_enum = "ExclusionMode.Auto" if bar.exclusive else "ExclusionMode.Ignore"

    if pos == "bottom":
        anchors = ["bottom: true", "left: true", "right: true"]
    elif pos == "left":
        anchors = ["top: true", "bottom: true", "left: true"]
    elif pos == "right":
        anchors = ["top: true", "bottom: true", "right: true"]
    else:
        anchors = ["top: true", "left: true", "right: true"]

    if not vertical and bar.width is not None and bar.width > 0:
        anchors = [a for a in anchors if a not in {"left: true", "right: true"}]

    ns = "waybar2qs" if total_bars == 1 else f"waybar2qs-{re.sub(r'[^a-zA-Z0-9_-]', '_', bar.name or str(bar_index))}"
    bar_window_id = f"barWindow{bar_index}" if total_bars > 1 else "barWindow"

    has_outputs = len(bar.outputs) > 0
    lines: list[str] = [
        "    Variants {",
        "        model: Quickshell.screens",
        "        PanelWindow {",
        f"            id: {bar_window_id}",
        "            required property var modelData",
        "            screen: modelData",
    ]
    if has_outputs:
        lines.append(f"            visible: {_qml_literal(bar.outputs)}.indexOf(modelData.name) !== -1")

    lines.append("            anchors {")
    for a in anchors:
        lines.append(f"                {a}")
    lines.append("            }")

    lines.append(f"            WlrLayershell.layer: {layer_enum}")
    lines.append(f"            WlrLayershell.namespace: {_qml_str(ns)}")
    if bar.margin_top:
        lines.append(f"            WlrLayershell.margins.top: {int(bar.margin_top)}")
    if bar.margin_bottom:
        lines.append(f"            WlrLayershell.margins.bottom: {int(bar.margin_bottom)}")
    if bar.margin_left:
        lines.append(f"            WlrLayershell.margins.left: {int(bar.margin_left)}")
    if bar.margin_right:
        lines.append(f"            WlrLayershell.margins.right: {int(bar.margin_right)}")

    lines.append(f"            exclusionMode: {exclusion_enum}")
    if vertical:
        width_val = bar.width if (bar.width is not None and bar.width > 0) else max(bar.height, 34)
        lines.append(f"            implicitWidth: {int(width_val)}")
    else:
        lines.append(f"            implicitHeight: {int(bar.height) if bar.height > 0 else 34}")
        if bar.width is not None and bar.width > 0:
            lines.append(f"            implicitWidth: {int(bar.width)}")

    lines.extend(
        [
            '            color: "transparent"',
            "",
            "            Rectangle {",
            "                anchors.fill: parent",
            "                color: Theme.barBg",
            "                radius: Theme.barRadius",
            "                border.width: Theme.barBorderWidth",
            "                border.color: Theme.barBorderColor",
            "",
            "                Item {",
            "                    anchors.fill: parent",
            "                    anchors.leftMargin: 6",
            "                    anchors.rightMargin: 6",
            "                    anchors.topMargin: 2",
            "                    anchors.bottomMargin: 2",
        ]
    )

    layout_type = "ColumnLayout" if vertical else "RowLayout"
    slots = (
        ("top", bar.modules_left, ["anchors.top: parent.top", "anchors.horizontalCenter: parent.horizontalCenter"] if vertical else ["anchors.left: parent.left", "anchors.verticalCenter: parent.verticalCenter"]),
        ("center", bar.modules_center, ["anchors.centerIn: parent"]),
        ("bottom" if vertical else "right", bar.modules_right, ["anchors.bottom: parent.bottom", "anchors.horizontalCenter: parent.horizontalCenter"] if vertical else ["anchors.right: parent.right", "anchors.verticalCenter: parent.verticalCenter"]),
    )

    for _slot_name, slot_modules, slot_anchors in slots:
        lines.append("")
        lines.append(f"                {layout_type} {{")
        for anchor_line in slot_anchors:
            lines.append(f"                    {anchor_line}")
        lines.append(f"                    spacing: {int(bar.spacing) if bar.spacing >= 0 else 6}")
        for mod in slot_modules:
            inst_qml, comp_file, note = _emit_module_instance(mod, tokens, has_outputs, bar_window_id)
            used_components.add(comp_file)
            if mod.raw_name not in module_notes_by_name:
                module_notes_by_name[mod.raw_name] = note
            lines.append(inst_qml)
        lines.append("                }")

    lines.extend(
        [
            "                }",
            "            }",
            "        }",
            "    }",
        ]
    )
    return "\n".join(lines)


def _render_shell_qml(
    bars: list[BarSpec],
    tokens: ThemeTokens,
    used_components: set[str],
    module_notes_by_name: dict[str, ModuleConversionNote],
) -> str:
    """Render root shell.qml containing ShellRoot and one Variants block per bar."""
    variant_blocks = [
        _render_bar_variants(bar, idx, len(bars), tokens, used_components, module_notes_by_name)
        for idx, bar in enumerate(bars)
    ]

    if not variant_blocks:
        return "import Quickshell\n\nShellRoot {}\n"

    imports = [
        "pragma ComponentBehavior: Bound",
        "import QtQuick",
        "import QtQuick.Layouts",
        "import Quickshell",
        "import Quickshell.Wayland",
        'import "."',
    ]
    if used_components:
        imports.append('import "components"')

    body = "\n\n".join(variant_blocks)
    return "\n".join(imports) + "\n\nShellRoot {\n" + body + "\n}\n"


def generate_quickshell_project(
    bars: list[BarSpec],
    tokens: ThemeTokens,
    output_dir: Path,
    report: ConversionReport,
    dry_run: bool = False,
) -> dict[str, str]:
    """Generate a complete Quickshell QML project from Waybar IR and theme tokens.

    Populates ``report.generated_files``, ``report.mapped_tokens``, and
    ``report.module_notes``. Writes files under ``output_dir`` unless ``dry_run``
    is True, and returns a mapping of ``{relative_path: file_content}``.
    """
    theme_ctx = _build_theme_context(bars, tokens)
    mapped_tokens: list[str] = []
    theme_qml = _render_theme_qml(theme_ctx, mapped_tokens)
    qmldir_txt = _render_qmldir()

    used_components: set[str] = set()
    module_notes_by_name: dict[str, ModuleConversionNote] = {}
    shell_qml = _render_shell_qml(bars, tokens, used_components, module_notes_by_name)

    files: dict[str, str] = {
        "qmldir": qmldir_txt,
        "Theme.qml": theme_qml,
        "shell.qml": shell_qml,
    }
    for comp_path in sorted(used_components):
        generator = _COMPONENT_GENERATORS[comp_path]
        files[comp_path] = generator()

    if not dry_run:
        for rel_path, content in files.items():
            target = output_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    report.mapped_tokens.extend(mapped_tokens)
    report.module_notes.extend(module_notes_by_name.values())
    report.generated_files.extend(sorted(files.keys()))
    return files
