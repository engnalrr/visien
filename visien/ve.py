"""Visual Enhancer engine: discovery and the official command-line tool (VE_CLI.exe).

Visien never ships or downloads Visual Enhancer. The user installs it from the
official release page; Visien finds the folder and drives VE_CLI.exe with
presets in Visual Enhancer's own JSON format (schema 41).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import CACHE_DIR, CONFIG, ENGINE_DIR, ROOT, known_folder

RELEASE_URL = "https://github.com/Merserk/dlss5-visual-enhancer/releases/latest"
CLI_NAME = "VE_CLI.exe"
APP_NAME = "Visual Enhancer.exe"
PRESET_FORMAT = "dlss5-visual-enhancer-settings-preset"
PRESET_SCHEMA = 41
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SKIP = {".venv", "venv", "node_modules", ".git", "__pycache__", "$recycle.bin", "appdata", "windows",
        "system volume information", "program files", "program files (x86)", "visien", "data", "qml",
        "translations", "resources", "imageformats", "platforms", "outputs", "logs"}
MAX_DEPTH = 4


class EngineMissing(RuntimeError):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ discovery


def inspect(directory: Path) -> dict:
    missing = [name for name, ok in ((CLI_NAME, (directory / CLI_NAME).is_file()),
                                     (APP_NAME, (directory / APP_NAME).is_file()),
                                     ("bin\\", (directory / "bin").is_dir())) if not ok]
    return {"path": str(directory), "complete": not missing, "missing": missing}


def _walk(root: Path, depth: int, found: list[dict], seen: set[str]) -> None:
    if depth > MAX_DEPTH:
        return
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    names = set()
    for entry in entries:
        try:
            if entry.is_file(follow_symlinks=False):
                names.add(entry.name.lower())
        except OSError:
            continue
    if CLI_NAME.lower() in names or APP_NAME.lower() in names:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            found.append(inspect(root))
        return
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False) and entry.name.lower() not in SKIP and not entry.name.startswith("."):
                _walk(Path(entry.path), depth + 1, found, seen)
        except OSError:
            continue


def search_roots() -> list[Path]:
    home = Path.home()
    roots = [ENGINE_DIR, ROOT.parent]
    for name in ("Downloads", "Desktop", "Documents"):
        roots.append(known_folder(name))
        for base in (home, home / "OneDrive"):
            roots.append(base / name)
    for drive in ("C:\\", "D:\\", "E:\\"):
        roots.append(Path(drive) / "Visual Enhancer")
    unique, seen = [], set()
    for root in roots:
        key = str(root).lower()
        if key not in seen and root.is_dir():
            seen.add(key)
            unique.append(root)
    return unique


def _version_key(item: dict) -> tuple:
    numbers = re.findall(r"v?(\d+)\.(\d+)", Path(item["path"]).name)
    return tuple(int(x) for x in numbers[0]) if numbers else (0, 0)


def scan(auto_select: bool = True) -> dict:
    started = time.time()
    found: list[dict] = []
    seen: set[str] = set()
    for root in search_roots():
        _walk(root, 0, found, seen)
    found.sort(key=lambda i: (not i["complete"], tuple(-n for n in _version_key(i)), i["path"].lower()))
    selected = CONFIG.get("ve_dir") or ""
    complete = [i for i in found if i["complete"]]
    if auto_select and complete and not usable(selected):
        selected = complete[0]["path"]
        CONFIG.update({"ve_dir": selected})
        cli_version.cache_clear()
    return {"found": found, "selected": selected, "seconds": round(time.time() - started, 2)}


def usable(directory: str) -> bool:
    return bool(directory) and (Path(directory) / CLI_NAME).is_file()


def engine_dir() -> Path:
    configured = CONFIG.get("ve_dir")
    if usable(configured):
        return Path(configured)
    if configured and Path(configured).is_dir():
        found: list[dict] = []
        _walk(Path(configured), MAX_DEPTH - 2, found, set())
        complete = [i for i in found if i["complete"]]
        if complete:
            CONFIG.update({"ve_dir": complete[0]["path"]})
            return Path(complete[0]["path"])
        if found:
            raise EngineMissing(missing_message(found[0]))
    result = scan(auto_select=True)
    if usable(result["selected"]):
        return Path(result["selected"])
    if result["found"]:
        raise EngineMissing(missing_message(result["found"][0]))
    raise EngineMissing("Visual Enhancer was not found. Download it from the official release page, extract the "
                        "package and press “Find automatically” in Settings.")


def missing_message(item: dict) -> str:
    hint = ""
    if CLI_NAME in item["missing"] and APP_NAME not in item["missing"]:
        hint = " Windows Security may have quarantined VE_CLI.exe (Windows Security › Protection history)."
    elif "bin\\" in item["missing"]:
        hint = " The archive looks partially extracted; extract the complete release package."
    return f"Visual Enhancer is incomplete ({item['path']}): missing {', '.join(item['missing'])}.{hint}"


def status() -> dict:
    if os.name != "nt" and not os.environ.get("VISIEN_FAKE_ENGINE"):
        return {"ok": False, "reason": "Visual Enhancer runs on Windows only.", "path": "", "version": ""}
    try:
        root = engine_dir()
    except EngineMissing as exc:
        return {"ok": False, "reason": str(exc), "path": "", "version": ""}
    return {"ok": True, "reason": "", "path": str(root), "version": cli_version(str(root)),
            "rtx": bool(_devices_cache.get("devices")) if _devices_cache else None,
            "adapters": [a.get("name", "") for a in _devices_cache.get("fsr_adapters", []) if a.get("name")],
            "rtx_problem": rtx_problem()}


def rtx_problem() -> str:
    """Why Visual Enhancer's cards cannot run on this PC ("" when they can, or before the GPUs were listed)."""
    if not _devices_cache or _devices_cache.get("devices"):
        return ""
    found = ", ".join(a.get("name", "") for a in _devices_cache.get("fsr_adapters", []) if a.get("name"))
    return ("Visual Enhancer's cards (DLSS 5 Neural Rendering, DLSS, RTX Video) need an NVIDIA GeForce RTX GPU"
            + (f"; this PC has {found}" if found else "") + ". Visien skips them here and runs only its AI cards "
            "(SeedVR2, RIFE, Face Restore): use Realism · SeedVR2 Restore, Realism · Faces or Smooth 60 · RIFE.")


