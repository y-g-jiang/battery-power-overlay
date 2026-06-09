# Battery Power Overlay

`battery_power_overlay.py` / `dist\battery_power_overlay.exe` shows the current
whole-machine battery charge or discharge power in the top-left corner.

## How it works

- Polls NirSoft BatteryInfoView through its `/scomma` CSV export option.
- Uses a tiny Tk window instead of a browser or always-rendering UI stack.
- Applies Win32 extended window styles for topmost, transparent background,
  no-activate, tool-window, and click-through behavior.
- Samples once per second and redraws a tiny wattage sparkline only when a new
  sample arrives.
- Shows the absolute wattage value on a small lightly blended white-on-dark
  mask, and hides that wattage mask when the pointer is nearby.
- Shows the BatteryInfoView current capacity percentage at the overlay's
  top-right corner.
- Shows `2026 姜尧耕 y-g-jiang.github.io` next to the overlay when the mouse is
  nearby. The overlay remains fully click-through.
- Registers the packaged exe for current-user startup on first normal launch.

## First run

Run:

```powershell
.\dist\battery_power_overlay.exe
```

If BatteryInfoView is not found automatically, a dialog asks you to choose
`BatteryInfoView.exe`. The selected path is saved in:

```text
battery_power_overlay.json
```

The app first looks for this JSON beside the executable, then in the current
working directory, then under `%APPDATA%\BatteryPowerOverlay`.

The installer removes the previous `%LOCALAPPDATA%\BatteryPowerOverlay`
installation before copying the new version and registering startup again.

## Configuration

Example:

```json
{
  "batteryinfo_path": "C:\\Tools\\BatteryInfoView\\BatteryInfoView.exe",
  "sample_interval_seconds": 1.0,
  "subprocess_timeout_seconds": 6.0,
  "opacity": 1.0,
  "position": { "x": 6, "y": 6 },
  "font": { "family": "Segoe UI Semibold", "size": 12 },
  "background": "#010203",
  "transparent_background": true,
  "foreground": "#f4f4f4",
  "discharge_foreground": "#ff5a5f",
  "error_foreground": "#ffd37a",
  "padding": { "x": 8, "y": 3 },
  "watt_mask": {
    "background": "#050505",
    "foreground": "#ffffff",
    "background_opacity": 0.62,
    "hide_proximity_pixels": 96
  },
  "graph": {
    "enabled": true,
    "width": 116,
    "height": 30,
    "history_seconds": 60,
    "line": "#78d9ff",
    "discharge_line": "#ff5a5f",
    "baseline": ""
  },
  "percent": {
    "enabled": true,
    "font": { "family": "Segoe UI", "size": 9 },
    "foreground": "#d8dde0"
  },
  "credit": {
    "enabled": true,
    "text": "2026 姜尧耕 y-g-jiang.github.io",
    "proximity_pixels": 42,
    "poll_ms": 250,
    "font": { "family": "Segoe UI", "size": 8 },
    "foreground": "#b8c2c7"
  },
  "adaptive_contrast": {
    "enabled": true,
    "poll_ms": 120,
    "sample_columns": 7,
    "sample_rows": 5
  },
  "register_startup_on_first_run": true,
  "startup_registered": false,
  "startup_command": "",
  "show_state": false
}
```

The default is one BatteryInfoView sample per second, with a 60-second
sparkline. Adaptive contrast only samples a small grid of screen pixels behind
the overlay; it does not call BatteryInfoView more often.

## Useful commands

Run from source:

```powershell
python .\battery_power_overlay.py
```

Set BatteryInfoView path explicitly:

```powershell
.\dist\battery_power_overlay.exe --batteryinfo "C:\Tools\BatteryInfoView\BatteryInfoView.exe"
```

Read once for testing:

```powershell
python .\battery_power_overlay.py --once --batteryinfo "C:\Tools\BatteryInfoView\BatteryInfoView.exe"
```

Temporarily adjust interval or opacity:

```powershell
.\dist\battery_power_overlay.exe --interval 1 --opacity 0.65
```

Debug without click-through:

```powershell
python .\battery_power_overlay.py --allow-clicks
```

Run without writing the startup entry:

```powershell
.\dist\battery_power_overlay.exe --no-startup
```

## Build

Use the module form so the current Python environment is used:

```powershell
python -m PyInstaller --clean --noconfirm .\battery_power_overlay.spec
```

## Folder Release

`battery_power_overlay_github` is a ready-to-publish folder:

```text
battery_power_overlay_github\
  battery_power_overlay.exe
  battery_power_overlay.py
  battery_power_overlay.spec
  battery_power_overlay.json
  README_battery_power_overlay.md
  BatteryInfoView\
    BatteryInfoView.exe
    BatteryInfoView_lng.ini
```

The bundled config uses the relative path
`BatteryInfoView\BatteryInfoView.exe`, so the folder can be moved as one unit.
BatteryInfoView is NirSoft freeware, not open-source code from this project.
