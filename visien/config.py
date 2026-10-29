"""Paths and persisted user settings (portable: everything lives next to the app)."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

_KNOWN = {"Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
          "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"}


def known_folder(name: str) -> Path:
    """A Windows known folder (follows OneDrive / drive redirection), else ~/<name>."""
    if os.name == "nt" and name in _KNOWN:
        try:
            import ctypes  # noqa: WPS433
            import uuid  # noqa: WPS433
            from ctypes import wintypes  # noqa: WPS433

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                            ("Data4", ctypes.c_ubyte * 8)]

            raw = uuid.UUID(_KNOWN[name]).bytes_le
            guid = GUID.from_buffer_copy(raw)
            buffer = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buffer)) == 0:
                path = Path(buffer.value)
                ctypes.windll.ole32.CoTaskMemFree(buffer)
                return path
        except Exception:  # noqa: BLE001
            pass
    return Path.home() / name
DATA_DIR = Path(os.environ.get("VISIEN_DATA", ROOT / "data"))
UI_DIR = ROOT / "ui"
BUILTIN_PRESETS_DIR = ROOT / "presets"
ENGINE_DIR = ROOT / "engine"            # drop folder for Visual Enhancer
TOOLS_DIR = ROOT / "tools"
USER_PRESETS_DIR = DATA_DIR / "presets"
CACHE_DIR = DATA_DIR / "cache"
PREVIEW_DIR = DATA_DIR / "previews"
THUMB_DIR = DATA_DIR / "thumbs"
CONFIG_PATH = DATA_DIR / "settings.json"
DEFAULT_OUTPUT = known_folder("Videos") / "Visien" if os.name == "nt" else ROOT / "outputs"

DEFAULTS: dict[str, Any] = {
    "ve_dir": "",
    "output_dir": "",
    "naming": "suffix",          # suffix | copy
    "suffix": "_Visien",
    "gpu": "auto",
    "preview_length": "3",
    "ffmpeg_dir": "",
    "last_dir": "",
    "port": 7870,
    "keep_previews": 12,
    "preview_cache_gb": 10,
}


class Config:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                self._data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def get(self, key: str) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def all(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._data)
        data["output_dir_effective"] = str(output_dir())
        return data

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for key, value in values.items():
                if key in DEFAULTS:
                    self._data[key] = value
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CONFIG_PATH)
        return self.all()


CONFIG = Config()


def output_dir() -> Path:
    configured = CONFIG.get("output_dir")
    return Path(configured) if configured else DEFAULT_OUTPUT


def ensure_dirs() -> None:
    for directory in (DATA_DIR, USER_PRESETS_DIR, CACHE_DIR, PREVIEW_DIR, THUMB_DIR, ENGINE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def find_tool(name: str) -> str:
    """ffmpeg / ffprobe: configured folder, bundled tools/ffmpeg, then PATH."""
    candidates = []
    if CONFIG.get("ffmpeg_dir"):
        candidates.append(Path(CONFIG.get("ffmpeg_dir")))
    candidates.append(TOOLS_DIR / "ffmpeg" / "bin")
    for directory in candidates:
        path = directory / _exe(name)
        if path.is_file():
            return str(path)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} not found. Run install.bat again or set the ffmpeg folder in Settings.")
