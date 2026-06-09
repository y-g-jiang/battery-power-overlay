#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
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


def stop_existing() -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run(
        ["taskkill", "/IM", "battery_power_overlay.exe", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        check=False,
        creationflags=creationflags,
    )


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
        stop_existing()
        copy_payload(resource_root(), target)
        exe = target / "battery_power_overlay.exe"
        register_startup(exe)
        launch_overlay(exe)
        messagebox.showinfo(DISPLAY_NAME, f"Installed to:\n{target}")
        return 0
    except Exception as exc:
        messagebox.showerror(DISPLAY_NAME, f"Installation failed:\n{exc}")
        return 1
    finally:
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
