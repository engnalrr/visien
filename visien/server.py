"""Local HTTP API for the Visien window (bound to 127.0.0.1 only)."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__, media, models, package, presets, stages, ve
from .config import CONFIG, UI_DIR, ensure_dirs, output_dir
from .jobs import clear_previews, preview_file, preview_still, prune_previews, worker
from .library import LIBRARY

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    ensure_dirs()
    worker()
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title=APP_NAME, version=__version__, docs_url=None, redoc_url=None, lifespan=_lifespan)
NO_CACHE = {"Cache-Control": "no-store"}


@app.exception_handler(KeyError)
async def _missing(_request: Request, exc: KeyError):
    return JSONResponse({"detail": str(exc.args[0]) if exc.args else "Not found"}, status_code=404)


@app.exception_handler(FileNotFoundError)
async def _no_file(_request: Request, exc: FileNotFoundError):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(ValueError)
async def _bad(_request: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(ve.EngineMissing)
async def _engine(_request: Request, exc: ve.EngineMissing):
    return JSONResponse({"detail": str(exc), "engine_missing": True}, status_code=409)


@app.exception_handler(RuntimeError)
async def _runtime(_request: Request, exc: RuntimeError):
    return JSONResponse({"detail": str(exc)}, status_code=500)


# ------------------------------------------------------------------ app state


def _warm() -> None:
    try:
        if not ve.usable(CONFIG.get("ve_dir")):
            ve.scan(auto_select=True)
        if ve.status()["ok"]:
            ve.devices()
    except Exception:  # noqa: BLE001 - shown later in Settings
        pass


@app.get("/api/state")
def state():
    return {"app": APP_NAME, "version": __version__, "engine": ve.status(), "settings": CONFIG.all(),
            "release_url": ve.RELEASE_URL}


@app.get("/api/schema")
def schema():
    return stages.schema()


@app.post("/api/settings")
def update_settings(values: dict = Body(...)):
    allowed = {k: v for k, v in values.items() if k not in ("ve_dir", "port")}
    return CONFIG.update(allowed)


# ------------------------------------------------------------------ engine


@app.get("/api/engine")
def engine():
    return ve.status()


@app.post("/api/engine/scan")
def engine_scan():
    result = ve.scan(auto_select=True)
    ve.cli_version.cache_clear()
    return result | {"status": ve.status()}


@app.post("/api/engine/select")
def engine_select(body: dict = Body(...)):
    path = str(body.get("path") or "").strip().strip('"')
    if not path or not Path(path).is_dir():
        raise ValueError("Choose the folder that contains VE_CLI.exe.")
    CONFIG.update({"ve_dir": path})
    ve.cli_version.cache_clear()
    status = ve.status()
    if not status["ok"]:
        raise ValueError(status["reason"])
    return status


@app.get("/api/engine/devices")
def engine_devices(refresh: bool = False):
    return ve.devices(refresh=refresh)


@app.post("/api/engine/test")
def engine_test():
    status = ve.status()
    if not status["ok"]:
        raise ve.EngineMissing(status["reason"])
    devices = ve.devices(refresh=True)
    return {"status": status, "devices": devices.get("devices", [])}


@app.post("/api/engine/open-release")
def open_release():
    import webbrowser  # noqa: WPS433

    webbrowser.open(ve.RELEASE_URL)
    return {"ok": True}


GITHUB_REPO = "engnalrr/visien"


def _version_tuple(text: str) -> tuple:
    import re  # noqa: WPS433

    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


@app.get("/api/update")
def update_check():
    """Newest Visien release on GitHub (works when the repository is public)."""
    import json as _json  # noqa: WPS433
    import urllib.request  # noqa: WPS433

    page = f"https://github.com/{GITHUB_REPO}/releases/latest"
    try:
        request = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                         headers={"Accept": "application/vnd.github+json", "User-Agent": "Visien"})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = _json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - offline, private repository or no release yet
        return {"ok": False, "current": __version__, "url": page, "error": str(exc)[:200]}
    latest = str(data.get("tag_name") or "").lstrip("v")
    return {"ok": True, "current": __version__, "latest": latest, "url": data.get("html_url") or page,
            "newer": bool(latest) and _version_tuple(latest) > _version_tuple(__version__),
            "notes": str(data.get("body") or "")[:1500]}


@app.post("/api/update/open")
def update_open(body: dict = Body(default={})):
    import webbrowser  # noqa: WPS433

    url = str(body.get("url") or f"https://github.com/{GITHUB_REPO}/releases/latest")
    if not url.startswith(f"https://github.com/{GITHUB_REPO}/"):
        raise ValueError("Unexpected address.")
    webbrowser.open(url)
    return {"ok": True}


# ------------------------------------------------------------------ media


@app.get("/api/media")
def media_list():
    return LIBRARY.list()


@app.post("/api/media")
def media_add(body: dict = Body(...)):
    paths = [str(p) for p in body.get("paths", []) if str(p).strip()]
    if not paths:
        raise ValueError("No files given.")
    result = LIBRARY.add(paths)
    if paths:
        CONFIG.update({"last_dir": str(Path(paths[0]).parent)})
    return result | {"items": LIBRARY.list()}


@app.post("/api/media/remove")
def media_remove(body: dict = Body(...)):
    LIBRARY.remove([str(i) for i in body.get("ids", [])])
    return LIBRARY.list()


@app.get("/api/media/{item_id}/thumb")
def media_thumb(item_id: str):
    return FileResponse(LIBRARY.thumbnail(item_id), media_type="image/jpeg", headers={"Cache-Control": "max-age=600"})


@app.get("/api/media/{item_id}/frame")
def media_frame(item_id: str, t: float = 0.0, w: int | None = None):
    return Response(LIBRARY.frame(item_id, t, w), media_type="image/jpeg", headers=NO_CACHE)


@app.get("/api/media/{item_id}/file")
def media_file(item_id: str):
    info = LIBRARY.get(item_id)
    if info.kind != "image":
        raise ValueError("Only images are served directly.")
    return FileResponse(info.path, headers=NO_CACHE)


@app.post("/api/plan")
def plan(body: dict = Body(...)):
    """Output size / fps for the selected file, plus problems and warnings for the current settings."""
    media_id = body.get("media_id")
    kind = str(body.get("kind") or "video")
    settings = stages.normalize(body.get("settings") or {})
    if not media_id:
        problems = stages.validate(stages.for_kind(settings, kind), kind)
        missing = models.missing(settings, kind)
        if missing:
            problems.append(models.missing_message(missing))
        return {"plan": None, "problems": problems, "warnings": [], "missing": missing}
    info = LIBRARY.get(str(media_id))
    kind = info.kind
    skipped = stages.skipped_ve(stages.for_kind(settings, kind), kind)
    settings = stages.resolve(stages.for_kind(settings, kind), info)
    if skipped and not stages.uses_ai(settings, kind):
        return {"plan": {"ok": False}, "problems": [ve.rtx_problem()], "warnings": [], "missing": []}
    problems = stages.validate(settings, kind)
    local = stages.estimate(settings, info)
    if skipped:
        local["warnings"] = [f"Skipped on this PC (needs an NVIDIA RTX GPU): {', '.join(skipped)}. "
                             "The AI cards run."] + list(local["warnings"])
    missing = models.missing(settings, kind)
    if missing:
        problems.append(models.missing_message(missing))
    if problems:
        return {"plan": {"ok": False}, "problems": problems, "warnings": local["warnings"], "missing": missing}
    if stages.uses_ai(settings, kind) or not ve.status()["ok"]:
        return {"plan": {"ok": not local["problems"], "estimated": not stages.uses_ai(settings, kind), **local},
                "problems": local["problems"], "warnings": local["warnings"]}
    target = str(Path(ve.CACHE_DIR) / f"plan_{info.kind}.{stages.output_extension(settings, info.kind)}")
    Path(target).unlink(missing_ok=True)
    result = ve.plan(info.path, settings, target)
    if not result.get("ok"):
        return {"plan": {"ok": False}, "problems": [result.get("error") or "Visual Enhancer rejected these settings."],
                "warnings": local["warnings"]}
    warnings = list(local["warnings"])
    width, height = result.get("width") or 0, result.get("height") or 0
    codec = str(settings.get("codec", ""))
    if kind == "video" and codec.startswith("H.264") and max(width, height) > 4096 and \
            not any("4096" in w for w in warnings):
        warnings.append(f"{width}×{height} is larger than H.264 hardware encoding allows (4096 px). Use H.265 or AV1.")
    return {"plan": result, "problems": [], "warnings": warnings}


# ------------------------------------------------------------------ presets


@app.get("/api/presets")
def preset_list():
    return presets.list_presets()


@app.post("/api/presets")
def preset_save(body: dict = Body(...)):
    return presets.save(str(body.get("name", "")), body.get("settings") or {}, str(body.get("description", "")))


@app.delete("/api/presets/{preset_id}")
def preset_delete(preset_id: str):
    presets.delete(preset_id)
    return presets.list_presets()


@app.post("/api/presets/import")
def preset_import(body: dict = Body(...)):
    return presets.import_file(str(body.get("path", "")))


@app.post("/api/presets/from-ve")
def preset_from_ve(body: dict = Body(default={})):
    return presets.from_visual_enhancer(str(body.get("name", "")).strip())


@app.post("/api/presets/export")
def preset_export(body: dict = Body(...)):
    path = presets.export(body.get("id"), str(body.get("path", "")), body.get("settings"), str(body.get("name", "")))
    return {"path": path}


# ------------------------------------------------------------------ previews


@app.post("/api/preview")
def preview_request(body: dict = Body(...)):
    info = LIBRARY.get(str(body.get("media_id")))
    kind_settings = stages.for_kind(stages.normalize(body.get("settings") or {}), info.kind)
    if stages.skipped_ve(kind_settings, info.kind) and not stages.uses_ai(kind_settings, info.kind):
        raise ValueError(ve.rtx_problem())
    return worker().request_preview(str(body.get("media_id")), body.get("settings") or {},
                                    float(body.get("start", 0.0)), float(body.get("length", 3.0)),
                                    force=bool(body.get("force")))


@app.post("/api/preview/cancel")
def preview_cancel():
    worker().cancel_preview()
    return {"ok": True}


@app.get("/api/previews")
def previews_usage():
    return prune_previews()


@app.post("/api/previews/clear")
def previews_clear():
    w = worker()
    with w.lock:
        busy = w.preview is not None and w.preview.state == "rendering"
    if busy:
        raise ValueError("A preview is rendering. Wait for it or cancel it first.")
    clear_previews()
    return {"count": 0, "bytes": 0}


@app.get("/api/preview/{job_id}")
def preview_status(job_id: str):
    return worker().get_preview(job_id).to_json()


@app.get("/api/preview-files/{key}/{which}")
def preview_media(key: str, which: str):
    return FileResponse(preview_file(key, which), headers={"Cache-Control": "max-age=3600"})


@app.get("/api/preview-still/{key}/{which}")
def preview_frame(key: str, which: str, t: float = 0.0):
    return FileResponse(preview_still(key, which, t), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------------------ queue


@app.get("/api/queue")
def queue_state():
    return worker().state()


@app.post("/api/queue")
def queue_add(body: dict = Body(...)):
    ids = [str(i) for i in body.get("media_ids", [])]
    if not ids:
        raise ValueError("Select at least one file.")
    status = ve.status()
    settings = body.get("settings") or {}
    for media_id in ids:
        info = LIBRARY.get(media_id)
        kind_settings = stages.for_kind(stages.normalize(settings), info.kind)
        if kind_settings.get(f"{info.kind}_enabled_stages"):
            if not status["ok"]:
                raise ve.EngineMissing(status["reason"])
            if ve.rtx_problem() and not stages.uses_ai(kind_settings, info.kind):
                raise ValueError(ve.rtx_problem())
        problems = stages.validate(kind_settings, info.kind)
        missing = models.missing(kind_settings, info.kind)
        if missing:
            problems.append(models.missing_message(missing))
        if problems:
            raise ValueError(f"{info.name}: {problems[0]}")
    created = worker().enqueue(ids, settings, str(body.get("preset", "")), start=bool(body.get("start", True)))
    return {"created": created, **worker().state()}


@app.post("/api/queue/{action}")
def queue_action(action: str, body: dict = Body(default={})):
    w = worker()
    job_id = str(body.get("id", ""))
    if action == "start":
        w.start()
    elif action == "pause":
        w.pause()
    elif action == "stop":
        w.stop()
    elif action == "cancel":
        w.cancel(job_id)
    elif action == "retry":
        w.retry(job_id)
    elif action == "remove":
        w.remove(job_id)
    elif action == "up":
        w.move(job_id, -1)
    elif action == "down":
        w.move(job_id, 1)
    elif action == "clear":
        w.clear_finished()
    else:
        raise KeyError(f"Unknown queue action: {action}")
    return w.state()


# ------------------------------------------------------------------ AI models


@app.get("/api/models")
def models_status():
    return models.status()


@app.post("/api/models/install")
def models_install(body: dict = Body(...)):
    ids = [str(i) for i in body.get("ids", [])]
    return models.install(ids, accept_licence=bool(body.get("accept_licence")))


@app.post("/api/models/remove")
def models_remove(body: dict = Body(...)):
    return models.remove(str(body.get("id", "")))


@app.get("/api/package")
def package_status():
    return package.status()


@app.post("/api/package")
def package_start(body: dict = Body(...)):
    return package.start(str(body.get("kind", "full")), str(body.get("folder", "")))


@app.post("/api/package/cancel")
def package_cancel():
    return package.cancel()


@app.post("/api/models/check")
def models_check():
    return models.runtime_check(refresh=True)


# ------------------------------------------------------------------ files


@app.post("/api/reveal")
def reveal(body: dict = Body(...)):
    path = str(body.get("path") or "")
    if path == "@output":
        path = str(output_dir())
        Path(path).mkdir(parents=True, exist_ok=True)
    if path == "@engine":
        path = str(ve.ENGINE_DIR)
        Path(path).mkdir(parents=True, exist_ok=True)
    if not path or not Path(path).exists():
        raise FileNotFoundError(f"Not found: {path}")
    media.open_in_explorer(path)
    return {"ok": True}


@app.post("/api/client-log")
async def client_log(request: Request):
    try:
        data = await request.json()
        logging.getLogger("visien.ui").warning(str(data.get("text", ""))[:2000])
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(UI_DIR / "index.html", headers=NO_CACHE)


app.mount("/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="assets")
