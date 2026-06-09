# Battery Power Overlay

Tiny Windows overlay that reads real-time charge/discharge power from
BatteryInfoView and shows it in the top-left corner with a small sparkline.

Highlights:

- 1 second polling through BatteryInfoView `/scomma`
- semi-transparent always-on-top overlay
- click-through top-level and child windows
- red text/line while discharging
- battery percentage in the overlay's top-right corner
- dodges downward by one overlay height when the pointer reaches it
- hover-near credit text: `2026 姜尧耕 y-g-jiang.github.io`
- per-user startup registration

## Install

Download `BatteryPowerOverlaySetup.exe` from the latest GitHub Release and run
it. The installer copies the app to:

```text
%LOCALAPPDATA%\BatteryPowerOverlay
```

It also creates a current-user startup entry and launches the overlay.

## Source Run

```powershell
python .\battery_power_overlay.py
```

## Build App Exe

```powershell
python -m PyInstaller --clean --noconfirm .\battery_power_overlay.spec
```

## Build Installer

The installer is built with PyInstaller and bundles the overlay executable,
configuration, BatteryInfoView, and the uninstall script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\build_installer.ps1
```

The installer is written to:

```text
release\BatteryPowerOverlaySetup.exe
```

## Third-Party Binary

The installer bundles NirSoft BatteryInfoView freeware. BatteryInfoView is not
open source and is not covered by this repository's MIT License. See
`NOTICE.md`.
