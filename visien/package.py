"""Shareable Visien packages (Settings › Share Visien, or dev/build_full_package.py).

slim  The app only (~2 MB). install.bat downloads Python, the packages and ffmpeg; the AI runtime and models are
      installed from Settings › AI models.
full  Everything except Visual Enhancer (its licence does not allow redistribution): the app, a relocatable
      CPython 3.12 with all packages (runtime/python), ffmpeg/ffprobe, uv, the AI runtime (ai/site-packages:
      PyTorch with CUDA, OpenCV, spandrel …) and the recommended models (SeedVR2 3B FP8 + VAE, RIFE 4.26, YuNet,
      GFPGAN 1.4). The receiving PC needs no internet for setup. CodeFormer (non-commercial licence) and the optional
      SeedVR2 variants are never included; they can be installed from Settings › AI models.

Model weights and other big binaries are stored without compression (they barely compress), the rest with fast
deflate.
"""

from __future__ import annotations

import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import __version__
from .config import ROOT

APP_ITEMS = ["visien", "ui", "presets", "vendor", "dev", "README.md", "install.bat", "install.ps1",
             "requirements.txt", "Visien.bat", "Visien (browser).bat"]
ENGINE_NOTE = ("Visual Enhancer is not included (its licence does not allow redistribution).\r\n"
               "Download it from https://github.com/Merserk/dlss5-visual-enhancer/releases/latest and extract the\r\n"
               "whole package here or in Downloads, then press Find automatically in Visien's Settings.\r\n")
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIX = (".pyc", ".pyo")
# Recommended models: all of them allow commercial use.
MODEL_FILES = ["seedvr2/ema_vae_fp16.safetensors", "seedvr2/seedvr2_ema_3b_fp8_e4m3fn.safetensors",
               "rife/rife426.pth", "face/face_detection_yunet_2023mar.onnx", "face/GFPGANv1.4.pth"]
MODEL_SOURCES = "\r\n".join([
    "Models shipped with Visien (each under its own licence):",
    "seedvr2/*  SeedVR2 by ByteDance Seed, Apache 2.0. Files from huggingface.co/numz/SeedVR2_comfyUI.",
    "rife/rife426.pth  Practical-RIFE 4.26 by hzwer, MIT. File from the ComfyUI-Frame-Interpolation releases.",
    "face/GFPGANv1.4.pth  GFPGAN by TencentARC, Apache 2.0. github.com/TencentARC/GFPGAN/releases",
    "face/face_detection_yunet_2023mar.onnx  YuNet, MIT. github.com/opencv/opencv_zoo",
    "Not included: CodeFormer (NTU S-Lab License 1.0, non-commercial) - install it from Settings > AI models.", ""])
FFMPEG_SOURCE = ("ffmpeg/ffprobe: GPLv3 build by BtbN (https://github.com/BtbN/FFmpeg-Builds).\r\n"
                 "Source code: https://github.com/FFmpeg/FFmpeg and the build scripts at the address above.\r\n")
# Installed only after the CodeFormer licence is accepted, so never shipped.
AI_SKIP = {"spandrel_extra_arches"}
STORED = (".safetensors", ".pth", ".onnx", ".pt", ".zip", ".gz", ".whl", ".gguf")


