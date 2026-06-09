#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tkinter import messagebox
import tkinter as tk

try:
    import winreg
except ImportError:
    winreg = None


APP_NAME = "BatteryPowerOverlay"
DISPLAY_NAME = "Battery Power Overlay"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


def install_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        raise RuntimeError("LOCALAPPDATA is not set")
    return Path(local_appdata) / APP_NAME


def ensure_install_dir_is_safe(path: Path) -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        raise RuntimeError("LOCALAPPDATA is not set")
    base = Path(local_appdata).resolve()
    target = path.resolve()
    if target == base or base not in target.parents or target.name != APP_NAME:
        raise RuntimeError(f"Refusing to remove unexpected install path: {target}")
    return target


def copy_payload(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "BatteryInfoView").mkdir(parents=True, exist_ok=True)

    files = [
        ("battery_power_overlay.exe", "battery_power_overlay.exe"),
        ("battery_power_overlay.json", "battery_power_overlay.json"),
        ("README.md", "README.md"),
        ("NOTICE.md", "NOTICE.md"),
        ("installer/uninstall.cmd", "uninstall.cmd"),
        ("BatteryInfoView/BatteryInfoView.exe", "BatteryInfoView/BatteryInfoView.exe"),
        ("BatteryInfoView/BatteryInfoView_lng.ini", "BatteryInfoView/BatteryInfoView_lng.ini"),
    ]
    for source_rel, target_rel in files:
        source = src / source_rel
        if not source.is_file():
            raise FileNotFoundError(source)
        target = dst / target_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def register_startup(exe: Path) -> None:
    if winreg is None:
        return
    command = f'"{exe}"'
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)


def unregister_startup() -> None:
    if winreg is None:
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


def stop_existing() -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run(
        ["taskkill", "/IM", "battery_power_overlay.exe", "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        check=False,
        creationflags=creationflags,
    )


def wait_for_file_release(path: Path, timeout_seconds: float = 8.0) -> None:
    if not path.exists():
        return

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with path.open("ab"):
                return
        except OSError:
            time.sleep(0.2)


def remove_previous_install(target: Path) -> None:
    safe_target = ensure_install_dir_is_safe(target)
    if not safe_target.exists():
        return

    wait_for_file_release(safe_target / "battery_power_overlay.exe")
    last_error: Exception | None = None
    for _attempt in range(24):
        try:
            shutil.rmtree(safe_target)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Could not remove previous installation:\n{safe_target}\n\n{last_error}")


def uninstall_previous(target: Path) -> None:
    stop_existing()
    unregister_startup()
    remove_previous_install(target)


def launch_overlay(exe: Path) -> None:
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    try:
        target = install_dir()
        uninstall_previous(target)
        copy_payload(resource_root(), target)
        exe = target / "battery_power_overlay.exe"
        register_startup(exe)
        launch_overlay(exe)
        return 0
    except Exception as exc:
        messagebox.showerror(DISPLAY_NAME, f"Installation failed:\n{exc}")
        return 1
    finally:
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
