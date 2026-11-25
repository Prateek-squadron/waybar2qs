"""Waybar GTK CSS parser and QML ThemeTokens extractor."""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from .ir import StyleProps, ThemeTokens, UnsupportedCssItem

# Standard CSS/SVG named colors (lowercase -> (r, g, b, a)).
_NAMED_COLORS: dict[str, tuple[int, int, int, float]] = {
    "transparent": (0, 0, 0, 0.0),
    "none": (0, 0, 0, 0.0),
    "aliceblue": (240, 248, 255, 1.0),
    "antiquewhite": (250, 235, 215, 1.0),
    "aqua": (0, 255, 255, 1.0),
    "aquamarine": (127, 255, 212, 1.0),
    "azure": (240, 255, 255, 1.0),
    "beige": (245, 245, 220, 1.0),
    "bisque": (255, 228, 196, 1.0),
    "black": (0, 0, 0, 1.0),
    "blanchedalmond": (255, 235, 205, 1.0),
    "blue": (0, 0, 255, 1.0),
    "blueviolet": (138, 43, 226, 1.0),
    "brown": (165, 42, 42, 1.0),
    "burlywood": (222, 184, 135, 1.0),
    "cadetblue": (95, 158, 160, 1.0),
    "chartreuse": (127, 255, 0, 1.0),
    "chocolate": (210, 105, 30, 1.0),
    "coral": (255, 127, 80, 1.0),
    "cornflowerblue": (100, 149, 237, 1.0),
    "cornsilk": (255, 248, 220, 1.0),
    "crimson": (220, 20, 60, 1.0),
    "cyan": (0, 255, 255, 1.0),
    "darkblue": (0, 0, 139, 1.0),
    "darkcyan": (0, 139, 139, 1.0),
    "darkgoldenrod": (184, 134, 11, 1.0),
    "darkgray": (169, 169, 169, 1.0),
    "darkgreen": (0, 100, 0, 1.0),
    "darkgrey": (169, 169, 169, 1.0),
    "darkkhaki": (189, 183, 107, 1.0),
    "darkmagenta": (139, 0, 139, 1.0),
    "darkolivegreen": (85, 107, 47, 1.0),
    "darkorange": (255, 140, 0, 1.0),
    "darkorchid": (153, 50, 204, 1.0),
    "darkred": (139, 0, 0, 1.0),
    "darksalmon": (233, 150, 122, 1.0),
    "darkseagreen": (143, 188, 143, 1.0),
    "darkslateblue": (72, 61, 139, 1.0),
    "darkslategray": (47, 79, 79, 1.0),
    "darkslategrey": (47, 79, 79, 1.0),
    "darkturquoise": (0, 206, 209, 1.0),
    "darkviolet": (148, 0, 211, 1.0),
    "deeppink": (255, 20, 147, 1.0),
    "deepskyblue": (0, 191, 255, 1.0),
    "dimgray": (105, 105, 105, 1.0),
    "dimgrey": (105, 105, 105, 1.0),
    "dodgerblue": (30, 144, 255, 1.0),
    "firebrick": (178, 34, 34, 1.0),
    "floralwhite": (255, 250, 240, 1.0),
    "forestgreen": (34, 139, 34, 1.0),
    "fuchsia": (255, 0, 255, 1.0),
    "gainsboro": (220, 220, 220, 1.0),
    "ghostwhite": (248, 248, 255, 1.0),
    "gold": (255, 215, 0, 1.0),
    "goldenrod": (218, 165, 32, 1.0),
    "gray": (128, 128, 128, 1.0),
    "green": (0, 128, 0, 1.0),
    "greenyellow": (173, 255, 47, 1.0),
    "grey": (128, 128, 128, 1.0),
    "honeydew": (240, 255, 240, 1.0),
    "hotpink": (255, 105, 180, 1.0),
    "indianred": (205, 92, 92, 1.0),
    "indigo": (75, 0, 130, 1.0),
    "ivory": (255, 255, 240, 1.0),
    "khaki": (240, 230, 140, 1.0),
    "lavender": (230, 230, 250, 1.0),
    "lavenderblush": (255, 240, 245, 1.0),
    "lawngreen": (124, 252, 0, 1.0),
    "lemonchiffon": (255, 250, 205, 1.0),
    "lightblue": (173, 216, 230, 1.0),
    "lightcoral": (240, 128, 128, 1.0),
    "lightcyan": (224, 255, 255, 1.0),
    "lightgoldenrodyellow": (250, 250, 210, 1.0),
    "lightgray": (211, 211, 211, 1.0),
    "lightgreen": (144, 238, 144, 1.0),
    "lightgrey": (211, 211, 211, 1.0),
    "lightpink": (255, 182, 193, 1.0),
    "lightsalmon": (255, 160, 122, 1.0),
    "lightseagreen": (32, 178, 170, 1.0),
    "lightskyblue": (135, 206, 250, 1.0),
    "lightslategray": (119, 136, 153, 1.0),
    "lightslategrey": (119, 136, 153, 1.0),
    "lightsteelblue": (176, 196, 222, 1.0),
    "lightyellow": (255, 255, 224, 1.0),
    "lime": (0, 255, 0, 1.0),
    "limegreen": (50, 205, 50, 1.0),
    "linen": (250, 240, 230, 1.0),
    "magenta": (255, 0, 255, 1.0),
    "maroon": (128, 0, 0, 1.0),
    "mediumaquamarine": (102, 205, 170, 1.0),
    "mediumblue": (0, 0, 205, 1.0),
    "mediumorchid": (186, 85, 211, 1.0),
    "mediumpurple": (147, 112, 219, 1.0),
    "mediumseagreen": (60, 179, 113, 1.0),
    "mediumslateblue": (123, 104, 238, 1.0),
    "mediumspringgreen": (0, 250, 154, 1.0),
    "mediumturquoise": (72, 209, 204, 1.0),
    "mediumvioletred": (199, 21, 133, 1.0),
    "midnightblue": (25, 25, 112, 1.0),
    "mintcream": (245, 255, 250, 1.0),
    "mistyrose": (255, 228, 225, 1.0),
    "moccasin": (255, 228, 181, 1.0),
    "navajowhite": (255, 222, 173, 1.0),
    "navy": (0, 0, 128, 1.0),
    "oldlace": (253, 245, 230, 1.0),
    "olive": (128, 128, 0, 1.0),
    "olivedrab": (107, 142, 35, 1.0),
    "orange": (255, 165, 0, 1.0),
    "orangered": (255, 69, 0, 1.0),
    "orchid": (218, 112, 214, 1.0),
    "palegoldenrod": (238, 232, 170, 1.0),
    "palegreen": (152, 251, 152, 1.0),
    "paleturquoise": (175, 238, 238, 1.0),
    "palevioletred": (219, 112, 147, 1.0),
    "papayawhip": (255, 239, 213, 1.0),
    "peachpuff": (255, 218, 185, 1.0),
    "peru": (205, 133, 63, 1.0),
    "pink": (255, 192, 203, 1.0),
    "plum": (221, 160, 221, 1.0),
    "powderblue": (176, 224, 230, 1.0),
    "purple": (128, 0, 128, 1.0),
    "rebeccapurple": (102, 51, 153, 1.0),
    "red": (255, 0, 0, 1.0),
    "rosybrown": (188, 143, 143, 1.0),
    "royalblue": (65, 105, 225, 1.0),
    "saddlebrown": (139, 69, 19, 1.0),
    "salmon": (250, 128, 114, 1.0),
    "sandybrown": (244, 164, 96, 1.0),
    "seagreen": (46, 139, 87, 1.0),
    "seashell": (255, 245, 238, 1.0),
    "sienna": (160, 82, 45, 1.0),
    "silver": (192, 192, 192, 1.0),
    "skyblue": (135, 206, 235, 1.0),
    "slateblue": (106, 90, 205, 1.0),
    "slategray": (112, 128, 144, 1.0),
    "slategrey": (112, 128, 144, 1.0),
    "snow": (255, 250, 250, 1.0),
    "springgreen": (0, 255, 127, 1.0),
    "steelblue": (70, 130, 180, 1.0),
    "tan": (210, 180, 140, 1.0),
    "teal": (0, 128, 128, 1.0),
    "thistle": (216, 191, 216, 1.0),
    "tomato": (255, 99, 71, 1.0),
    "turquoise": (64, 224, 208, 1.0),
    "violet": (238, 130, 238, 1.0),
    "wheat": (245, 222, 179, 1.0),
    "white": (255, 255, 255, 1.0),
    "whitesmoke": (245, 245, 245, 1.0),
    "yellow": (255, 255, 0, 1.0),
    "yellowgreen": (154, 205, 50, 1.0),
}