class Plan:
    """Entries of a package: (source path | text, archive name)."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, str]] = []

    def file(self, path: Path, arc: str) -> None:
        self.entries.append(("file", str(path), arc))

    def text(self, arc: str, content: str) -> None:
        self.entries.append(("text", content, arc))

    def tree(self, source: Path, arc: str, skip: set[str] | None = None) -> None:
        skip = (skip or set()) | SKIP_DIRS
        if source.is_file():
            self.file(source, arc)
            return
        for root, dirs, files in os.walk(source):
            dirs[:] = sorted(d for d in dirs if d not in skip and not any(
                d.startswith(s + "-") and d.endswith(".dist-info") for s in skip))
            for name in sorted(files):
                if not name.endswith(SKIP_SUFFIX):
                    path = Path(root) / name
                    self.file(path, f"{arc}/{path.relative_to(source).as_posix()}")

    def size(self) -> int:
        return sum(os.path.getsize(src) if kind == "file" else len(src) for kind, src, _ in self.entries)


def _app(plan: Plan, folder: Path) -> None:
    for item in APP_ITEMS:
        if (folder / item).exists():
            plan.tree(folder / item, f"Visien/{item}")
    plan.text("Visien/engine/README.txt", ENGINE_NOTE)  # never ship the engine folder's contents


def _python(plan: Plan, folder: Path) -> None:
    bundled = folder / "runtime" / "python"
    if (bundled / "python.exe").is_file() and (bundled / "Lib" / "site-packages" / "webview").is_dir():
        plan.tree(bundled, "Visien/runtime/python")
        return
    pythons = sorted(p for p in (folder / "tools" / "python").glob("cpython-3.12.*-windows-x86_64-none")
                     if (p / "python.exe").is_file())
    site = folder / ".venv" / "Lib" / "site-packages"
    if not pythons or not (site / "webview").is_dir():
        raise RuntimeError("No complete Python found (runtime\\python, or tools\\python with .venv). "
                           "Run install.bat in this Visien folder first.")
    python = pythons[-1]
    for root, dirs, files in os.walk(python):
        rel = Path(root).relative_to(python)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (rel == Path("Lib") and d == "site-packages")]
        for name in files:
            if not name.endswith(SKIP_SUFFIX) and name != "EXTERNALLY-MANAGED":
                path = Path(root) / name
                plan.file(path, f"Visien/runtime/python/{path.relative_to(python).as_posix()}")
    plan.tree(site, "Visien/runtime/python/Lib/site-packages")


def plan_for(kind: str, folder: Path = ROOT) -> Plan:
    plan = Plan()
    _app(plan, folder)
    if kind == "slim":
        return plan
    ffbin = folder / "tools" / "ffmpeg" / "bin"
    ai_site = folder / "ai" / "site-packages"
    needed = [ffbin / "ffmpeg.exe", ffbin / "ffprobe.exe", ai_site / "torch", ai_site / "spandrel"]
    needed += [folder / "models" / name for name in MODEL_FILES]
    missing = [p for p in needed if not p.exists()]
    if missing:
        names = ", ".join(p.name for p in missing)
        raise RuntimeError(f"The full package needs everything installed here first: ffmpeg (install.bat) and the "
                           f"recommended AI models (Settings › AI models). Missing: {names}")
    _python(plan, folder)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        plan.file(ffbin / name, f"Visien/tools/ffmpeg/bin/{name}")
    licence = folder / "tools" / "ffmpeg" / "LICENSE.txt"
    if licence.is_file():
        plan.file(licence, "Visien/tools/ffmpeg/LICENSE.txt")
    plan.text("Visien/tools/ffmpeg/SOURCE.txt", FFMPEG_SOURCE)
    uv = folder / "tools" / "uv" / "uv.exe"
    if uv.is_file():  # installs optional models and packages later without a system Python
        plan.file(uv, "Visien/tools/uv/uv.exe")
        plan.text("Visien/tools/uv/SOURCE.txt", "uv by Astral (MIT or Apache 2.0): https://github.com/astral-sh/uv\r\n")
    plan.tree(ai_site, "Visien/ai/site-packages", skip=AI_SKIP)
    for name in MODEL_FILES:
        plan.file(folder / "models" / name, f"Visien/models/{name}")
    plan.text("Visien/models/SOURCES.txt", MODEL_SOURCES)
    return plan


def write(plan: Plan, target: Path, progress: Callable[[int, int, int, int], None] | None = None,
          cancel: threading.Event | None = None) -> Path:
    """Writes the package; progress(files_done, files_total, bytes_done, bytes_total)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    total_bytes, total_files = plan.size(), len(plan.entries)
    part = target.with_name(target.name + ".part")
    done_bytes = 0
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zf:
            for index, (kind, source, arc) in enumerate(plan.entries):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Cancelled.")
                size = len(source) if kind == "text" else os.path.getsize(source)
                if progress and size > 32 * 1024 * 1024:  # say which big file is being written
                    progress(index, total_files, done_bytes, total_bytes)
                if kind == "text":
                    zf.writestr(arc, source)
                    done_bytes += size
                else:
                    stored = source.lower().endswith(STORED)
                    zf.write(source, arc, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
                    done_bytes += size
                if progress and (index % 50 == 0 or size > 32 * 1024 * 1024 or index == total_files - 1):
                    progress(index + 1, total_files, done_bytes, total_bytes)
        part.replace(target)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    return target


# ---------------------------------------------------------------- background job for the app

_job: dict = {"state": "idle"}
_lock = threading.Lock()
_cancel = threading.Event()


def status() -> dict:
    with _lock:
        return dict(_job)


def start(kind: str, folder: str) -> dict:
    if kind not in ("slim", "full"):
        raise ValueError("Unknown package type.")
    out_dir = Path(folder).expanduser() if folder else ROOT.parent
    if not out_dir.is_dir():
        raise ValueError(f"Folder not found: {out_dir}")
    if out_dir.resolve() == ROOT.resolve() or ROOT.resolve() in out_dir.resolve().parents:
        raise ValueError("Choose a folder outside the Visien folder.")
    with _lock:
        if _job.get("state") == "running":
            raise ValueError("A package is already being created.")
        name = f"Visien-{__version__}{'-full' if kind == 'full' else ''}.zip"
        target = out_dir / name
        number = 2
        while target.exists():
            target = out_dir / name.replace(".zip", f"_{number}.zip")
            number += 1
        _job.clear()
        _job.update(state="running", kind=kind, path=str(target), progress=0.0, message="Listing files", error="",
                    started=time.time())
    _cancel.clear()

    def run() -> None:
        try:
            plan = plan_for(kind)

            def report(files: int, files_total: int, done: int, total: int) -> None:
                with _lock:
                    _job.update(progress=done / max(total, 1),
                                message=f"{files}/{files_total} files · {done / 1024 ** 3:.2f} of "
                                        f"{total / 1024 ** 3:.2f} GB")

            write(plan, target, report, _cancel)
            with _lock:
                _job.update(state="done", progress=1.0, message=f"Ready: {target.name}",
                            size=target.stat().st_size, finished=time.time())
        except InterruptedError:
            with _lock:
                _job.update(state="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - shown in Settings
            with _lock:
                _job.update(state="error", message="Failed", error=str(exc)[:600])

    threading.Thread(target=run, name="visien-package", daemon=True).start()
    return status()


def cancel() -> dict:
    _cancel.set()
    return status()
