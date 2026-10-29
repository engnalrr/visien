"""The media list: files the user added, their probe data and thumbnails."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from . import media
from .config import DATA_DIR, THUMB_DIR

LIBRARY_PATH = DATA_DIR / "library.json"


def media_id(path: str) -> str:
    return hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:12]


class Library:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}
        try:
            stored = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
            for entry in stored if isinstance(stored, list) else []:
                if isinstance(entry, dict) and entry.get("id") and entry.get("info"):
                    self._items[entry["id"]] = entry
        except (OSError, ValueError):
            pass

    # -------------------------------------------------------------- persistence

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LIBRARY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self._items.values()), ensure_ascii=False), encoding="utf-8")
        tmp.replace(LIBRARY_PATH)

    # -------------------------------------------------------------- queries

    def list(self) -> list[dict]:
        with self._lock:
            items = sorted(self._items.values(), key=lambda e: e["added"])
        result = []
        for entry in items:
            item = dict(entry["info"])
            item.update(id=entry["id"], added=entry["added"], missing=not Path(item["path"]).is_file())
            result.append(item)
        return result

    def get(self, item_id: str) -> media.MediaInfo:
        with self._lock:
            entry = self._items.get(item_id)
        if entry is None:
            raise KeyError("This file is no longer in the media list.")
        info = media.MediaInfo(**entry["info"])
        path = Path(info.path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {info.path}")
        stat = path.stat()
        if stat.st_size != info.size or abs(stat.st_mtime - entry.get("mtime", stat.st_mtime)) > 1:
            info = self._refresh(item_id, path)
        return info

    def _refresh(self, item_id: str, path: Path) -> media.MediaInfo:
        info = media.probe(path)
        with self._lock:
            entry = self._items.get(item_id)
            if entry is not None:
                entry["info"] = info.to_json()
                entry["mtime"] = path.stat().st_mtime
                self._save()
        thumb = THUMB_DIR / f"{item_id}.jpg"
        thumb.unlink(missing_ok=True)
        return info

    # -------------------------------------------------------------- changes

    def add(self, paths: list[str]) -> dict:
        added, skipped = [], []
        files: list[Path] = []
        for raw in paths:
            path = Path(str(raw).strip().strip('"'))
            if path.is_dir():
                files.extend(sorted(p for p in path.iterdir() if p.is_file() and media.media_kind(p)))
            else:
                files.append(path)
        for path in files:
            try:
                info = media.probe(path)
            except Exception as exc:  # noqa: BLE001 - reported per file
                skipped.append({"path": str(path), "error": str(exc)})
                continue
            item_id = media_id(str(path))
            with self._lock:
                existing = self._items.get(item_id)
                self._items[item_id] = {"id": item_id, "info": info.to_json(), "mtime": path.stat().st_mtime,
                                        "added": existing["added"] if existing else time.time()}
            added.append(item_id)
        with self._lock:
            self._save()
        return {"added": added, "skipped": skipped}

    def remove(self, ids: list[str]) -> None:
        with self._lock:
            for item_id in ids:
                self._items.pop(item_id, None)
                (THUMB_DIR / f"{item_id}.jpg").unlink(missing_ok=True)
            self._save()

    def clear(self) -> None:
        self.remove(list(self._items))

    # -------------------------------------------------------------- pictures

    def thumbnail(self, item_id: str) -> Path:
        target = THUMB_DIR / f"{item_id}.jpg"
        if target.is_file():
            return target
        info = self.get(item_id)
        at = min(1.0, info.duration * 0.1) if info.kind == "video" else 0.0
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(media.grab_jpeg(info.path, at, width=360, quality=4))
        return target

    def frame(self, item_id: str, seconds: float, width: int | None) -> bytes:
        info = self.get(item_id)
        seconds = max(0.0, min(seconds, max(0.0, info.duration - 0.05))) if info.kind == "video" else 0.0
        return media.grab_jpeg(info.path, seconds, width=width, quality=2)


LIBRARY = Library()