_BORDER_STYLES = frozenset({
    "none", "hidden", "dotted", "dashed", "solid",
    "double", "groove", "ridge", "inset", "outset",
})

_ANIMATION_PROPS = frozenset({
    "animation", "animation-name", "animation-duration", "animation-timing-function",
    "animation-delay", "animation-iteration-count", "animation-direction",
    "animation-fill-mode", "animation-play-state",
    "transition", "transition-property", "transition-duration",
    "transition-timing-function", "transition-delay",
})

_EFFECT_HINTS: dict[str, str] = {
    "box-shadow": "Use QtQuick.Effects.MultiEffect (shadowEnabled: true) for drop shadows.",
    "text-shadow": "Use QtQuick.Effects.MultiEffect or a secondary offset Text item.",
    "background-image": "Use a QML Image element inside the module container.",
    "backdrop-filter": "Use QtQuick.Effects.MultiEffect blur on a ShaderEffectSource.",
    "filter": "Use QtQuick.Effects.MultiEffect for blur/brightness/contrast effects.",
    "transform": "Use QML Item scale, rotation, or transform: Translate {}.",
}

_PSEUDO_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r":hover\b"), ":hover", "Use QML HoverHandler or MouseArea { hoverEnabled: true } with Behavior on color."),
    (re.compile(r":focus\b"), ":focus", "Use QML activeFocus / FocusScope bindings."),
    (re.compile(r":active\b"), ":active", "Use QML MouseArea.pressed or TapHandler.pressed."),
    (re.compile(r":first-child\b"), ":first-child", "Check (index === 0) inside QML Repeater delegates."),
    (re.compile(r":last-child\b"), ":last-child", "Check (index === count - 1) inside QML Repeater delegates."),
    (re.compile(r":nth-child\([^)]*\)"), ":nth-child(...)", "Use Repeater index arithmetic inside QML delegates."),
    (re.compile(r":not\([^)]*\)"), ":not(...)", "Express negated state conditions in QML property bindings."),
]

_KNOWN_STYLE_FIELDS = (
    "background", "color", "border_radius", "border_width", "border_color",
    "font_family", "font_size", "font_weight",
    "padding_top", "padding_right", "padding_bottom", "padding_left",
    "margin_top", "margin_right", "margin_bottom", "margin_left",
    "min_height", "min_width", "opacity",
)