@lru_cache(maxsize=4)
def cli_version(root: str) -> str:
    try:
        out = subprocess.run([str(Path(root) / CLI_NAME), "--version"], capture_output=True, text=True, timeout=60,
                             cwd=root, creationflags=NO_WINDOW).stdout.strip()
        return out.replace("Visual Enhancer CLI ", "") or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _last_json(text: str) -> dict:
    for line in reversed([l for l in text.splitlines() if l.strip()]):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    return {}


_devices_cache: dict = {}


def devices(refresh: bool = False) -> dict:
    if _devices_cache and not refresh:
        return _devices_cache
    root = engine_dir()
    result = subprocess.run([str(root / CLI_NAME), "devices", "--json"], cwd=str(root), capture_output=True,
                            timeout=180, creationflags=NO_WINDOW)
    data = _last_json(result.stdout.decode("utf-8", "replace"))
    if not data.get("ok"):
        raise RuntimeError(explain(data.get("error") or result.stderr.decode("utf-8", "replace")[-400:]))
    _devices_cache.clear()
    _devices_cache.update(data)
    return data


GPU_FAULTS = ("cuda 999", "engine poisoned", "cuda_error_unknown", "device lost", "dxgi_error_device_removed",
              "device removed")


def is_gpu_fault(message: str) -> bool:
    """Errors that come from the GPU/driver state rather than from the file or the settings."""
    low = (message or "").lower()
    return any(marker in low for marker in GPU_FAULTS)


def explain(message: str) -> str:
    text = message or "Unknown error."
    low = text.lower()
    if is_gpu_fault(text):
        return ("The graphics card stopped accepting work from Visual Enhancer (a GPU/driver error, not a problem "
                "with the file or the settings). Close other programs that use the GPU (Topaz, DaVinci Resolve, "
                "games, Visual Enhancer's own window while it renders), wait a few seconds and try again. "
                "If it keeps happening, restart Windows.\n\n" + text)
    if "out of memory" in low:
        return ("The graphics card ran out of memory. Lower the output size (Scale Factor, DLSS Mode) or close other "
                "programs that use the GPU, then try again.\n\n" + text)
    if "winerror 2" in low or "cannot find the file" in low:
        return "VE_CLI.exe could not be started; Windows Security may have blocked it.\n\n" + text
    if "winerror 5" in low or "access is denied" in low:
        return "Access to VE_CLI.exe was denied (Windows Security / SmartScreen).\n\n" + text
    return text


# ------------------------------------------------------------------ presets


def preset_document(settings: dict, name: str = "Visien") -> dict:
    return {"format": PRESET_FORMAT, "schema_version": PRESET_SCHEMA, "name": name[:120] or "Visien",
            "settings": settings}


