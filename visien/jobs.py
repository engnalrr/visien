"""Render queue and preview worker.

Renders run one at a time in the order of the queue. Previews have their own
worker so a long export never blocks trying settings on a short excerpt; a new
preview request replaces any preview still waiting or running.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import media, models, pipeline, stages, ve
from .config import CONFIG, DATA_DIR, PREVIEW_DIR, output_dir
from .library import LIBRARY

QUEUE_PATH = DATA_DIR / "queue.json"
FINISHED = {"done", "failed", "cancelled"}


@dataclass
class Job:
    id: str
    kind: str                      # render | preview
    media_id: str
    name: str
    source: str
    media_kind: str
    settings: dict
    preset: str = ""
    target: str = ""
    state: str = "pending"         # pending | rendering | done | failed | cancelled
    progress: float = 0.0
    message: str = "Waiting"
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    output: str = ""
    log_path: str = ""
    # previews
    start: float = 0.0
    length: float = 0.0
    key: str = ""
    result: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        data = asdict(self)
        data.pop("settings")
        now = time.time()
        elapsed = (self.finished or now) - self.started if self.started else 0.0
        data["elapsed"] = round(elapsed, 1)
        data["eta"] = round(elapsed * (1 - self.progress) / self.progress, 0) \
            if self.state == "rendering" and self.progress > 0.02 else None
        return data


class Worker:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.renders: list[Job] = []
        self.preview: Job | None = None
        self.previews: dict[str, Job] = {}
        self.running = False
        self._current: Job | None = None
        self._cancel_render = threading.Event()
        self._cancel_preview = threading.Event()
        self._render_wake = threading.Event()
        self._preview_wake = threading.Event()
        self._log: list[str] = []
        self._load()
        threading.Thread(target=self._render_loop, name="visien-render", daemon=True).start()
        threading.Thread(target=self._preview_loop, name="visien-preview", daemon=True).start()

    # ------------------------------------------------------------ persistence

    def _load(self) -> None:
        try:
            stored = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for raw in stored if isinstance(stored, list) else []:
            try:
                job = Job(**raw)
            except TypeError:
                continue
            if job.state == "rendering":
                job.state, job.error, job.message = "failed", "Visien was closed during this render.", "Interrupted"
            self.renders.append(job)

    def _save(self) -> None:
        with self.lock:
            data = [asdict(job) for job in self.renders]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(QUEUE_PATH)

    def log(self, text: str) -> None:
        line = time.strftime("%H:%M:%S ") + text
        with self.lock:
            self._log.append(line)
            del self._log[:-400]

    # ------------------------------------------------------------ state

    def state(self) -> dict:
        with self.lock:
            renders = [job.to_json() for job in self.renders]
            preview = self.preview.to_json() if self.preview else None
            log = self._log[-120:]
        pending = sum(1 for job in renders if job["state"] == "pending")
        active = next((job for job in renders if job["state"] == "rendering"), None)
        return {"running": self.running, "pending": pending, "active": active["id"] if active else None,
                "jobs": renders, "preview": preview, "log": log}

    def _find(self, job_id: str) -> Job:
        with self.lock:
            for job in self.renders:
                if job.id == job_id:
                    return job
        raise KeyError("Queue item not found.")

    # ------------------------------------------------------------ render queue

    def enqueue(self, media_ids: list[str], settings: dict, preset: str, start: bool = True) -> list[str]:
        settings = stages.normalize(settings)
        created = []
        with self.lock:
            for media_id in media_ids:
                info = LIBRARY.get(media_id)
                job = Job(id=uuid.uuid4().hex[:10], kind="render", media_id=media_id, name=info.name,
                          source=info.path, media_kind=info.kind,
                          settings=stages.resolve(stages.for_kind(settings, info.kind), info), preset=preset)
                self.renders.append(job)
                created.append(job.id)
            if start:
                self.running = True
        self._save()
        self._render_wake.set()
        return created

    def start(self) -> None:
        with self.lock:
            self.running = True
        self._render_wake.set()

    def pause(self) -> None:
        with self.lock:
            self.running = False

    def stop(self) -> None:
        """Pause the queue and cancel the item that is rendering now."""
        with self.lock:
            self.running = False
            if self._current is not None:
                self._cancel_render.set()

    def cancel(self, job_id: str) -> None:
        job = self._find(job_id)
        with self.lock:
            if job.state == "rendering":
                self._cancel_render.set()
            elif job.state == "pending":
                job.state, job.message, job.finished = "cancelled", "Cancelled", time.time()
        self._save()

    def retry(self, job_id: str) -> None:
        job = self._find(job_id)
        with self.lock:
            if job.state in FINISHED:
                job.state, job.progress, job.message, job.error = "pending", 0.0, "Waiting", ""
                job.started = job.finished = 0.0
                job.output = job.target = ""
                self.running = True
        self._save()
        self._render_wake.set()

    def remove(self, job_id: str) -> None:
        job = self._find(job_id)
        with self.lock:
            if job.state == "rendering":
                raise ValueError("Stop this item before removing it.")
            self.renders.remove(job)
        self._save()

    def move(self, job_id: str, offset: int) -> None:
        job = self._find(job_id)
        with self.lock:
            index = self.renders.index(job)
            target = max(0, min(len(self.renders) - 1, index + offset))
            self.renders.insert(target, self.renders.pop(index))
        self._save()

    def clear_finished(self) -> None:
        with self.lock:
            self.renders = [job for job in self.renders if job.state not in FINISHED]
        self._save()

    def _next_render(self) -> Job | None:
        with self.lock:
            if not self.running:
                return None
            for job in self.renders:
                if job.state == "pending":
                    job.state, job.started, job.message = "rendering", time.time(), "Starting"
                    self._current = job
                    self._cancel_render.clear()
                    return job
            self.running = False
        return None

    def _render_loop(self) -> None:
        while True:
            job = self._next_render()
            if job is None:
                self._render_wake.wait(1.0)
                self._render_wake.clear()
                continue
            self._save()
            try:
                self._render(job)
                job.state, job.progress, job.message = "done", 1.0, "Done"
                self.log(f"Done: {job.name} → {job.output}")
            except ve.Cancelled:
                job.state, job.message = "cancelled", "Cancelled"
                self.log(f"Cancelled: {job.name}")
            except Exception as exc:  # noqa: BLE001 - shown on the queue item
                job.state, job.message, job.error = "failed", "Failed", str(exc) or exc.__class__.__name__
                self.log(f"Failed: {job.name}: {job.error}")
                if not isinstance(exc, (RuntimeError, ve.EngineMissing, FileNotFoundError)):
                    self.log(traceback.format_exc(limit=4))
            finally:
                job.finished = time.time()
                if job.state in ("failed", "cancelled") and job.target and not job.output:
                    # Visien chose a name that did not exist before, so anything there now is a partial file.
                    try:
                        Path(job.target).unlink(missing_ok=True)
                    except OSError:
                        pass
                with self.lock:
                    self._current = None
                self._save()

    def _target_for(self, job: Job) -> Path:
        source = Path(job.source)
        folder = output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        suffix = CONFIG.get("suffix") if CONFIG.get("naming") == "suffix" else ""
        stem = source.stem + (suffix or "")
        extension = stages.output_extension(job.settings, job.media_kind)
        with self.lock:
            reserved = {Path(other.target).name.lower() for other in self.renders
                        if other is not job and other.target and other.state in ("pending", "rendering")}
        candidate = folder / f"{stem}.{extension}"
        number = 2
        while candidate.exists() or candidate.name.lower() in reserved or \
                candidate.resolve() == source.resolve():
            candidate = folder / f"{stem}_{number}.{extension}"
            number += 1
        return candidate

    def _render(self, job: Job) -> None:
        if not Path(job.source).is_file():
            raise FileNotFoundError(f"Source file not found: {job.source}")
        target = self._target_for(job)
        job.target = str(target)
        self.log(f"Render: {job.name} ({job.preset or 'custom settings'})")

        def progress(fraction: float, message: str) -> None:
            job.progress, job.message = min(fraction, 0.999), message or "Rendering"

        missing = models.missing(job.settings, job.media_kind)
        if missing:
            raise RuntimeError(models.missing_message(missing))
        result = pipeline.run(job.source, str(target), job.settings, job.media_kind, name=job.preset or "Visien",
                              retries=2, cancel=self._cancel_render, progress=progress, log=self.log,
                              comparison=str(job.settings.get("vz_compare") or "off") != "off")
        job.output, job.log_path = result.output, result.log_path

    # ------------------------------------------------------------ previews

    def request_preview(self, media_id: str, settings: dict, start: float, length: float,
                        force: bool = False) -> dict:
        info = LIBRARY.get(media_id)
        settings = stages.resolve(stages.for_kind(stages.normalize(settings), info.kind), info)
        if info.kind == "video":
            length = max(0.2, min(float(length), 30.0))
            start = max(0.0, min(float(start), max(0.0, info.duration - length)))
            length = min(length, max(0.2, info.duration - start)) if info.duration else length
        else:
            start, length = 0.0, 0.0
        key = preview_key(info, settings, start, length)
        cached = None if force else load_preview(key)
        job = Job(id=uuid.uuid4().hex[:10], kind="preview", media_id=media_id, name=info.name, source=info.path,
                  media_kind=info.kind, settings=settings, start=start, length=length, key=key)
        if cached:
            job.state, job.progress, job.message, job.result = "done", 1.0, "Ready (cached)", cached
            job.started = job.finished = time.time()
        with self.lock:
            previous = self.preview
            if previous is not None and previous.state == "rendering" and previous.key != key:
                self._cancel_preview.set()
            if previous is not None and previous.state == "rendering" and previous.key == key and not cached:
                return previous.to_json()
            self.preview = job
            self.previews[job.id] = job
            if len(self.previews) > 50:
                for old in list(self.previews)[:-50]:
                    self.previews.pop(old, None)
        self._preview_wake.set()
        return job.to_json()

    def cancel_preview(self) -> None:
        with self.lock:
            if self.preview is not None:
                if self.preview.state == "rendering":
                    self._cancel_preview.set()
                elif self.preview.state == "pending":
                    self.preview.state, self.preview.message = "cancelled", "Cancelled"

    def get_preview(self, job_id: str) -> Job:
        with self.lock:
            job = self.previews.get(job_id)
        if job is None:
            raise KeyError("Preview not found.")
        return job

    def _preview_loop(self) -> None:
        while True:
            with self.lock:
                job = self.preview if self.preview is not None and self.preview.state == "pending" else None
                if job is not None:
                    job.state, job.started, job.message = "rendering", time.time(), "Preparing"
                    self._cancel_preview.clear()
            if job is None:
                self._preview_wake.wait(1.0)
                self._preview_wake.clear()
                continue
            try:
                job.result = build_preview(job, self._cancel_preview, self.log)
                job.state, job.progress, job.message = "done", 1.0, "Ready"
            except ve.Cancelled:
                job.state, job.message = "cancelled", "Cancelled"
            except Exception as exc:  # noqa: BLE001
                job.state, job.message, job.error = "failed", "Failed", str(exc) or exc.__class__.__name__
                self.log(f"Preview failed: {job.error}")
            finally:
                job.finished = time.time()
                prune_previews(job.key)


# ---------------------------------------------------------------- preview files


def preview_key(info: media.MediaInfo, settings: dict, start: float, length: float) -> str:
    stat = Path(info.path).stat()
    payload = json.dumps({"path": info.path, "size": stat.st_size, "mtime": int(stat.st_mtime),
                          "start": round(start, 3), "length": round(length, 3), "settings": settings,
                          "engine": ve.status().get("version", "")}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def load_preview(key: str) -> dict | None:
    meta = PREVIEW_DIR / key / "meta.json"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if all((PREVIEW_DIR / key / name).exists() for name in data.get("files", {}).values()):
        (PREVIEW_DIR / key).touch()
        return data
    return None


def build_preview(job: Job, cancel: threading.Event, log) -> dict:
    folder = PREVIEW_DIR / job.key
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    info = LIBRARY.get(job.media_id)
    settings = stages.preview_settings(job.settings, info.kind)
    missing = models.missing(settings, info.kind)
    if missing:
        raise RuntimeError(models.missing_message(missing))
    started = time.time()

    def progress(low: float, high: float):
        def update(fraction: float, message: str) -> None:
            job.progress = low + (high - low) * fraction
            job.message = message or "Rendering"
        return update

    if info.kind == "image":
        job.message = "Visual Enhancer"
        out = folder / "out.png"
        pipeline.run(info.path, str(out), settings, "image", name="Visien preview", cancel=cancel,
                  progress=progress(0.02, 0.95), log=log)
        out_info = media.probe(out)
        source = media.browser_image(info.path, folder / "src.png")
        converted = source.parent == folder
        files = {"output": out.name}
        if converted:
            files["source"] = source.name
        meta = {"kind": "image", "files": files, "source_path": "" if converted else str(source),
                "source": {"width": info.width, "height": info.height},
                "output": {"width": out_info.width, "height": out_info.height}}
    else:
        job.message = "Cutting excerpt"
        segment = media.cut_segment(info, job.start, job.length, folder / "src.mkv")
        if cancel.is_set():
            raise ve.Cancelled()
        job.progress = 0.05
        out = folder / "out.mkv"
        pipeline.run(str(segment), str(out), settings, "video", name="Visien preview", cancel=cancel,
                  progress=progress(0.05, 0.86), log=log)
        out_info = media.probe(out)
        job.message, job.progress = "Preparing players", 0.88
        media.make_proxy(segment, folder / "src.mp4", hdr=info.hdr)
        job.progress = 0.94
        media.make_proxy(out, folder / "out.mp4", hdr=out_info.hdr)
        meta = {"kind": "video", "files": {"source": "src.mp4", "output": "out.mp4",
                                           "source_full": "src.mkv", "output_full": "out.mkv"},
                "source": {"width": info.width, "height": info.height, "fps": info.fps_value,
                           "frames": int(round(job.length * info.fps_value)), "hdr": info.hdr},
                "output": {"width": out_info.width, "height": out_info.height, "fps": out_info.fps_value,
                           "frames": out_info.frames, "hdr": out_info.hdr}}
    meta.update(start=job.start, length=job.length, seconds=round(time.time() - started, 1),
                created=time.time(), media_id=job.media_id)
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    log(f"Preview ready in {meta['seconds']} s: {info.name}")
    return meta


def preview_file(key: str, which: str) -> Path:
    meta = load_preview(key)
    if not meta:
        raise KeyError("Preview expired. Run it again.")
    if which == "source" and meta.get("source_path"):
        return Path(meta["source_path"])
    name = meta["files"].get(which)
    if not name:
        raise KeyError(f"No {which} file in this preview.")
    return PREVIEW_DIR / key / name


def preview_still(key: str, which: str, seconds: float) -> Path:
    """Lossless full-resolution frame from a video preview (pixel peeping)."""
    meta = load_preview(key)
    if not meta:
        raise KeyError("Preview expired. Run it again.")
    if meta["kind"] == "image":
        return preview_file(key, which)
    source = PREVIEW_DIR / key / meta["files"][f"{which}_full"]
    fps = meta[which].get("fps") or 24.0
    frame = int(round(max(0.0, seconds) * fps))
    target = PREVIEW_DIR / key / f"still_{which}_{frame}.png"
    if not target.exists():
        media.extract_png(str(source), frame / fps, target, hdr=bool(meta[which].get("hdr")))
    return target


def _folder_size(folder: Path) -> int:
    total = 0
    for item in folder.iterdir():
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def prune_previews(keep_key: str = "") -> dict:
    """Keep the newest previews within the count and size limits from Settings."""
    keep = max(3, int(CONFIG.get("keep_previews") or 12))
    limit = max(1.0, float(CONFIG.get("preview_cache_gb") or 10)) * 1024 ** 3
    try:
        folders = sorted((p for p in PREVIEW_DIR.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime,
                         reverse=True)
    except OSError:
        return {"count": 0, "bytes": 0}
    total, kept = 0, 0
    for index, folder in enumerate(folders):
        size = _folder_size(folder)
        if index == 0 or folder.name == keep_key or (kept < keep and total + size <= limit):
            total += size
            kept += 1
        else:
            shutil.rmtree(folder, ignore_errors=True)
    return {"count": kept, "bytes": total}


def clear_previews() -> None:
    for folder in PREVIEW_DIR.glob("*"):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


WORKER: Worker | None = None


def worker() -> Worker:
    global WORKER
    if WORKER is None:
        WORKER = Worker()
    return WORKER