def _strip_css_comments(text: str) -> str:
    """Strip /* ... */ CSS comments outside quotes, preserving exact line numbers."""
    out: list[str] = []
    n = len(text)
    i = 0
    quote: str | None = None
    escaped = False

    while i < n:
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n:
                c = text[i]
                if c == "*" and i + 1 < n and text[i + 1] == "/":
                    out.append("  ")
                    i += 2
                    break
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split text by separator outside quotes, parentheses, and brackets."""
    parts: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    quote: str | None = None
    escaped = False

    for ch in text:
        if quote is not None:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue

        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch == "(":
            paren_depth += 1
            buf.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
        elif ch == "[":
            bracket_depth += 1
            buf.append(ch)
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            buf.append(ch)
        elif ch == sep and paren_depth == 0 and bracket_depth == 0:
            parts.append("".join(buf))
            buf.clear()
        else:
            buf.append(ch)

    if buf or parts:
        parts.append("".join(buf))
    return parts


def _split_ws_top_level(text: str) -> list[str]:
    """Split text on whitespace outside parentheses and quotes."""
    parts: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    quote: str | None = None
    escaped = False

    for ch in text:
        if quote is not None:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue

        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch == "(":
            paren_depth += 1
            buf.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
        elif ch.isspace() and paren_depth == 0:
            if buf:
                parts.append("".join(buf))
                buf.clear()
        else:
            buf.append(ch)

    if buf:
        parts.append("".join(buf))
    return parts


def _clamp_int(val: float, lo: int = 0, hi: int = 255) -> int:
    return max(lo, min(hi, round(val)))


def _clamp_float(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _rgba_to_qml(r: int, g: int, b: int, a: float) -> str:
    """Format RGBA tuple into QML-valid #RRGGBB or #AARRGGBB (alpha first!)."""
    ri = _clamp_int(r)
    gi = _clamp_int(g)
    bi = _clamp_int(b)
    ai = _clamp_int(_clamp_float(a) * 255.0)
    if ai >= 255:
        return f"#{ri:02x}{gi:02x}{bi:02x}"
    return f"#{ai:02x}{ri:02x}{gi:02x}{bi:02x}"


def _parse_channel_255(token: str) -> float | None:
    token = token.strip()
    if token.endswith("%"):
        try:
            return float(token[:-1]) * 255.0 / 100.0
        except ValueError:
            return None
    try:
        return float(token)
    except ValueError:
        return None


