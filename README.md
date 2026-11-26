# waybar2qs

[![PyPI version](https://img.shields.io/pypi/v/waybar2qs)](https://pypi.org/project/waybar2qs/)
[![CI](https://github.com/Prateek-squadron/waybar2qs/actions/workflows/ci.yml/badge.svg)](https://github.com/Prateek-squadron/waybar2qs/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Transpile Waybar configurations (`config.jsonc` + `style.css`) into modular [Quickshell](https://quickshell.outfoxxed.me/) (`shell.qml`) projects, accompanied by an honest migration audit report.

## Why `waybar2qs`?

Wayland desktop ecosystems such as **Omarchy**, **Noctalia**, and **DankMaterialShell** are increasingly moving from Waybar + GTK CSS toward **Quickshell** (Qt 6 / QML) for native compositor IPC, smooth animations, and unified shell surfaces. Rebuilding an existing Waybar setup in QML from scratch means manually porting JSONC module layouts, `@define-color` palettes, interval/event scripts, and compositor bindings.

`waybar2qs` bridges that gap:

- Parses Waybar `config.jsonc` (including `//` / `/* */` comments, trailing commas, `include` directives, and multi-bar arrays).
- Extracts mappable GTK CSS design tokens (`@define-color`, colors, radii, fonts, padding, margins, state styles) into a centralized `Theme.qml` singleton.
- Generates modular QML components (`qmldir`, `shell.qml`, `Theme.qml`, and `components/*.qml`) tailored for **Hyprland** or **Niri**.
- Produces an explicit migration report (`--report`) calling out everything transpiled natively, everything backed by `Process`, and every unsupported CSS rule (`:hover`, `@keyframes`, `box-shadow`, gradients) with line numbers and QML hints.

Zero third-party Python runtime dependencies — uses only the Python >= 3.10 standard library.

## Installation

```bash
# Install from PyPI
pip install waybar2qs

# Or install as an isolated CLI tool with uv
uv tool install waybar2qs

# Or editable install from source
git clone https://github.com/Prateek-squadron/waybar2qs.git
cd waybar2qs
pip install -e .
```

## CLI Usage

```text
waybar2qs [CONFIG] [options]
```

If `CONFIG` is omitted, `waybar2qs` auto-discovers `~/.config/waybar/config.jsonc` or `~/.config/waybar/config`. If `-s/--style` is omitted, it auto-discovers a sibling `style.css` next to `CONFIG`.

### Options

| Option | Description |
| --- | --- |
| `CONFIG` | Path to Waybar `config.jsonc` / `config` (optional if `~/.config/waybar/` exists) |
| `-s, --style PATH` | Path to Waybar `style.css` |
| `-o, --output DIR` | Output directory for the generated Quickshell project (default: `./quickshell-bar`) |
| `--compositor {auto,hyprland,niri}` | Target compositor backend (default: `auto`, inferred from modules) |
| `--report` | Print the full Markdown migration report to stdout |
| `--report-file PATH` | Write the migration report to a file (e.g. `MIGRATION_REPORT.md`) |
| `--report-json` | Print the machine-readable JSON migration report to stdout |
| `--lint` | Run Qt 6 `qmllint` on generated `.qml` files and include results in the report |
| `--dry-run` | Parse, transpile, and report without writing files to disk |
| `--version` | Show the `waybar2qs` version and exit |

### Examples

```bash
# Convert your active ~/.config/waybar setup into ./quickshell-bar
waybar2qs --report

# Convert a specific config + style and verify with Qt 6 qmllint
waybar2qs fixtures/omarchy_hyprland/config.jsonc \
  -s fixtures/omarchy_hyprland/style.css \
  -o ./out-omarchy \
  --lint \
  --report-file ./out-omarchy/MIGRATION_REPORT.md

# Preview a Niri conversion without writing files
waybar2qs fixtures/niri_scrollable/config.jsonc --dry-run --report-json
```

## Supported Modules

| Waybar Module | Quickshell Backend | Support Level |
| --- | --- | --- |
| `hyprland/workspaces` | `Quickshell.Hyprland` (`Hyprland.workspaces`) | Native |
| `clock` | `Quickshell.SystemClock` / `Qt.formatDateTime` | Native |
| `pulseaudio` / `wireplumber` | `Quickshell.Services.Pipewire` (`PwObjectTracker`) | Native |
| `battery` | `Quickshell.Services.UPower` (`UPower.displayDevice`) | Native |
| `network` | `Quickshell.Networking` (`WifiDevice` / `WiredDevice`) | Native / Partial |
| `tray` | `Quickshell.Services.SystemTray` + `IconImage` + `QsMenuAnchor` | Native |
| `niri/workspaces` | `Quickshell.Io.Process` (`niri msg --json workspaces` + `event-stream`) | Process-backed |
| `custom/*` | `Quickshell.Io.Process` (`exec`, `interval`, `return-type: json`, `on-click*`, `on-scroll-*`) | Process-backed |
| Other modules | Placeholder QML component (`StubModuleWidget.qml`) | Stub |

## How `--report` Works

GTK CSS and Waybar JSONC do not map 1:1 to Qt Quick / QML. Rather than silently dropping rules, `waybar2qs` records an audit trail in `ConversionReport`:

1. **Summary**: Source paths, compositor target, bar count, and module counts broken down by `native`, `process-backed`, `partial`, and `stub`.
2. **Mapped CSS Design Tokens**: Extracted `@define-color` palette entries and resolved bar/module tokens written to `Theme.qml`.
3. **Module-by-Module Conversion**: Exact mapping from each Waybar module name to its generated `.qml` file, backend, and behavioral caveats (such as `format-alt` toggles or `states` thresholds).
4. **Unsupported CSS Features**: Grouped by category (`Animations & Transitions`, `Pseudo-Selectors`, `Visual Effects`, `CSS At-Rules`, `Unsupported Properties`) with selector, line number, raw CSS snippet, and a concrete QML equivalent hint (for example, `MouseArea { hoverEnabled: true }` + `Behavior on color` for `:hover` transitions, or `SequentialAnimation` for `@keyframes`).
5. **Config Warnings & `qmllint` Verification**: Non-fatal JSONC/module warnings and Qt 6 `qmllint` pass/fail output when `--lint` is enabled.

## Running the Generated Bar

Launch the generated project directly with Quickshell:

```bash
quickshell -p ./quickshell-bar
```

Generated project layout:

```text
quickshell-bar/
├── qmldir             # Registers Theme as a QML singleton
├── shell.qml          # ShellRoot + Variants + PanelWindow bar layouts
├── Theme.qml          # Extracted @define-color & style design tokens
└── components/        # Modular per-widget QML components
```
