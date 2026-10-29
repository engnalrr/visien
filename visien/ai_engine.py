"""Runs one AI stage (SeedVR2, RIFE, Face Restore) in the AI runtime as a separate process."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from . import models, ve
from .config import DATA_DIR, ROOT, find_tool

LOG_DIR = DATA_DIR / "logs"
NOTEWORTHY = re.compile(r"error|warning|out of memory|fallback|traceback", re.IGNORECASE)
IGNORED = re.compile(r"deprecat|setPreferableTarget|FutureWarning|UserWarning|TypedStorage|optimizations check|"
                     r"pip install|\[INFO\]|attempt \d", re.IGNORECASE)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TITLES = {"seedvr2": "SeedVR2", "rife": "RIFE", "face_restore": "Face Restore", "color_match": "Color Match"}


# SeedVR2 needs most of the GPU: two at once (a preview during a render) would starve each other.
_heavy = threading.Lock()
_active = {"count": 0}
_active_lock = threading.Lock()


def active() -> int:
    """Number of AI runners running now (the runtime must not be removed meanwhile)."""
    with _active_lock:
        return _active["count"]


def _prune_logs() -> None:
    logs = sorted(LOG_DIR.glob("ai-*.log"), key=lambda path: path.stat().st_mtime if path.exists() else 0)
    for old in logs[:-40]:  # keep the 40 newest
        try:
            old.unlink()
        except OSError:  # open in another run, or already gone
            pass


def _wait_for_gpu(stage: str, cancel, progress, log) -> bool:
    if stage != "seedvr2":
        return False
    if _heavy.acquire(blocking=False):
        return True
    log("SeedVR2: waiting for the other SeedVR2 run to finish")
    while not _heavy.acquire(timeout=0.5):
        if progress:
            progress(0.0, "Waiting for the GPU (another SeedVR2 run)")
        if cancel is not None and cancel.is_set():
            raise ve.Cancelled()
    return True


def run_stage(stage: str, source: str, target: str, settings: dict, kind: str, *,
              cancel: threading.Event | None = None, progress: Callable[[float, str], None] | None = None,
              log: Callable[[str], None] | None = None) -> dict:
    log = log or (lambda _text: None)
    missing = [c for c in models.required({**settings, f"vz_{kind}_ai": [stage],
                                           f"{kind}_enabled_stages": []}, kind) if not models.installed(c)]
    if missing:
        raise RuntimeError(models.missing_message(missing))
    locked = _wait_for_gpu(stage, cancel, progress, log)
    with _active_lock:
        _active["count"] += 1
    params = ""
    log_file = None
    proc = None
    threads: list[threading.Thread] = []
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _prune_logs()
    log_path = LOG_DIR / f"ai-{stage}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}.log"
    log_lock = threading.Lock()
    state: dict = {"result": None, "error": "", "tail": [], "noted": 0}

    def keep(line: str) -> None:
        with log_lock:
            if log_file is not None and not log_file.closed:
                log_file.write(time.strftime("%H:%M:%S ") + line + "\n")
                log_file.flush()

    def note(line: str) -> None:
        if state["noted"] < 12 and NOTEWORTHY.search(line) and not IGNORED.search(line) and \
                not line.lstrip().startswith(("File ", "^")):
            state["noted"] += 1
            log(f"{TITLES.get(stage, stage)}: {line.strip()[:200]}")

    def read_out() -> None:
        last_logged = -1.0
        for line in proc.stdout:
            line = line.rstrip()
            if not line.startswith("@@VZ "):
                keep(line)
            if line.startswith("@@VZ-RESULT "):
                try:
                    state["result"] = json.loads(line[len("@@VZ-RESULT "):])
                except ValueError:
                    state["result"] = {}
            elif line.startswith("@@VZ-ERROR "):
                state["error"] = line[len("@@VZ-ERROR "):]
            elif line.startswith("@@VZ "):
                parts = line.split(" ", 2)
                try:
                    fraction = float(parts[1]) / 100.0
                except (IndexError, ValueError):
                    continue
                message = parts[2] if len(parts) > 2 else TITLES.get(stage, stage)
                if progress:
                    progress(fraction, message)
                if fraction - last_logged >= 0.1 or fraction >= 1.0:
                    last_logged = fraction
                    log(f"{fraction * 100:.0f}% {message}")
                    keep(f"{fraction * 100:.0f}% {message}")
            elif line.strip():
                state["tail"].append(line)
                del state["tail"][:-60]
                note(line)

    def read_err() -> None:
        for line in proc.stderr:
            if line.strip():
                keep(line.rstrip())
                state["tail"].append(line.rstrip())
                del state["tail"][:-60]
                note(line)

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=models.cache_dir(), delete=False,
                                         encoding="utf-8") as handle:
            json.dump(settings, handle)
            params = handle.name
        cmd = [models.ai_python(), "-u", "-m", "visien.ai.run", stage, "--input", source, "--output", target,
               "--kind", kind, "--params", params, "--models", str(models.MODELS_DIR), "--ffmpeg",
               find_tool("ffmpeg"), "--ffprobe", find_tool("ffprobe"), "--root", str(ROOT)]
        log(f"{TITLES.get(stage, stage)}: {Path(source).name} → {Path(target).name}")
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        log_file.write(" ".join(cmd) + "\n\n")
        env = models.ai_env()
        env["VISIEN_AI_LOGGED"] = "1"
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace",
                                    bufsize=1)
        except OSError as exc:
            raise RuntimeError(f"{TITLES.get(stage, stage)}: the AI runtime could not start ({exc}). Reinstall it in "
                               "Settings › AI models.") from exc
        threads = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
        for thread in threads:
            thread.start()
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                ve.stop(proc)
                raise ve.Cancelled()
            time.sleep(0.25)
    finally:
        for thread in threads:
            thread.join(timeout=10)
        if params:
            try:
                os.unlink(params)
            except OSError:
                pass
        with log_lock:
            if log_file is not None:
                log_file.write(f"\nexit code {proc.poll() if proc else 'not started'}\n")
                log_file.close()
        with _active_lock:
            _active["count"] -= 1
        if locked:
            _heavy.release()
    if proc.returncode != 0 or state["result"] is None:
        detail = state["error"] or "\n".join(state["tail"][-8:]) or ""
        if not state["error"]:
            code = proc.returncode if proc.returncode is not None else "?"
            unsigned = code & 0xFFFFFFFF if isinstance(code, int) else code
            crashed = isinstance(code, int) and (code < 0 or unsigned >= 0xC0000000)
            detail = (f"the AI process stopped unexpectedly (exit code {code}"
                      f"{f' / 0x{unsigned:08X}' if isinstance(code, int) and unsigned >= 0xC0000000 else ''})."
                      + (" This is usually the graphics driver or running out of memory." if crashed else "")
                      + (f" Last output: {detail.splitlines()[-1][:200]}" if detail else ""))
        raise RuntimeError(f"{TITLES.get(stage, stage)}: {ve.explain(detail)}\nLog: {log_path}")
    if not Path(target).exists():
        raise RuntimeError(f"{TITLES.get(stage, stage)} reported success but wrote no file.\nLog: {log_path}")
    result = dict(state["result"])
    result["log_path"] = str(log_path)
    summary = ", ".join(f"{k} {v}" for k, v in result.items() if k in ("seconds", "faces", "cuts", "ms_per_frame", "device"))
    if summary:
        log(f"{TITLES.get(stage, stage)} done: {summary}")
    return result