def _parse_unit_float(token: str) -> float | None:
    token = token.strip()
    if token.endswith("%"):
        try:
            return float(token[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(token)
    except ValueError:
        return None


def _parse_hex_rgba(expr: str) -> tuple[int, int, int, float] | None:
    h = expr[1:]
    if not re.fullmatch(r"[0-9a-fA-F]+", h):
        return None
    if len(h) == 3:
        r, g, b = (int(c * 2, 16) for c in h)
        return (r, g, b, 1.0)
    if len(h) == 4:
        r, g, b, a = (int(c * 2, 16) for c in h)
        return (r, g, b, a / 255.0)
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    if len(h) == 8:
        return (
            int(h[0:2], 16),
            int(h[2:4], 16),
            int(h[4:6], 16),
            int(h[6:8], 16) / 255.0,
        )
    return None


class _ColorResolver:
    """Resolves CSS & GTK color expressions into QML-valid color strings."""

    def __init__(self) -> None:
        self.raw_defs: dict[str, tuple[str, int]] = {}
        self.resolved_rgba: dict[str, tuple[int, int, int, float]] = {}
        self.resolved_defs: dict[str, str] = {}

    def add_define(self, name: str, raw_expr: str, line: int = 0) -> None:
        """Register an @define-color entry and eagerly resolve if possible."""
        cleaned = raw_expr.strip()
        self.raw_defs[name] = (cleaned, line)
        self.resolved_rgba.pop(name, None)
        self.resolved_defs.pop(name, None)
        rgba = self.resolve_rgba(cleaned, stack=frozenset({name}))
        if rgba is not None:
            self.resolved_rgba[name] = rgba
            qml_val = self._format_qml_from_expr(cleaned, rgba)
            self.resolved_defs[name] = qml_val

    def resolve_named_all(self) -> tuple[dict[str, str], list[tuple[str, str, int]]]:
        """Resolve all @define-color entries, returning (resolved_map, unresolved_list)."""
        unresolved: list[tuple[str, str, int]] = []
        for name, (raw_expr, line) in self.raw_defs.items():
            if name not in self.resolved_defs:
                rgba = self.resolve_rgba(raw_expr, stack=frozenset({name}))
                if rgba is not None:
                    self.resolved_rgba[name] = rgba
                    self.resolved_defs[name] = self._format_qml_from_expr(raw_expr, rgba)
                else:
                    unresolved.append((name, raw_expr, line))
        return dict(self.resolved_defs), unresolved

    @staticmethod
    def _format_qml_from_expr(expr: str, rgba: tuple[int, int, int, float]) -> str:
        lower = expr.strip().lower()
        if lower in ("transparent", "none"):
            return "transparent"
        if lower in _NAMED_COLORS:
            return lower
        r, g, b, a = rgba
        if a <= 0.0:
            return "#00000000" if lower.startswith("rgba") else "transparent"
        return _rgba_to_qml(r, g, b, a)

    def resolve_to_qml(
        self, expr: str, stack: frozenset[str] = frozenset()
    ) -> str | None:
        """Resolve a color expression to a QML-valid color string or None."""
        cleaned = expr.strip()
        if not cleaned:
            return None
        lower = cleaned.lower()
        if lower in ("transparent", "none"):
            return "transparent"
        if lower in _NAMED_COLORS:
            return lower
        if cleaned.startswith("@"):
            ref_name = cleaned[1:].strip()
            if ref_name in self.resolved_defs:
                return self.resolved_defs[ref_name]

        rgba = self.resolve_rgba(cleaned, stack=stack)
        if rgba is None:
            return None
        return self._format_qml_from_expr(cleaned, rgba)

    def resolve_rgba(
        self, expr: str, stack: frozenset[str] = frozenset()
    ) -> tuple[int, int, int, float] | None:
        """Resolve a color expression to an (r, g, b, a) tuple."""
        cleaned = expr.strip()
        if not cleaned:
            return None
        lower = cleaned.lower()

        if lower in _NAMED_COLORS:
            return _NAMED_COLORS[lower]

        if cleaned.startswith("#"):
            return _parse_hex_rgba(cleaned)

        if cleaned.startswith("@"):
            ref_name = cleaned[1:].strip()
            if ref_name in stack:
                return None
            if ref_name in self.resolved_rgba:
                return self.resolved_rgba[ref_name]
            if ref_name in self.raw_defs:
                raw_expr, _ = self.raw_defs[ref_name]
                return self.resolve_rgba(raw_expr, stack=stack | {ref_name})
            return None

        m = re.fullmatch(r"([a-zA-Z_-]+)\((.*)\)", cleaned, re.DOTALL)
        if not m:
            return None
        func = m.group(1).lower()
        inner = m.group(2).strip()
        return self._eval_color_func(func, inner, stack)

    def _eval_color_func(
        self, func: str, inner: str, stack: frozenset[str]
    ) -> tuple[int, int, int, float] | None:
        if func in ("rgb", "rgba"):
            return self._parse_rgb_func(inner)
        if func in ("hsl", "hsla"):
            return self._parse_hsl_func(inner)

        args = [a.strip() for a in _split_top_level(inner, ",") if a.strip()]
        if func == "alpha" and len(args) == 2:
            base = self.resolve_rgba(args[0], stack)
            factor = _parse_unit_float(args[1])
            if base is None or factor is None:
                return None
            return (base[0], base[1], base[2], _clamp_float(base[3] * factor))

        if func == "shade" and len(args) == 2:
            base = self.resolve_rgba(args[0], stack)
            factor = _parse_unit_float(args[1])
            if base is None or factor is None:
                return None
            return self._shade_rgba(base, factor)

        if func == "lighter" and len(args) == 1:
            base = self.resolve_rgba(args[0], stack)
            return self._shade_rgba(base, 1.3) if base is not None else None

        if func == "darker" and len(args) == 1:
            base = self.resolve_rgba(args[0], stack)
            return self._shade_rgba(base, 0.7) if base is not None else None

        if func == "mix" and len(args) == 3:
            c1 = self.resolve_rgba(args[0], stack)
            c2 = self.resolve_rgba(args[1], stack)
            ratio = _parse_unit_float(args[2])
            if c1 is None or c2 is None or ratio is None:
                return None
            t = _clamp_float(ratio)
            return (
                _clamp_int(c1[0] * (1.0 - t) + c2[0] * t),
                _clamp_int(c1[1] * (1.0 - t) + c2[1] * t),
                _clamp_int(c1[2] * (1.0 - t) + c2[2] * t),
                _clamp_float(c1[3] * (1.0 - t) + c2[3] * t),
            )

        return None

    @staticmethod
    def _shade_rgba(
        rgba: tuple[int, int, int, float], factor: float
    ) -> tuple[int, int, int, float]:
        r, g, b, a = rgba
        h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        if l == 0.0 and factor > 1.0:
            l = min(1.0, (factor - 1.0) * 0.2)
        else:
            l = _clamp_float(l * max(0.0, factor))
        nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
        return (_clamp_int(nr * 255.0), _clamp_int(ng * 255.0), _clamp_int(nb * 255.0), a)

    @staticmethod
    def _parse_rgb_func(inner: str) -> tuple[int, int, int, float] | None:
        # Support comma-separated and CSS4 space/slash syntax: rgb(r g b / a)
        if "," in inner:
            parts = [p.strip() for p in _split_top_level(inner, ",")]
        else:
            slash_parts = inner.split("/")
            parts = _split_ws_top_level(slash_parts[0])
            if len(slash_parts) == 2:
                parts.append(slash_parts[1].strip())
            elif len(slash_parts) > 2:
                return None

        if len(parts) not in (3, 4):
            return None
        r = _parse_channel_255(parts[0])
        g = _parse_channel_255(parts[1])
        b = _parse_channel_255(parts[2])
        a = _parse_unit_float(parts[3]) if len(parts) == 4 else 1.0
        if r is None or g is None or b is None or a is None:
            return None
        return (_clamp_int(r), _clamp_int(g), _clamp_int(b), _clamp_float(a))

    @staticmethod
    def _parse_hsl_func(inner: str) -> tuple[int, int, int, float] | None:
        if "," in inner:
            parts = [p.strip() for p in _split_top_level(inner, ",")]
        else:
            slash_parts = inner.split("/")
            parts = _split_ws_top_level(slash_parts[0])
            if len(slash_parts) == 2:
                parts.append(slash_parts[1].strip())
            elif len(slash_parts) > 2:
                return None

        if len(parts) not in (3, 4):
            return None
        hue_raw = parts[0].strip().lower()
        for suffix in ("deg", "turn", "rad"):
            if hue_raw.endswith(suffix):
                hue_raw = hue_raw[: -len(suffix)].strip()
                break
        try:
            hue_deg = float(hue_raw)
        except ValueError:
            return None
        if parts[0].strip().lower().endswith("turn"):
            hue_deg *= 360.0
        s = _parse_unit_float(parts[1])
        l = _parse_unit_float(parts[2])
        a = _parse_unit_float(parts[3]) if len(parts) == 4 else 1.0
        if s is None or l is None or a is None:
            return None
        r, g, b = colorsys.hls_to_rgb((hue_deg % 360.0) / 360.0, _clamp_float(l), _clamp_float(s))
        return (_clamp_int(r * 255.0), _clamp_int(g * 255.0), _clamp_int(b * 255.0), _clamp_float(a))


def _parse_px(token: str) -> int | None:
    """Parse a CSS length token (px, pt, or 0) into an integer pixel value."""
    tok = token.strip().lower()
    if tok == "0":
        return 0
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(px|pt)?", tok)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "pt":
        return round(val * 96.0 / 72.0)
    return round(val)


def _expand_box_values(val: str) -> tuple[int, int, int, int] | None:
    """Expand CSS 1-to-4 value shorthand (padding/margin) into (top, right, bottom, left)."""
    tokens = _split_ws_top_level(val)
    if not (1 <= len(tokens) <= 4):
        return None
    nums: list[int] = []
    for tok in tokens:
        px = _parse_px(tok)
        if px is None:
            return None
        nums.append(px)
    if len(nums) == 1:
        return (nums[0], nums[0], nums[0], nums[0])
    if len(nums) == 2:
        return (nums[0], nums[1], nums[0], nums[1])
    if len(nums) == 3:
        return (nums[0], nums[1], nums[2], nums[1])
    return (nums[0], nums[1], nums[2], nums[3])


def _extract_gradient_fallback(
    val: str, resolver: _ColorResolver
) -> tuple[str, str | None]:
    """Identify gradient function name and extract the first resolvable color stop."""
    m = re.search(r"(repeating-(?:linear|radial)-gradient|(?:linear|radial)-gradient)\s*\((.*)\)", val, re.IGNORECASE | re.DOTALL)
    if not m:
        return "gradient", None
    feat = m.group(1).lower()
    inner = m.group(2)
    args = _split_top_level(inner, ",")
    for arg in args:
        arg_clean = arg.strip()
        if not arg_clean:
            continue
        # Strip trailing stop position like "0%" or "50px"
        sub_tokens = _split_ws_top_level(arg_clean)
        for cand in (arg_clean, sub_tokens[0] if sub_tokens else ""):
            if not cand:
                continue
            resolved = resolver.resolve_to_qml(cand)
            if resolved is not None:
                return feat, resolved
    return feat, None


def _consume_balanced_braces(text: str, open_idx: int, start_line: int) -> tuple[str, int, int]:
    """Consume from '{' at open_idx to matching '}', returning (inner, next_idx, next_line)."""
    n = len(text)
    i = open_idx + 1
    depth = 1
    line = start_line
    quote: str | None = None
    escaped = False

    while i < n and depth > 0:
        ch = text[i]
        if ch == "\n":
            line += 1
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1, line
        i += 1

    return text[open_idx + 1 :], n, line


def _parse_declarations(block: str, start_line: int) -> list[tuple[str, str, int]]:
    """Parse 'prop: val;' declarations inside a rule block with accurate 1-based line numbers."""
    decls: list[tuple[str, str, int]] = []
    n = len(block)
    i = 0
    line = start_line

    while i < n:
        while i < n and (block[i].isspace() or block[i] == ";"):
            if block[i] == "\n":
                line += 1
            i += 1
        if i >= n:
            break

        decl_line = line
        buf: list[str] = []
        paren_depth = 0
        quote: str | None = None
        escaped = False

        while i < n:
            ch = block[i]
            if ch == "\n":
                line += 1
            if quote is not None:
                buf.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                buf.append(ch)
            elif ch == "(":
                paren_depth += 1
                buf.append(ch)
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
                buf.append(ch)
            elif ch == ";" and paren_depth == 0:
                i += 1
                break
            else:
                buf.append(ch)
            i += 1

        raw_decl = "".join(buf).strip()
        if ":" in raw_decl:
            prop, _, val = raw_decl.partition(":")
            prop_clean = prop.strip().lower()
            val_clean = val.strip()
            if prop_clean and val_clean:
                decls.append((prop_clean, val_clean, decl_line))

    return decls


def _strip_quotes_and_brackets(selector: str) -> str:
    """Replace quoted/bracketed contents so pseudo/combinator scans ignore literals."""
    s = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', selector)
    s = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", s)
    return re.sub(r"\[[^\]]*\]", "[]", s)


def _detect_unsupported_selector(
    selector: str, line: int, raw_block: str
) -> tuple[list[UnsupportedCssItem], bool]:
    """Detect unsupported pseudo-selectors and '>' combinators in a CSS selector.

    Returns (items, has_pseudo_class).
    """
    items: list[UnsupportedCssItem] = []
    sanitized = _strip_quotes_and_brackets(selector)
    has_pseudo = False

    if ">" in sanitized:
        items.append(
            UnsupportedCssItem(
                selector=selector,
                feature=">",
                raw=raw_block,
                line=line,
                category="pseudo-selector",
                hint="Nest QML styling directly on child components instead of CSS '>' combinators.",
            )
        )

    matched_spans: list[tuple[int, int]] = []
    for pattern, feat, hint in _PSEUDO_PATTERNS:
        for m in pattern.finditer(sanitized):
            has_pseudo = True
            matched_spans.append(m.span())
            items.append(
                UnsupportedCssItem(
                    selector=selector,
                    feature=feat,
                    raw=raw_block,
                    line=line,
                    category="pseudo-selector",
                    hint=hint,
                )
            )

    # Catch any other :pseudo-class or ::pseudo-element not explicitly listed.
    for m in re.finditer(r"::?[a-zA-Z_-]+(?:\([^)]*\))?", sanitized):
        start, end = m.span()
        if any(s <= start and end <= e for s, e in matched_spans):
            continue
        has_pseudo = True
        feat = m.group(0)
        items.append(
            UnsupportedCssItem(
                selector=selector,
                feature=feat,
                raw=raw_block,
                line=line,
                category="pseudo-selector",
                hint=f"Translate CSS '{feat}' state to explicit QML property bindings.",
            )
        )

    return items, has_pseudo


def _get_or_create_style(mapping: dict[str, StyleProps], key: str) -> StyleProps:
    if key not in mapping:
        mapping[key] = StyleProps()
    return mapping[key]


def _normalize_css_module_id(id_name: str) -> str:
    """Map CSS #id (like custom-foo) to IR module key (custom/foo)."""
    if id_name.startswith("custom-"):
        return f"custom/{id_name[7:]}"
    return id_name


def _resolve_selector_targets(
    selector: str, tokens: ThemeTokens
) -> list[StyleProps]:
    """Map a non-pseudo CSS selector to target StyleProps objects inside ThemeTokens."""
    # Collapse child combinator '>' into space for structural matching after logging it.
    norm = re.sub(r"\s*>\s*", " ", selector.strip())
    norm = re.sub(r"\s+", " ", norm)

    if norm == "*":
        return [tokens.global_style]

    if norm in ("window#waybar", "#waybar", "window#waybar.solo"):
        return [tokens.bar_style]

    # Match workspaces button + optional states anywhere at the tail of selector.
    ws_btn_match = re.fullmatch(
        r"(?:(?:window)?#waybar\s+)?#workspaces\s+button((?:\.[a-zA-Z0-9_-]+)*)",
        norm,
    )
    if ws_btn_match:
        classes_raw = ws_btn_match.group(1)
        if not classes_raw:
            return [_get_or_create_style(tokens.module_styles, "workspaces_button")]
        ws_states = tokens.state_styles.setdefault("workspaces", {})
        classes = [c for c in classes_raw.split(".") if c]
        return [_get_or_create_style(ws_states, cls) for cls in classes]

    # Split compound parts and examine the rightmost element.
    parts = norm.split(" ")
    tail = parts[-1]

    if tail == ".modules-left":
        return [_get_or_create_style(tokens.section_styles, "left")]
    if tail == ".modules-center":
        return [_get_or_create_style(tokens.section_styles, "center")]
    if tail == ".modules-right":
        return [_get_or_create_style(tokens.section_styles, "right")]

    id_match = re.fullmatch(r"(?:[a-zA-Z0-9_-]+)?#([a-zA-Z0-9_-]+)((?:\.[a-zA-Z0-9_-]+)*)", tail)
    if id_match:
        raw_id = id_match.group(1)
        classes_raw = id_match.group(2)
        if raw_id == "waybar" and not classes_raw:
            return [tokens.bar_style]
        if raw_id == "waybar" and classes_raw:
            return []

        mod_key = _normalize_css_module_id(raw_id)
        if not classes_raw:
            return [_get_or_create_style(tokens.module_styles, mod_key)]
        mod_states = tokens.state_styles.setdefault(mod_key, {})
        classes = [c for c in classes_raw.split(".") if c]
        return [_get_or_create_style(mod_states, cls) for cls in classes]

    return []


def _apply_property(
    selector: str,
    prop: str,
    val: str,
    line: int,
    targets: list[StyleProps],
    resolver: _ColorResolver,
    unsupported: list[UnsupportedCssItem],
    record_unsupported: bool,
) -> None:
    """Apply a CSS declaration to target StyleProps and record unsupported CSS items."""
    raw_decl = f"{prop}: {val};"
    clean_val = re.sub(r"\s*!important\s*$", "", val, flags=re.IGNORECASE).strip()
    lower_val = clean_val.lower()

    if prop in _ANIMATION_PROPS:
        if record_unsupported:
            unsupported.append(
                UnsupportedCssItem(
                    selector=selector,
                    feature=prop,
                    raw=raw_decl,
                    line=line,
                    category="animation",
                    hint="Use QML Behavior on <property> { NumberAnimation / ColorAnimation }.",
                )
            )
        return

    if prop in _EFFECT_HINTS:
        if record_unsupported:
            unsupported.append(
                UnsupportedCssItem(
                    selector=selector,
                    feature=prop,
                    raw=raw_decl,
                    line=line,
                    category="effect",
                    hint=_EFFECT_HINTS[prop],
                )
            )
        return

    if prop in ("background-color", "background"):
        if "gradient(" in lower_val:
            feat, fallback = _extract_gradient_fallback(clean_val, resolver)
            if record_unsupported:
                unsupported.append(
                    UnsupportedCssItem(
                        selector=selector,
                        feature=feat,
                        raw=raw_decl,
                        line=line,
                        category="effect",
                        hint="Use QML Gradient { GradientStop { ... } } on Rectangle; first stop kept as fallback.",
                    )
                )
            if fallback is not None:
                for t in targets:
                    t.background = fallback
            return

        resolved = resolver.resolve_to_qml(clean_val)
        if resolved is None and prop == "background":
            # Try first whitespace-separated token in CSS background shorthand.
            ws_tokens = _split_ws_top_level(clean_val)
            if ws_tokens:
                resolved = resolver.resolve_to_qml(ws_tokens[0])
        if resolved is not None:
            for t in targets:
                t.background = resolved
        elif record_unsupported and clean_val.startswith("@"):
            unsupported.append(
                UnsupportedCssItem(
                    selector=selector,
                    feature=prop,
                    raw=raw_decl,
                    line=line,
                    category="property",
                    hint=f"Unresolved color reference in '{clean_val}'.",
                )
            )
        return

    if prop == "color":
        resolved = resolver.resolve_to_qml(clean_val)
        if resolved is not None:
            for t in targets:
                t.color = resolved
        elif record_unsupported and clean_val.startswith("@"):
            unsupported.append(
                UnsupportedCssItem(
                    selector=selector,
                    feature=prop,
                    raw=raw_decl,
                    line=line,
                    category="property",
                    hint=f"Unresolved color reference in '{clean_val}'.",
                )
            )
        return

    if prop == "border-radius":
        tokens_ws = _split_ws_top_level(clean_val)
        if tokens_ws:
            px = _parse_px(tokens_ws[0])
            if px is not None:
                for t in targets:
                    t.border_radius = px
        return

    if prop == "border":
        if lower_val in ("none", "0"):
            for t in targets:
                t.border_width = 0
            return
        b_width: int | None = None
        b_color: str | None = None
        for tok in _split_ws_top_level(clean_val):
            if tok.lower() in _BORDER_STYLES:
                continue
            if b_width is None:
                px = _parse_px(tok)
                if px is not None:
                    b_width = px
                    continue
            if b_color is None:
                col = resolver.resolve_to_qml(tok)
                if col is not None:
                    b_color = col
        for t in targets:
            if b_width is not None:
                t.border_width = b_width
            if b_color is not None:
                t.border_color = b_color
        return

    if prop in ("border-top", "border-right", "border-bottom", "border-left"):
        if record_unsupported:
            unsupported.append(
                UnsupportedCssItem(
                    selector=selector,
                    feature=prop,
                    raw=raw_decl,
                    line=line,
                    category="property",
                    hint="QML Rectangle border applies to all 4 sides; use a thin anchored child Rectangle for single-side borders.",
                )
            )
        return

    if prop == "border-width":
        tokens_ws = _split_ws_top_level(clean_val)
        if tokens_ws:
            px = _parse_px(tokens_ws[0])
            if px is not None:
                for t in targets:
                    t.border_width = px
        return

    if prop == "border-color":
        col = resolver.resolve_to_qml(clean_val)
        if col is not None:
            for t in targets:
                t.border_color = col
        return

    if prop == "font-family":
        families = _split_top_level(clean_val, ",")
        for fam in families:
            stripped = fam.strip().strip('"').strip("'").strip()
            if stripped:
                for t in targets:
                    t.font_family = stripped
                break
        return

    if prop == "font-size":
        px = _parse_px(clean_val)
        if px is not None:
            for t in targets:
                t.font_size = px
        return

    if prop == "font-weight":
        for t in targets:
            t.font_weight = clean_val
        return

    if prop == "padding":
        box = _expand_box_values(clean_val)
        if box is not None:
            top, right, bottom, left = box
            for t in targets:
                t.padding_top = top
                t.padding_right = right
                t.padding_bottom = bottom
                t.padding_left = left
        return

    if prop in ("padding-top", "padding-right", "padding-bottom", "padding-left"):
        px = _parse_px(clean_val)
        if px is not None:
            attr = prop.replace("-", "_")
            for t in targets:
                setattr(t, attr, px)
        return

    if prop == "margin":
        box = _expand_box_values(clean_val)
        if box is not None:
            top, right, bottom, left = box
            for t in targets:
                t.margin_top = top
                t.margin_right = right
                t.margin_bottom = bottom
                t.margin_left = left
        return

    if prop in ("margin-top", "margin-right", "margin-bottom", "margin-left"):
        px = _parse_px(clean_val)
        if px is not None:
            attr = prop.replace("-", "_")
            for t in targets:
                setattr(t, attr, px)
        return

    if prop == "min-height":
        px = _parse_px(clean_val)
        if px is not None:
            for t in targets:
                t.min_height = px
        return

    if prop == "min-width":
        px = _parse_px(clean_val)
        if px is not None:
            for t in targets:
                t.min_width = px
        return

    if prop == "opacity":
        try:
            op = _clamp_float(float(clean_val))
        except ValueError:
            return
        for t in targets:
            t.opacity = op


def _merge_style_props(dst: StyleProps, src: StyleProps) -> None:
    """Merge non-None StyleProps fields from src into dst."""
    for field_name in _KNOWN_STYLE_FIELDS:
        val = getattr(src, field_name)
        if val is not None:
            setattr(dst, field_name, val)


def _merge_theme_tokens(dst: ThemeTokens, src: ThemeTokens) -> None:
    """Merge parsed ThemeTokens from an @imported stylesheet into dst."""
    dst.named_colors.update(src.named_colors)
    _merge_style_props(dst.global_style, src.global_style)
    _merge_style_props(dst.bar_style, src.bar_style)
    for sec, sp in src.section_styles.items():
        _merge_style_props(_get_or_create_style(dst.section_styles, sec), sp)
    for mod, sp in src.module_styles.items():
        _merge_style_props(_get_or_create_style(dst.module_styles, mod), sp)
    for mod, states in src.state_styles.items():
        dst_states = dst.state_styles.setdefault(mod, {})
        for st, sp in states.items():
            _merge_style_props(_get_or_create_style(dst_states, st), sp)
    dst.unsupported_css.extend(src.unsupported_css)


def _extract_import_target(stmt: str) -> str:
    """Extract path/url string from an @import statement."""
    body = re.sub(r"^@import\s+", "", stmt.strip(), flags=re.IGNORECASE).rstrip(";").strip()
    m = re.match(r"url\(\s*(.*?)\s*\)", body, flags=re.IGNORECASE)
    if m:
        body = m.group(1).strip()
    return body.strip('"').strip("'").strip()


def _parse_css_internal(
    text: str,
    source_name: str,
    base_dir: Path | None,
    visited_paths: frozenset[Path],
    resolver: _ColorResolver,
) -> ThemeTokens:
    tokens = ThemeTokens()
    stripped = _strip_css_comments(text)
    n = len(stripped)
    i = 0
    line = 1

    while i < n:
        while i < n and stripped[i].isspace():
            if stripped[i] == "\n":
                line += 1
            i += 1
        if i >= n:
            break

        start_line = line

        if stripped[i] == "@":
            # Read at-rule header up to ';' or '{'.
            header_buf: list[str] = []
            paren_depth = 0
            quote: str | None = None
            escaped = False
            term = ""
            while i < n:
                ch = stripped[i]
                if ch == "\n":
                    line += 1
                if quote is not None:
                    header_buf.append(ch)
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == quote:
                        quote = None
                    i += 1
                    continue
                if ch in ('"', "'"):
                    quote = ch
                    header_buf.append(ch)
                    i += 1
                    continue
                if ch == "(":
                    paren_depth += 1
                    header_buf.append(ch)
                    i += 1
                    continue
                if ch == ")":
                    paren_depth = max(0, paren_depth - 1)
                    header_buf.append(ch)
                    i += 1
                    continue
                if paren_depth == 0 and ch in (";", "{"):
                    term = ch
                    i += 1
                    break
                header_buf.append(ch)
                i += 1

            header = "".join(header_buf).strip()
            header_lower = header.lower()

            if term == "{":
                inner_block, i, line = _consume_balanced_braces(stripped, i - 1, line)
                kf_match = re.match(r"^@(?:-webkit-|-moz-)?keyframes\s+(.+)$", header, re.IGNORECASE)
                if kf_match:
                    kf_name = kf_match.group(1).strip()
                    tokens.unsupported_css.append(
                        UnsupportedCssItem(
                            selector=f"@keyframes {kf_name}",
                            feature="@keyframes",
                            raw=f"{header} {{ {inner_block.strip()} }}",
                            line=start_line,
                            category="animation",
                            hint="Use QML SequentialAnimation / NumberAnimation instead of CSS @keyframes.",
                        )
                    )
                else:
                    at_kw = header.split()[0] if header else "@"
                    tokens.unsupported_css.append(
                        UnsupportedCssItem(
                            selector=header,
                            feature=at_kw,
                            raw=f"{header} {{ ... }}",
                            line=start_line,
                            category="at-rule",
                            hint=f"At-rule '{at_kw}' is not translated directly to QML.",
                        )
                    )
                continue

            # Semicolon-terminated at-rules
            if header_lower.startswith("@define-color"):
                dc_match = re.match(
                    r"^@define-color\s+([a-zA-Z0-9_-]+)\s+(.+)$",
                    header,
                    re.IGNORECASE | re.DOTALL,
                )
                if dc_match:
                    c_name = dc_match.group(1).strip()
                    c_expr = dc_match.group(2).strip()
                    resolver.add_define(c_name, c_expr, line=start_line)
                continue

            if header_lower.startswith("@import"):
                target = _extract_import_target(header)
                resolved_import = False
                if base_dir is not None and target and not re.match(r"^[a-z]+://", target, re.IGNORECASE):
                    inc_path = Path(target).expanduser()
                    if not inc_path.is_absolute():
                        inc_path = base_dir / inc_path
                    inc_resolved = inc_path.resolve()
                    if inc_resolved not in visited_paths and inc_resolved.is_file():
                        try:
                            inc_text = inc_resolved.read_text(encoding="utf-8")
                            inc_tokens = _parse_css_internal(
                                inc_text,
                                str(inc_path),
                                inc_resolved.parent,
                                visited_paths | {inc_resolved},
                                resolver,
                            )
                            _merge_theme_tokens(tokens, inc_tokens)
                            resolved_import = True
                        except OSError:
                            resolved_import = False

                if not resolved_import:
                    tokens.unsupported_css.append(
                        UnsupportedCssItem(
                            selector="@import",
                            feature="@import",
                            raw=f"{header};",
                            line=start_line,
                            category="at-rule",
                            hint=f"Imported stylesheet '{target}' could not be inlined; ensure referenced colors are defined.",
                        )
                    )
                continue

            at_kw = header.split()[0] if header else "@"
            tokens.unsupported_css.append(
                UnsupportedCssItem(
                    selector=header,
                    feature=at_kw,
                    raw=f"{header};",
                    line=start_line,
                    category="at-rule",
                    hint=f"At-rule '{at_kw}' is not supported in QML.",
                )
            )
            continue

        # Regular CSS rule: read selector(s) up to '{'.
        sel_buf: list[str] = []
        quote = None
        escaped = False
        found_open = False
        while i < n:
            ch = stripped[i]
            if ch == "\n":
                line += 1
            if quote is not None:
                sel_buf.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                sel_buf.append(ch)
                i += 1
                continue
            if ch == "{":
                found_open = True
                break
            sel_buf.append(ch)
            i += 1

        if not found_open:
            break

        sel_text = "".join(sel_buf).strip()
        block_start_line = line
        inner_block, i, line = _consume_balanced_braces(stripped, i, line)
        if not sel_text:
            continue

        decls = _parse_declarations(inner_block, block_start_line)
        raw_rule = f"{sel_text} {{ {inner_block.strip()} }}"
        selectors = [s.strip() for s in _split_top_level(sel_text, ",") if s.strip()]

        all_targets: list[StyleProps] = []
        first_selector = selectors[0] if selectors else sel_text

        for sel in selectors:
            sel_items, has_pseudo = _detect_unsupported_selector(sel, start_line, raw_rule)
            tokens.unsupported_css.extend(sel_items)
            if not has_pseudo:
                all_targets.extend(_resolve_selector_targets(sel, tokens))

        for prop, val, decl_line in decls:
            _apply_property(
                selector=first_selector,
                prop=prop,
                val=val,
                line=decl_line,
                targets=all_targets,
                resolver=resolver,
                unsupported=tokens.unsupported_css,
                record_unsupported=True,
            )

    resolved_colors, unresolved_colors = resolver.resolve_named_all()
    tokens.named_colors.update(resolved_colors)
    for c_name, c_expr, c_line in unresolved_colors:
        tokens.unsupported_css.append(
            UnsupportedCssItem(
                selector=f"@define-color {c_name}",
                feature="@define-color",
                raw=f"@define-color {c_name} {c_expr};",
                line=c_line,
                category="property",
                hint=f"Could not resolve @define-color '{c_name}': {c_expr}",
            )
        )
    return tokens


def parse_waybar_css(text: str, source_name: str = "style.css") -> ThemeTokens:
    """Parse Waybar GTK CSS text into ThemeTokens."""
    if text.startswith("\ufeff"):
        text = text[1:]
    resolver = _ColorResolver()
    return _parse_css_internal(
        text=text,
        source_name=source_name,
        base_dir=None,
        visited_paths=frozenset(),
        resolver=resolver,
    )


def load_waybar_css(path: Path) -> ThemeTokens:
    """Load and parse a Waybar style.css file, resolving local @import files."""
    resolved_path = path.expanduser().resolve()
    text = resolved_path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    resolver = _ColorResolver()
    return _parse_css_internal(
        text=text,
        source_name=str(path),
        base_dir=resolved_path.parent,
        visited_paths=frozenset({resolved_path}),
        resolver=resolver,
    )