def _write_preset(settings: dict, name: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", dir=CACHE_DIR, delete=False, encoding="utf-8") as handle:
        json.dump(preset_document(settings, name), handle, ensure_ascii=False)
        return handle.name


def _gpu_args() -> list[str]:
    gpu = str(CONFIG.get("gpu") or "auto")
    return [] if gpu == "auto" else ["--gpu", gpu]


# ------------------------------------------------------------------ dry run


def plan(source: str, settings: dict, target: str | None = None) -> dict:
    """Ask VE what it would do (output size, fps, stages) without rendering."""
    root = engine_dir()
    preset = _write_preset(settings, "Visien plan")
    out = target or str(Path(CACHE_DIR) / f"plan_{int(time.time() * 1000)}{Path(source).suffix or '.mp4'}")
    try:
        result = subprocess.run([str(root / CLI_NAME), "render", source, "-o", out, "--preset", preset,
                                 "--dry-run", "--json"], cwd=str(root), capture_output=True, timeout=120,
                                creationflags=NO_WINDOW)
    finally:
        os.unlink(preset)
    data = _last_json(result.stdout.decode("utf-8", "replace"))
    if not data.get("ok"):
        message = data.get("error") or result.stderr.decode("utf-8", "replace").strip()[-400:]
        return {"ok": False, "error": message.replace("Error: ", "")}
    item = (data.get("items") or [{}])[0]
    return {"ok": True, "width": item.get("width"), "height": item.get("height"), "fps": item.get("fps"),
            "hdr": item.get("hdr"), "stages": item.get("stages", [])}


# ------------------------------------------------------------------ render


_PROGRESS = re.compile(r"\]\s.*?\s(\d+(?:\.\d+)?)%\s+(.*)$")


@dataclass
class RenderResult:
    output: str
    seconds: float
    log_path: str


def render(source: str, target: str, settings: dict, *, name: str = "Visien",
           cancel: threading.Event | None = None, progress: Callable[[float, str], None] | None = None,
           log: Callable[[str], None] | None = None) -> RenderResult:
    root = engine_dir()
    preset = _write_preset(settings, name)
    cmd = [str(root / CLI_NAME), "render", source, "-o", target, "--preset", preset, "--json", *_gpu_args()]
    log = log or (lambda _text: None)
    log("VE_CLI render " + Path(source).name + " → " + Path(target).name)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=NO_WINDOW)
    except OSError as exc:
        os.unlink(preset)
        raise RuntimeError(explain(str(exc))) from exc
    tail: list[str] = []

    def handle(line: str, final: bool, state: dict) -> None:
        match = _PROGRESS.search(line)
        if match:
            if line == state.get("shown"):
                return
            state["shown"] = line
            fraction, message = float(match.group(1)) / 100.0, match.group(2).strip()
            if progress:
                progress(fraction, message)
            if fraction - state.get("last", -1) >= 0.1 or fraction >= 1.0:
                state["last"] = fraction
                log(f"{fraction * 100:.0f}% {message}")
        elif final:
            tail.append(line)
            del tail[:-60]
            if line.startswith("Error:"):
                log(line)

    def pump() -> None:
        buffer, state = b"", {}
        fd = proc.stderr.fileno()
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            parts = re.split(rb"[\r\n]", buffer)
            buffer = parts.pop()
            for raw in parts:
                text = raw.decode("utf-8", "replace").strip()
                if text:
                    handle(text, True, state)
            if b"%" in buffer:
                handle(buffer.decode("utf-8", "replace").strip(), False, state)
        if buffer.strip():
            handle(buffer.decode("utf-8", "replace").strip(), True, state)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    started = time.time()
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                stop(proc)
                raise Cancelled()
            time.sleep(0.25)
        stdout = proc.stdout.read().decode("utf-8", "replace")
        reader.join(timeout=5)
    finally:
        try:
            os.unlink(preset)
        except OSError:
            pass
    data = _last_json(stdout)
    item = (data.get("items") or [{}])[0]
    if proc.returncode != 0 or not data.get("ok"):
        message = item.get("error") or data.get("error") or "\n".join(tail[-8:]) or f"exit code {proc.returncode}"
        raise RuntimeError(explain(message.replace("Error: ", "")) +
                           (f"\nLog: {data['log_path']}" if data.get("log_path") else ""))
    output = item.get("output_path") or target
    if not Path(output).exists():
        raise RuntimeError(f"Visual Enhancer reported success but the output is missing: {output}")
    return RenderResult(output, round(time.time() - started, 2), data.get("log_path", ""))


def render_retrying(source: str, target: str, settings: dict, *, retries: int = 1, wait: float = 12.0,
                    cancel: threading.Event | None = None, log: Callable[[str], None] | None = None,
                    progress: Callable[[float, str], None] | None = None, name: str = "Visien") -> RenderResult:
    """render(), retried after a pause when the GPU/driver reports a transient fault (CUDA 999 and the like)."""
    log = log or (lambda _text: None)
    for attempt in range(retries + 1):
        try:
            return render(source, target, settings, name=name, cancel=cancel, progress=progress, log=log)
        except RuntimeError as exc:
            if attempt >= retries or not is_gpu_fault(str(exc)):
                raise
            try:
                Path(target).unlink(missing_ok=True)
            except OSError:
                pass
            pause = wait * (attempt + 1)
            log(f"GPU error, trying again in {pause:.0f} s (attempt {attempt + 2} of {retries + 1})")
            if progress:
                progress(0.0, f"GPU error - retrying in {pause:.0f} s")
            deadline = time.time() + pause
            while time.time() < deadline:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                time.sleep(0.25)
    raise RuntimeError("unreachable")


def stop(proc: subprocess.Popen) -> None:
    """Stop VE_CLI and the worker processes it started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=NO_WINDOW)
        else:
            proc.terminate()
        proc.wait(timeout=15)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except OSError:
            pass
