#!/usr/bin/env python3
"""
Tiny always-on-top power overlay backed by NirSoft BatteryInfoView.

BatteryInfoView is polled through its documented /scomma export command.  The
overlay itself is a borderless Tk window with Win32 extended styles for
click-through, no-activate, layered opacity, and topmost behavior.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

try:
    import winreg
except ImportError:
    winreg = None


APP_NAME = "BatteryPowerOverlay"
CONFIG_NAME = "battery_power_overlay.json"
DEFAULT_CONFIG = {
    "batteryinfo_path": "",
    "sample_interval_seconds": 1.0,
    "subprocess_timeout_seconds": 6.0,
    "opacity": 0.72,
    "position": {"x": 6, "y": 6},
    "font": {"family": "Segoe UI Semibold", "size": 12},
    "background": "#050505",
    "foreground": "#f4f4f4",
    "discharge_foreground": "#ff5a5f",
    "error_foreground": "#ffd37a",
    "padding": {"x": 8, "y": 3},
    "graph": {
        "enabled": True,
        "width": 116,
        "height": 30,
        "history_seconds": 60,
        "line": "#78d9ff",
        "discharge_line": "#ff5a5f",
        "baseline": "#353535",
    },
    "percent": {
        "enabled": True,
        "font": {"family": "Segoe UI", "size": 9},
        "foreground": "#d8dde0",
    },
    "credit": {
        "enabled": True,
        "text": "2026 \u59dc\u5c27\u8015 y-g-jiang.github.io",
        "proximity_pixels": 42,
        "poll_ms": 250,
        "font": {"family": "Segoe UI", "size": 8},
        "foreground": "#b8c2c7",
    },
    "dodge": {
        "enabled": True,
        "poll_ms": 80,
        "gap_pixels": 4,
        "return_margin_pixels": 42,
    },
    "register_startup_on_first_run": True,
    "startup_registered": False,
    "startup_command": "",
    "show_state": False,
}


RATE_KEYS = (
    "charge/discharge rate",
    "charge discharge rate",
    "charge or discharge rate",
    "charging/discharging rate",
    "charging discharging rate",
    "charge/discharge power",
    "charge discharge power",
    "charge or discharge power",
    "charging/discharging power",
    "charging discharging power",
    "discharge rate",
    "charge rate",
    "discharge power",
    "charge power",
    "battery power",
    "充电/放电速率",
    "充放电速率",
    "\u5145\u7535\u6216\u653e\u7535\u529f\u7387",
    "\u5145\u7535/\u653e\u7535\u529f\u7387",
    "\u5145\u653e\u7535\u529f\u7387",
    "充電/放電速率",
    "充放電速率",
    "\u5145\u96fb\u6216\u653e\u96fb\u529f\u7387",
    "\u5145\u96fb/\u653e\u96fb\u529f\u7387",
    "\u5145\u653e\u96fb\u529f\u7387",
    "放电速率",
    "放電速率",
    "\u653e\u7535\u529f\u7387",
    "\u653e\u96fb\u529f\u7387",
    "充电速率",
    "充電速率",
    "\u5145\u7535\u529f\u7387",
    "\u5145\u96fb\u529f\u7387",
)
STATE_KEYS = (
    "power state",
    "battery status",
    "电源状态",
    "電源狀態",
    "电池状态",
    "電池狀態",
)
PERCENT_KEYS = (
    "current capacity (in %)",
    "current capacity (%)",
    "current capacity percent",
    "battery percentage",
    "battery percent",
    "battery level",
    "remaining capacity (%)",
    "\u5f53\u524d\u5bb9\u91cf (%)",
    "\u7576\u524d\u5bb9\u91cf (%)",
    "\u5f53\u524d\u5bb9\u91cf(\u0025)",
    "\u7576\u524d\u5bb9\u91cf(\u0025)",
    "\u7535\u91cf\u767e\u5206\u6bd4",
    "\u96fb\u91cf\u767e\u5206\u6bd4",
)
PERCENT_EXCLUDE_KEYS = (
    "value",
    "health",
    "wear",
    "full",
    "design",
    "low",
    "\u503c",
    "\u5065\u5eb7",
    "\u635f\u8017",
    "\u5b8c\u5168",
    "\u8bbe\u8ba1",
    "\u8a2d\u8a08",
    "\u4f4e\u7535\u91cf",
    "\u4f4e\u96fb\u91cf",
)
PERCENT_MARKERS = ("%", "percent", "percentage", "\u767e\u5206\u6bd4")


@dataclass(frozen=True)
class PowerSample:
    watts: float | None
    percent: float | None = None
    state: str = ""
    error: str = ""


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ordered_unique(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def default_config_candidates() -> list[Path]:
    base = app_dir()
    cwd = Path.cwd()
    appdata = Path(os.environ.get("APPDATA", base)) / APP_NAME
    return ordered_unique(
        [
            base / CONFIG_NAME,
            cwd / CONFIG_NAME,
            appdata / CONFIG_NAME,
        ]
    )


def choose_config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    candidates = default_config_candidates()
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def merge_config(raw: dict[str, object]) -> dict[str, object]:
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = merged[key]
            assert isinstance(nested, dict)
            nested.update(value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return merge_config({})
    try:
        return merge_config(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        messagebox.showwarning(
            APP_NAME,
            f"配置文件读取失败，将使用默认配置。\n\n{path}\n\n{exc}",
        )
        return merge_config({})


def save_config(path: Path, config: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        fallback = Path(os.environ.get("APPDATA", str(app_dir()))) / APP_NAME / CONFIG_NAME
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        messagebox.showwarning(
            APP_NAME,
            f"无法写入配置：\n{path}\n\n已改写到：\n{fallback}\n\n{exc}",
        )


def as_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def as_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def is_valid_batteryinfo(path: str | Path | None) -> bool:
    if not path:
        return False
    candidate = Path(str(path)).expanduser()
    return candidate.is_file() and candidate.name.lower().endswith(".exe")


def resolve_configured_batteryinfo(path: object, config_path: Path) -> Path | None:
    if not path:
        return None
    raw = Path(str(path)).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend([config_path.parent / raw, app_dir() / raw])
    for candidate in ordered_unique(candidates):
        if is_valid_batteryinfo(candidate):
            return candidate.resolve()
    return None


def find_batteryinfo() -> Path | None:
    names = ("BatteryInfoView.exe", "BatteryInfoView_x64.exe")
    direct_dirs: list[Path] = [
        app_dir(),
        Path.cwd(),
        app_dir() / "tools",
        app_dir() / "BatteryInfoView",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NirSoft",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "NirSoft",
    ]

    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)

    for directory in ordered_unique(direct_dirs):
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        try:
            children = list(directory.glob("BatteryInfoView*/BatteryInfoView*.exe"))
        except OSError:
            children = []
        if children:
            return children[0]

    return None


def prompt_for_batteryinfo() -> Path | None:
    messagebox.showinfo(
        APP_NAME,
        "没有检测到 BatteryInfoView.exe。\n\n请在下一步选择 NirSoft BatteryInfoView 的程序路径。",
    )
    selected = filedialog.askopenfilename(
        title="选择 BatteryInfoView.exe",
        filetypes=[("BatteryInfoView.exe", "BatteryInfoView*.exe"), ("Executable", "*.exe")],
        initialdir=str(Path.home() / "Downloads"),
    )
    if not selected:
        messagebox.showwarning(APP_NAME, "没有选择 BatteryInfoView.exe，程序已退出。")
        return None
    return Path(selected)


def resolve_batteryinfo_path(
    config: dict[str, object],
    config_path: Path,
    cli_path: str | None,
) -> Path | None:
    if cli_path and is_valid_batteryinfo(cli_path):
        config["batteryinfo_path"] = str(Path(cli_path).expanduser().resolve())
        save_config(config_path, config)
        return Path(cli_path).expanduser().resolve()

    configured = resolve_configured_batteryinfo(config.get("batteryinfo_path"), config_path)
    if configured:
        return configured

    found = find_batteryinfo()
    if found:
        config["batteryinfo_path"] = str(found.resolve())
        save_config(config_path, config)
        return found.resolve()

    selected = prompt_for_batteryinfo()
    if selected and is_valid_batteryinfo(selected):
        config["batteryinfo_path"] = str(selected.resolve())
        save_config(config_path, config)
        return selected.resolve()
    return None


def read_text_auto(path: Path) -> str:
    data = path.read_bytes()
    encodings = ["utf-8-sig", "gb18030", "mbcs", "latin-1"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode(errors="replace")


def normalize_key(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("\u3000", " ")
    value = re.sub(r"[\s:_-]+", " ", value)
    return value


def key_matches(key: str, choices: tuple[str, ...]) -> bool:
    key_norm = normalize_key(key)
    return any(normalize_key(choice) in key_norm for choice in choices)


def key_matches_percent(key: str) -> bool:
    if key_matches(key, PERCENT_EXCLUDE_KEYS):
        return False
    return key_matches(key, PERCENT_KEYS)


def parse_number(value: str) -> float | None:
    normalized = (
        value.replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\xa0", " ")
    )
    match = re.search(r"[-+]?\d[\d\s,.]*", normalized)
    if not match:
        return None

    token = match.group(0).strip().replace(" ", "")
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        parts = token.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            token = token.replace(",", "")
        else:
            token = token.replace(",", ".")

    try:
        return float(token)
    except ValueError:
        return None


def contains_any(value: str, markers: tuple[str, ...]) -> bool:
    lower = value.lower()
    compact = lower.replace(" ", "")
    return any(marker in lower or marker in compact for marker in markers)


ENERGY_UNIT_MARKERS = (
    "mwh",
    "wh",
    "watt-hour",
    "watt hour",
    "watthour",
    "\u6beb\u74e6\u65f6",
    "\u6beb\u74e6\u6642",
    "\u74e6\u65f6",
    "\u74e6\u6642",
)
MILLIWATT_MARKERS = ("mw", "milliwatt", "\u6beb\u74e6")
KILOWATT_MARKERS = ("kw", "kilowatt", "\u5343\u74e6")
WATT_MARKERS = ("watt", "\u74e6")


def parse_power_watts(value: str, require_unit: bool = False) -> float | None:
    if contains_any(value, ENERGY_UNIT_MARKERS):
        return None

    number = parse_number(value)
    if number is None:
        return None

    if contains_any(value, MILLIWATT_MARKERS):
        return number / 1000.0
    if contains_any(value, KILOWATT_MARKERS):
        return number * 1000.0
    compact = value.lower().replace(" ", "")
    if contains_any(value, WATT_MARKERS) or re.search(r"(?<![a-z])w(?!h|[a-z])", compact):
        return number
    if require_unit:
        return None
    return number


def parse_percent(value: str, require_marker: bool = False) -> float | None:
    number = parse_number(value)
    if number is None:
        return None
    if require_marker and not contains_any(value, PERCENT_MARKERS):
        return None
    if not 0 <= number <= 100:
        return None
    return number


def row_value(row: list[str]) -> str:
    if len(row) < 2:
        return ""
    return next((cell for cell in row[1:] if cell.strip()), ",".join(row[1:]))


def parse_batteryinfo_csv(text: str) -> PowerSample:
    rows = list(csv.reader(text.splitlines()))
    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return PowerSample(None, error="CSV empty")

    state = ""
    watts: float | None = None
    percent: float | None = None

    for row in rows:
        if len(row) < 2:
            continue
        key, value = row[0], row_value(row)
        if key_matches(key, STATE_KEYS):
            state = value
        if key_matches(key, RATE_KEYS):
            watts = parse_power_watts(value)
        if percent is None and key_matches_percent(key):
            percent = parse_percent(value)

    if watts is None:
        for row in rows:
            if len(row) < 2:
                continue
            value = row_value(row)
            watts = parse_power_watts(value, require_unit=True)
            if watts is not None:
                break

    if (watts is None or percent is None) and len(rows) >= 2:
        header = rows[0]
        rate_index = next(
            (index for index, name in enumerate(header) if key_matches(name, RATE_KEYS)),
            None,
        )
        percent_index = next(
            (index for index, name in enumerate(header) if key_matches_percent(name)),
            None,
        )
        state_index = next(
            (index for index, name in enumerate(header) if key_matches(name, STATE_KEYS)),
            None,
        )
        for row in rows[1:]:
            if watts is None and rate_index is not None and rate_index < len(row):
                watts = parse_power_watts(row[rate_index])
            if percent is None and percent_index is not None and percent_index < len(row):
                percent = parse_percent(row[percent_index])
            if state_index is not None and state_index < len(row) and not state:
                state = row[state_index]
            if watts is not None and (percent is not None or percent_index is None):
                break

    if watts is None:
        return PowerSample(None, percent=percent, state=state, error="rate missing")
    return PowerSample(watts, percent=percent, state=state)


class BatteryInfoReader:
    def __init__(self, exe_path: Path, timeout_seconds: float) -> None:
        self.exe_path = exe_path
        self.timeout_seconds = timeout_seconds

    def read(self) -> PowerSample:
        with tempfile.NamedTemporaryFile(
            prefix="batteryinfo_",
            suffix=".csv",
            delete=False,
        ) as tmp:
            csv_path = Path(tmp.name)

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            completed = subprocess.run(
                [str(self.exe_path), "/scomma", str(csv_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
                check=False,
                creationflags=creationflags,
            )
            if completed.returncode != 0:
                return PowerSample(None, error=f"exit {completed.returncode}")
            return parse_batteryinfo_csv(read_text_auto(csv_path))
        except subprocess.TimeoutExpired:
            return PowerSample(None, error="timeout")
        except Exception as exc:
            return PowerSample(None, error=type(exc).__name__)
        finally:
            try:
                csv_path.unlink(missing_ok=True)
            except OSError:
                pass


def current_startup_command() -> str | None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    return f'"{Path(sys.executable).resolve()}"'


def ensure_startup_registered(config: dict[str, object], config_path: Path) -> None:
    if os.name != "nt" or winreg is None:
        return
    if not bool(config.get("register_startup_on_first_run", True)):
        return

    command = current_startup_command()
    if not command:
        return
    if config.get("startup_registered") is True and config.get("startup_command") == command:
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        config["startup_registered"] = True
        config["startup_command"] = command
        config.pop("startup_error", None)
    except OSError as exc:
        config["startup_registered"] = False
        config["startup_error"] = str(exc)[:240]
    save_config(config_path, config)


class Poller(threading.Thread):
    def __init__(
        self,
        reader: BatteryInfoReader,
        interval_seconds: float,
        output: queue.Queue[PowerSample],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="BatteryInfoPoller", daemon=True)
        self.reader = reader
        self.interval_seconds = interval_seconds
        self.output = output
        self.stop_event = stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            self.output.put(self.reader.read())
            elapsed = time.monotonic() - started
            wait_seconds = max(0.2, self.interval_seconds - elapsed)
            self.stop_event.wait(wait_seconds)


class Win32OverlayStyle:
    GWL_EXSTYLE = -20
    GWLP_WNDPROC = -4
    WM_NCHITTEST = 0x0084
    WM_MOUSEACTIVATE = 0x0021
    HTTRANSPARENT = -1
    MA_NOACTIVATE = 3
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_APPWINDOW = 0x00040000
    LWA_ALPHA = 0x00000002
    HWND_TOPMOST = -1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040
    RDW_INVALIDATE = 0x0001
    RDW_FRAME = 0x0400
    GA_ROOT = 2

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32
        long_ptr = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        self.long_ptr = long_ptr
        self.enum_child_proc = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        self.wnd_proc_type = ctypes.WINFUNCTYPE(
            long_ptr,
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        )
        self.subclassed: dict[int, tuple[int, object]] = {}
        self.get_window_long = getattr(self.user32, "GetWindowLongPtrW", self.user32.GetWindowLongW)
        self.set_window_long = getattr(self.user32, "SetWindowLongPtrW", self.user32.SetWindowLongW)
        self.get_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        self.get_window_long.restype = long_ptr
        self.set_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, long_ptr]
        self.set_window_long.restype = long_ptr
        self.user32.GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
        self.user32.GetAncestor.restype = ctypes.wintypes.HWND
        self.user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        self.user32.CallWindowProcW.restype = long_ptr
        self.user32.DefWindowProcW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        self.user32.DefWindowProcW.restype = long_ptr
        self.user32.SetLayeredWindowAttributes.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.COLORREF,
            ctypes.wintypes.BYTE,
            ctypes.wintypes.DWORD,
        ]
        self.user32.SetWindowPos.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        self.user32.EnumChildWindows.argtypes = [
            ctypes.wintypes.HWND,
            self.enum_child_proc,
            ctypes.wintypes.LPARAM,
        ]
        self.user32.EnumChildWindows.restype = ctypes.wintypes.BOOL
        self.user32.RedrawWindow.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]

    def root_hwnd(self, hwnd: int) -> int:
        root = int(self.user32.GetAncestor(hwnd, self.GA_ROOT))
        return root or hwnd

    def apply(self, hwnd: int, opacity: float, click_through: bool) -> None:
        style = int(self.get_window_long(hwnd, self.GWL_EXSTYLE))
        style |= self.WS_EX_LAYERED | self.WS_EX_TOPMOST | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE
        style &= ~self.WS_EX_APPWINDOW
        if click_through:
            style |= self.WS_EX_TRANSPARENT
        else:
            style &= ~self.WS_EX_TRANSPARENT

        self.set_window_long(hwnd, self.GWL_EXSTYLE, style)
        alpha = int(max(0.15, min(1.0, opacity)) * 255)
        self.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, self.LWA_ALPHA)
        self.user32.RedrawWindow(hwnd, None, None, self.RDW_INVALIDATE | self.RDW_FRAME)
        self.keep_topmost(hwnd)

    def apply_child(self, hwnd: int, click_through: bool) -> None:
        style = int(self.get_window_long(hwnd, self.GWL_EXSTYLE))
        style |= self.WS_EX_LAYERED
        if click_through:
            style |= self.WS_EX_TRANSPARENT
        else:
            style &= ~self.WS_EX_TRANSPARENT
        self.set_window_long(hwnd, self.GWL_EXSTYLE, style)
        self.user32.SetLayeredWindowAttributes(hwnd, 0, 255, self.LWA_ALPHA)
        self.user32.RedrawWindow(hwnd, None, None, self.RDW_INVALIDATE | self.RDW_FRAME)

    def proc_pointer(self, proc: int) -> ctypes.c_void_p:
        bits = ctypes.sizeof(ctypes.c_void_p) * 8
        return ctypes.c_void_p(proc & ((1 << bits) - 1))

    def install_hit_test_passthrough(self, hwnd: int, enabled: bool) -> None:
        hwnd = int(hwnd)
        if not enabled:
            existing = self.subclassed.pop(hwnd, None)
            if existing:
                old_proc, _callback = existing
                self.set_window_long(hwnd, self.GWLP_WNDPROC, old_proc)
            return
        if hwnd in self.subclassed:
            return

        old_proc_holder = [0]

        @self.wnd_proc_type
        def wnd_proc(current_hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == self.WM_NCHITTEST:
                return self.HTTRANSPARENT
            if msg == self.WM_MOUSEACTIVATE:
                return self.MA_NOACTIVATE
            old_proc = old_proc_holder[0]
            if old_proc:
                return self.user32.CallWindowProcW(
                    self.proc_pointer(old_proc),
                    current_hwnd,
                    msg,
                    wparam,
                    lparam,
                )
            return self.user32.DefWindowProcW(current_hwnd, msg, wparam, lparam)

        callback_ptr = ctypes.cast(wnd_proc, ctypes.c_void_p).value
        if not callback_ptr:
            return
        old_proc = int(self.set_window_long(hwnd, self.GWLP_WNDPROC, callback_ptr))
        old_proc_holder[0] = old_proc
        self.subclassed[hwnd] = (old_proc, wnd_proc)

    def child_windows(self, hwnd: int) -> list[int]:
        children: list[int] = []

        @self.enum_child_proc
        def collect(child_hwnd: int, _param: int) -> bool:
            children.append(child_hwnd)
            return True

        self.user32.EnumChildWindows(hwnd, collect, 0)
        return children

    def apply_tree(self, hwnd: int, opacity: float, click_through: bool) -> None:
        root = self.root_hwnd(hwnd)
        self.apply(root, opacity, click_through)
        self.install_hit_test_passthrough(root, click_through)
        for child_hwnd in self.child_windows(root):
            self.apply_child(child_hwnd, click_through)
            self.install_hit_test_passthrough(child_hwnd, click_through)

    def keep_topmost(self, hwnd: int) -> None:
        self.user32.SetWindowPos(
            hwnd,
            self.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE | self.SWP_SHOWWINDOW,
        )


class PowerOverlay:
    def __init__(
        self,
        config: dict[str, object],
        reader: BatteryInfoReader,
        click_through: bool,
    ) -> None:
        self.config = config
        self.reader = reader
        self.click_through = click_through
        self.samples: queue.Queue[PowerSample] = queue.Queue(maxsize=3)
        self.stop_event = threading.Event()
        self.last_text = ""
        self.last_percent_text = ""
        self.last_error_state = False
        self.last_discharging = False
        self.win32 = Win32OverlayStyle() if os.name == "nt" else None

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        font_config = config.get("font", {})
        position_config = config.get("position", {})
        padding_config = config.get("padding", {})
        graph_config = config.get("graph", {})
        percent_config = config.get("percent", {})
        credit_config = config.get("credit", {})
        dodge_config = config.get("dodge", {})
        assert isinstance(font_config, dict)
        assert isinstance(position_config, dict)
        assert isinstance(padding_config, dict)
        assert isinstance(graph_config, dict)
        assert isinstance(percent_config, dict)
        assert isinstance(credit_config, dict)
        assert isinstance(dodge_config, dict)

        family = str(font_config.get("family", DEFAULT_CONFIG["font"]["family"]))
        size = as_int(font_config.get("size"), 12, 7, 32)
        bg = str(config.get("background", DEFAULT_CONFIG["background"]))
        fg = str(config.get("foreground", DEFAULT_CONFIG["foreground"]))
        padx = as_int(padding_config.get("x"), 8, 0, 32)
        pady = as_int(padding_config.get("y"), 3, 0, 24)
        interval = as_float(config.get("sample_interval_seconds"), 1.0, 1.0, 300.0)

        graph_defaults = DEFAULT_CONFIG["graph"]
        assert isinstance(graph_defaults, dict)
        self.graph_enabled = bool(graph_config.get("enabled", graph_defaults["enabled"]))
        self.graph_width = as_int(graph_config.get("width"), int(graph_defaults["width"]), 48, 360)
        self.graph_height = as_int(graph_config.get("height"), int(graph_defaults["height"]), 16, 160)
        history_seconds = as_int(
            graph_config.get("history_seconds"),
            int(graph_defaults["history_seconds"]),
            5,
            3600,
        )
        history_points = max(2, int(history_seconds / interval))
        self.graph_values: deque[tuple[float, bool] | None] = deque(maxlen=history_points)
        self.graph_line = str(graph_config.get("line", graph_defaults["line"]))
        self.graph_discharge_line = str(graph_config.get("discharge_line", graph_defaults["discharge_line"]))
        self.graph_baseline = str(graph_config.get("baseline", graph_defaults["baseline"]))

        percent_defaults = DEFAULT_CONFIG["percent"]
        assert isinstance(percent_defaults, dict)
        percent_font = percent_config.get("font", {})
        percent_default_font = percent_defaults["font"]
        assert isinstance(percent_font, dict)
        assert isinstance(percent_default_font, dict)
        self.percent_enabled = bool(percent_config.get("enabled", percent_defaults["enabled"]))
        self.percent_family = str(percent_font.get("family", percent_default_font["family"]))
        self.percent_size = as_int(percent_font.get("size"), int(percent_default_font["size"]), 6, 24)
        self.percent_foreground = str(percent_config.get("foreground", percent_defaults["foreground"]))

        credit_defaults = DEFAULT_CONFIG["credit"]
        assert isinstance(credit_defaults, dict)
        credit_font = credit_config.get("font", {})
        credit_default_font = credit_defaults["font"]
        assert isinstance(credit_font, dict)
        assert isinstance(credit_default_font, dict)
        self.credit_enabled = bool(credit_config.get("enabled", credit_defaults["enabled"]))
        self.credit_text = str(credit_config.get("text", credit_defaults["text"]))
        self.credit_proximity = as_int(
            credit_config.get("proximity_pixels"),
            int(credit_defaults["proximity_pixels"]),
            4,
            200,
        )
        self.credit_poll_ms = as_int(credit_config.get("poll_ms"), int(credit_defaults["poll_ms"]), 100, 2000)
        self.credit_visible = False

        dodge_defaults = DEFAULT_CONFIG["dodge"]
        assert isinstance(dodge_defaults, dict)
        self.dodge_enabled = bool(dodge_config.get("enabled", dodge_defaults["enabled"]))
        self.dodge_poll_ms = as_int(dodge_config.get("poll_ms"), int(dodge_defaults["poll_ms"]), 50, 1000)
        self.dodge_gap = as_int(dodge_config.get("gap_pixels"), int(dodge_defaults["gap_pixels"]), 0, 80)
        self.dodge_return_margin = as_int(
            dodge_config.get("return_margin_pixels"),
            int(dodge_defaults["return_margin_pixels"]),
            0,
            240,
        )
        self.dodged = False

        self.container = tk.Frame(self.root, bg=bg, bd=0, highlightthickness=0)
        self.container.pack()
        self.main_panel = tk.Frame(self.container, bg=bg, bd=0, highlightthickness=0)
        self.main_panel.pack(side="left", anchor="nw")

        self.header = tk.Frame(self.main_panel, bg=bg, bd=0, highlightthickness=0)
        self.header.pack(anchor="w", fill="x")
        self.header.grid_columnconfigure(0, weight=1)

        self.label = tk.Label(
            self.header,
            text="-- W",
            font=(family, size),
            bg=bg,
            fg=fg,
            bd=0,
            padx=padx,
            pady=pady,
        )
        self.label.grid(row=0, column=0, sticky="w")

        self.percent_label: tk.Label | None = None
        if self.percent_enabled:
            self.percent_label = tk.Label(
                self.header,
                text="--%",
                font=(self.percent_family, self.percent_size),
                bg=bg,
                fg=self.percent_foreground,
                bd=0,
                padx=padx,
                pady=pady,
            )
            self.percent_label.grid(row=0, column=1, sticky="e")

        self.graph_canvas: tk.Canvas | None = None
        if self.graph_enabled:
            self.graph_canvas = tk.Canvas(
                self.main_panel,
                width=self.graph_width,
                height=self.graph_height,
                bg=bg,
                bd=0,
                highlightthickness=0,
                relief="flat",
            )
            self.graph_canvas.pack(anchor="w", padx=padx, pady=(0, max(1, pady)))
            self.draw_graph()

        self.credit_label: tk.Label | None = None
        if self.credit_enabled:
            self.credit_label = tk.Label(
                self.container,
                text=self.credit_text,
                font=(
                    str(credit_font.get("family", credit_default_font["family"])),
                    as_int(credit_font.get("size"), int(credit_default_font["size"]), 6, 20),
                ),
                bg=bg,
                fg=str(credit_config.get("foreground", credit_defaults["foreground"])),
                bd=0,
                padx=4,
                pady=0,
            )

        self.home_x = as_int(position_config.get("x"), 6, -10000, 10000)
        self.home_y = as_int(position_config.get("y"), 6, -10000, 10000)
        self.current_x = self.home_x
        self.current_y = self.home_y
        self.root.geometry(self.geometry_at(self.current_x, self.current_y))
        self.root.update_idletasks()
        self.apply_window_style()

        self.poller = Poller(reader, interval, self.samples, self.stop_event)

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    @staticmethod
    def geometry_at(x: int, y: int) -> str:
        return f"{x:+d}{y:+d}"

    def move_window(self, x: int, y: int) -> None:
        if x == self.current_x and y == self.current_y:
            return
        self.current_x = x
        self.current_y = y
        self.root.geometry(self.geometry_at(x, y))
        self.root.update_idletasks()
        self.apply_window_style()

    def apply_window_style(self) -> None:
        opacity = as_float(self.config.get("opacity"), 0.72, 0.15, 1.0)
        if self.win32:
            hwnd = self.root.winfo_id()
            self.win32.apply_tree(hwnd, opacity, self.click_through)
        else:
            self.root.attributes("-alpha", opacity)

    def prime_window_style(self, passes: int = 8) -> None:
        self.apply_window_style()
        if passes > 1:
            self.root.after(80, self.prime_window_style, passes - 1)

    def format_sample(self, sample: PowerSample) -> tuple[str, bool, bool]:
        show_state = bool(self.config.get("show_state", False))
        if sample.watts is None:
            if sample.error == "rate missing" and sample.state:
                return sample.state[:18], True, False
            return "-- W", True, False

        watts = abs(sample.watts)
        if watts < 99.95:
            text = f"{watts:.1f} W"
        else:
            text = f"{watts:.0f} W"
        if show_state and sample.state:
            text = f"{text} {sample.state[:10]}"
        return text, False, sample.watts < 0

    @staticmethod
    def format_percent(percent: float | None) -> str:
        if percent is None:
            return "--%"
        return f"{percent:.0f}%"

    def set_text(self, text: str, is_error: bool, is_discharging: bool) -> None:
        if text == self.last_text and is_error == self.last_error_state and is_discharging == self.last_discharging:
            return
        self.last_text = text
        self.last_error_state = is_error
        self.last_discharging = is_discharging
        if is_error:
            fg_key = "error_foreground"
        elif is_discharging:
            fg_key = "discharge_foreground"
        else:
            fg_key = "foreground"
        self.label.configure(text=text, fg=str(self.config.get(fg_key, DEFAULT_CONFIG[fg_key])))
        self.root.update_idletasks()

    def set_percent(self, percent: float | None) -> None:
        if self.percent_label is None:
            return
        text = self.format_percent(percent)
        if text == self.last_percent_text:
            return
        self.last_percent_text = text
        self.percent_label.configure(text=text)
        self.root.update_idletasks()

    def add_graph_sample(self, sample: PowerSample) -> None:
        if not self.graph_enabled:
            return
        self.graph_values.append((abs(sample.watts), sample.watts < 0) if sample.watts is not None else None)
        self.draw_graph()

    def draw_graph(self) -> None:
        canvas = self.graph_canvas
        if canvas is None:
            return

        canvas.delete("all")
        width = self.graph_width
        height = self.graph_height
        pad = 2
        bottom = height - pad
        canvas.create_line(pad, bottom, width - pad, bottom, fill=self.graph_baseline)

        values = list(self.graph_values)
        valid_values = [value for value in values if value is not None]
        if len(valid_values) < 2:
            return

        max_value = max(max(value for value, _is_discharging in valid_values), 1.0)
        y_scale = (height - pad * 2) / max_value
        x_scale = (width - pad * 2) / max(1, self.graph_values.maxlen - 1)
        start_index = self.graph_values.maxlen - len(values)

        segment: list[float] = []
        segment_discharging = False
        for index, value in enumerate(values):
            if value is None:
                if len(segment) >= 4:
                    line_color = self.graph_discharge_line if segment_discharging else self.graph_line
                    canvas.create_line(*segment, fill=line_color, width=2, smooth=True)
                segment = []
                continue

            magnitude, is_discharging = value
            x = pad + (start_index + index) * x_scale
            y = bottom - min(magnitude * y_scale, height - pad * 2)
            if segment and is_discharging != segment_discharging:
                if len(segment) >= 4:
                    line_color = self.graph_discharge_line if segment_discharging else self.graph_line
                    canvas.create_line(*segment, fill=line_color, width=2, smooth=True)
                segment = segment[-2:]
            segment_discharging = is_discharging
            segment.extend([x, y])

        if len(segment) >= 4:
            line_color = self.graph_discharge_line if segment_discharging else self.graph_line
            canvas.create_line(*segment, fill=line_color, width=2, smooth=True)

    def set_credit_visible(self, visible: bool) -> None:
        if not self.credit_enabled or self.credit_label is None:
            return
        if visible == self.credit_visible:
            return

        self.credit_visible = visible
        if visible:
            self.credit_label.pack(side="left", anchor="n", padx=(4, 8), pady=(4, 0))
        else:
            self.credit_label.pack_forget()
        self.root.update_idletasks()
        self.apply_window_style()

    @staticmethod
    def point_in_rect(px: int, py: int, x: int, y: int, width: int, height: int, margin: int = 0) -> bool:
        return x - margin <= px <= x + width + margin and y - margin <= py <= y + height + margin

    def pointer_position(self) -> tuple[int, int] | None:
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        if pointer_x < 0 or pointer_y < 0:
            return None
        return pointer_x, pointer_y

    def pointer_is_near_overlay(self) -> bool:
        pointer = self.pointer_position()
        if pointer is None:
            return False

        pointer_x, pointer_y = pointer
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        margin = self.credit_proximity
        near_current = self.point_in_rect(
            pointer_x,
            pointer_y,
            self.current_x,
            self.current_y,
            width,
            height,
            margin,
        )
        near_home = self.dodged and self.point_in_rect(
            pointer_x,
            pointer_y,
            self.home_x,
            self.home_y,
            width,
            height,
            margin,
        )
        return near_current or near_home

    def set_dodged(self, dodged: bool) -> None:
        if dodged == self.dodged:
            return

        self.dodged = dodged
        height = max(1, self.root.winfo_height())
        if dodged:
            target_y = self.home_y + height + self.dodge_gap
            screen_height = max(height, self.root.winfo_screenheight())
            target_y = min(target_y, max(0, screen_height - height))
        else:
            target_y = self.home_y
        self.move_window(self.home_x, target_y)

    def update_dodge(self) -> None:
        if not self.dodge_enabled:
            return

        pointer = self.pointer_position()
        if pointer is None:
            return

        pointer_x, pointer_y = pointer
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        on_current = self.point_in_rect(pointer_x, pointer_y, self.current_x, self.current_y, width, height)
        if on_current and not self.dodged:
            self.set_dodged(True)
            return

        if self.dodged:
            margin = self.dodge_return_margin
            keep_dodged = self.point_in_rect(
                pointer_x,
                pointer_y,
                self.home_x,
                self.home_y,
                width,
                height,
                margin,
            ) or self.point_in_rect(
                pointer_x,
                pointer_y,
                self.current_x,
                self.current_y,
                width,
                height,
                margin,
            )
            if not keep_dodged:
                self.set_dodged(False)

    def poll_pointer(self) -> None:
        self.update_dodge()
        self.set_credit_visible(self.pointer_is_near_overlay())
        self.root.after(min(self.credit_poll_ms, self.dodge_poll_ms), self.poll_pointer)

    def pump_samples(self) -> None:
        latest: PowerSample | None = None
        while True:
            try:
                latest = self.samples.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            text, is_error, is_discharging = self.format_sample(latest)
            self.set_text(text, is_error, is_discharging)
            self.set_percent(latest.percent)
            self.add_graph_sample(latest)
        self.root.after(1000, self.pump_samples)

    def refresh_topmost(self) -> None:
        if self.win32:
            hwnd = self.win32.root_hwnd(self.root.winfo_id())
            self.win32.apply_tree(hwnd, as_float(self.config.get("opacity"), 0.72, 0.15, 1.0), self.click_through)
            self.win32.keep_topmost(hwnd)
        else:
            self.root.attributes("-topmost", True)
        self.root.after(1000, self.refresh_topmost)

    def close(self) -> None:
        self.stop_event.set()
        self.root.destroy()

    def run(self) -> None:
        self.poller.start()
        self.root.after(0, self.prime_window_style)
        self.root.after(1000, self.pump_samples)
        self.root.after(min(self.credit_poll_ms, self.dodge_poll_ms), self.poll_pointer)
        self.root.after(1000, self.refresh_topmost)
        self.root.mainloop()
        self.stop_event.set()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BatteryInfoView-powered click-through power overlay.")
    parser.add_argument("--config", help=f"configuration JSON path; default: .\\{CONFIG_NAME}")
    parser.add_argument("--batteryinfo", help="BatteryInfoView.exe path; saved into config when valid")
    parser.add_argument("--interval", type=float, help="poll interval in seconds; overrides config for this run")
    parser.add_argument("--opacity", type=float, help="overlay opacity 0.15..1.0; overrides config for this run")
    parser.add_argument("--allow-clicks", action="store_true", help="debug mode: make the overlay clickable")
    parser.add_argument("--no-startup", action="store_true", help="do not register the packaged exe for user startup")
    parser.add_argument("--once", action="store_true", help="read once, print watts, and exit")
    return parser.parse_args()


def apply_cli_overrides(config: dict[str, object], args: argparse.Namespace) -> None:
    if args.interval is not None:
        config["sample_interval_seconds"] = as_float(args.interval, 1.0, 1.0, 300.0)
    if args.opacity is not None:
        config["opacity"] = as_float(args.opacity, 0.72, 0.15, 1.0)
    if args.no_startup:
        config["register_startup_on_first_run"] = False


def main() -> int:
    args = parse_args()
    config_path = choose_config_path(args.config)

    selector_root = tk.Tk()
    selector_root.withdraw()
    config = load_config(config_path)
    apply_cli_overrides(config, args)
    batteryinfo_path = resolve_batteryinfo_path(config, config_path, args.batteryinfo)
    selector_root.destroy()

    if batteryinfo_path is None:
        return 2

    timeout = as_float(config.get("subprocess_timeout_seconds"), 6.0, 1.0, 60.0)
    reader = BatteryInfoReader(batteryinfo_path, timeout)

    if args.once:
        sample = reader.read()
        if sample.watts is None:
            print(f"ERROR: {sample.error or 'no power value'}")
            return 1
        print(f"{abs(sample.watts):.3f} W")
        return 0

    ensure_startup_registered(config, config_path)

    overlay = PowerOverlay(config, reader, click_through=not args.allow_clicks)
    overlay.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
