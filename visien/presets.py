"""Presets in Visual Enhancer's own JSON format, so they open in Visual Enhancer too.

Built-in presets live in <app>/presets, user presets in <data>/presets. Visien
keeps its description in an extra top-level "visien" object, which Visual
Enhancer ignores.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from . import stages, ve
from .config import BUILTIN_PRESETS_DIR, USER_PRESETS_DIR

_lock = threading.Lock()


def _slug(name: str) -> str:
    slug = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip().replace(" ", "_")
    return slug[:80] or "preset"


def _read(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("format") != ve.PRESET_FORMAT or not isinstance(doc.get("settings"), dict):
        return None
    return doc


def _entry(doc: dict, path: Path, builtin: bool) -> dict:
    extra = doc.get("visien") if isinstance(doc.get("visien"), dict) else {}
    settings = stages.normalize(doc["settings"])
    ai = [stages.STAGE_BY_ID[s]["short"] for s in stages.AI_IDS
          if s in set(settings.get("vz_video_ai") or []) | set(settings.get("vz_image_ai") or [])]
    return {"id": ("builtin:" if builtin else "user:") + path.stem, "name": doc.get("name") or path.stem,
            "builtin": builtin, "description": extra.get("description", ""), "order": extra.get("order", 100),
            "group": extra.get("group", "Visien presets" if builtin else ""), "ai": ai,
            "settings": settings, "file": str(path)}


def list_presets() -> list[dict]:
    result = []
    for folder, builtin in ((BUILTIN_PRESETS_DIR, True), (USER_PRESETS_DIR, False)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            doc = _read(path)
            if doc is not None:
                result.append(_entry(doc, path, builtin))
    result.sort(key=lambda e: (not e["builtin"], e["order"], e["name"].lower()))
    return result


def get(preset_id: str) -> dict:
    for entry in list_presets():
        if entry["id"] == preset_id:
            return entry
    raise KeyError("Preset not found.")


def document(name: str, settings: dict, description: str = "") -> dict:
    doc = ve.preset_document(stages.normalize(settings), name)
    if description:
        doc["visien"] = {"description": description}
    return doc


def save(name: str, settings: dict, description: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the preset a name.")
    for entry in list_presets():
        if entry["builtin"] and entry["name"].lower() == name.lower():
            raise ValueError("A built-in preset already has this name. Choose another one.")
    USER_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = USER_PRESETS_DIR / f"{_slug(name)}.json"
    with _lock:
        path.write_text(json.dumps(document(name, settings, description), indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return _entry(_read(path), path, False)


def delete(preset_id: str) -> None:
    entry = get(preset_id)
    if entry["builtin"]:
        raise ValueError("Built-in presets cannot be deleted.")
    Path(entry["file"]).unlink(missing_ok=True)


def import_file(path: str) -> dict:
    source = Path(path)
    doc = _read(source)
    if doc is None:
        raise ValueError("This is not a Visual Enhancer preset (.json exported from Visual Enhancer or Visien).")
    schema = int(doc.get("schema_version") or 0)
    if schema > ve.PRESET_SCHEMA:
        raise ValueError(f"This preset was made with a newer Visual Enhancer (schema {schema}). "
                         "Update Visien or re-export it from your Visual Enhancer version.")
    name = doc.get("name") or source.stem
    extra = doc.get("visien") if isinstance(doc.get("visien"), dict) else {}
    return save(name, doc["settings"], extra.get("description", "Imported preset"))


def ve_config_path() -> Path:
    """Where Visual Enhancer keeps its current settings (QStandardPaths::AppConfigLocation)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Merserk" / "Visual Enhancer" / "config.ini"


def from_visual_enhancer(save_as: str = "") -> dict:
    """The settings Visual Enhancer has right now (its last session), as settings or a saved preset."""
    path = ve_config_path()
    if not path.is_file():
        raise FileNotFoundError("Visual Enhancer has no saved settings yet. Open Visual Enhancer once, set it up, "
                                "close it, then try again.")
    settings = stages.from_ve_config(path.read_text(encoding="utf-8", errors="replace"))
    if save_as:
        return save(save_as, settings, "Copied from Visual Enhancer's current settings.")
    return {"settings": settings, "file": str(path)}


def export(preset_id: str | None, path: str, settings: dict | None = None, name: str = "") -> str:
    if preset_id:
        entry = get(preset_id)
        doc = document(entry["name"], entry["settings"], entry["description"])
    else:
        doc = document(name or "Visien", settings or {})
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(target)
