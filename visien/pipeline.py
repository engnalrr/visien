"""Runs a Visien pipeline: Visual Enhancer stages and AI stages in the user's order.

Consecutive Visual Enhancer stages share one VE_CLI run. AI stages run in the AI runtime. Between steps
the picture travels as a lossless file (FFV1 video with the source audio, or PNG); the last step writes
the requested export.

Clean Shot Starts (video): the source first gets a mirrored warm-up before every shot (visien/shots.py), every
card processes that padded copy, and the warm-up frames are cut out before the export is written.
Comparison (Export): after the export, a labelled source-vs-result copy is written next to it (visien/compare.py).
"""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Callable

from . import ai_engine, compare, media, shots, stages, ve
from .config import CACHE_DIR

COST = {"seedvr2": 6.0, "rife": 2.0, "face_restore": 1.5, "color_match": 0.8}


def _cost(segment: tuple[str, list[str]]) -> float:
    engine, ids = segment
    return 2.0 if engine == "ve" else COST.get(ids[0], 2.0)


def _retrying(action: Callable[[], object], *, cancel, progress, log, retries: int, wait: float = 12.0):
    for attempt in range(retries + 1):
        try:
            return action()
        except RuntimeError as exc:
            if attempt >= retries or not ve.is_gpu_fault(str(exc)):
                raise
            pause = wait * (attempt + 1)
            log(f"GPU error, trying again in {pause:.0f} s")
            if progress:
                progress(0.0, f"GPU error - retrying in {pause:.0f} s")
            deadline = time.time() + pause
            while time.time() < deadline:
                if cancel is not None and cancel.is_set():
                    raise ve.Cancelled()
                time.sleep(0.25)
    return None


def _warmup_wanted(settings: dict, kind: str, log) -> bool:
    """Clean Shot Starts applies to videos with temporal cards (every Visual Enhancer card and SeedVR2)."""
    if kind != "video" or not settings.get("vz_shot_warmup", True):
        return False
    active = stages.active_stages(settings, kind)
    if not (settings.get("video_enabled_stages") or "seedvr2" in active):
        return False
    if "rtx_video_hdr" in active or settings.get("hdr_mode"):
        log("Clean Shot Starts is skipped for HDR output.")
        return False
    return True


def run(source: str, target: str, settings: dict, kind: str, *, name: str = "Visien",
        cancel: threading.Event | None = None, progress: Callable[[float, str], None] | None = None,
        log: Callable[[str], None] | None = None, retries: int = 1, comparison: bool = False) -> ve.RenderResult:
    log = log or (lambda _text: None)
    warm = _warmup_wanted(settings, kind, log)
    if not stages.uses_ai(settings, kind) and not warm:
        result = ve.render_retrying(source, target, settings, name=name, cancel=cancel, progress=progress, log=log,
                                    retries=retries)
        if comparison:
            _comparison(source, target, settings, kind, log)
        return result
    segments = stages.segments(settings, kind)
    if not segments:
        raise RuntimeError("Turn on at least one stage.")
    started = time.time()
    work = CACHE_DIR / f"job_{uuid.uuid4().hex[:10]}"
    work.mkdir(parents=True, exist_ok=True)
    total = sum(_cost(s) for s in segments) + (0.6 if warm else 0.0)
    done = 0.0
    current = source
    log_path = ""
    ext = "mkv" if kind == "video" else "png"
    plan = None
    try:
        if warm:
            if progress:
                progress(0.0, "Finding shots")
            info = media.probe(source)
            fps = Fraction(info.fps)
            starts = shots.detect_cuts(source, fps)
            if progress:
                progress(0.1 / total, f"Adding warm-up frames to {len(starts)} shot{'s' if len(starts) != 1 else ''}")
            padded = work / "padded.mkv"
            plan = shots.pad(source, padded, width=info.width, height=info.height, fps=fps, pix_fmt=info.pix_fmt,
                             bit_depth=info.bit_depth, starts=starts, cancel=cancel)
            log(f"Clean Shot Starts: {len(starts)} shot{'s' if len(starts) != 1 else ''}, "
                f"{plan.frames_out - plan.frames_in} warm-up frames")
            current = padded
            done += 0.4
        reference = current  # what Color Match compares with (same timeline as the processed picture)
        for index, segment in enumerate(segments):
            engine, ids = segment
            last = index == len(segments) - 1
            final_here = last and not warm
            low, high = done / total, (done + _cost(segment)) / total

            def sub(fraction: float, message: str, low=low, high=high) -> None:
                if progress:
                    progress(low + (high - low) * max(0.0, min(1.0, fraction)), message)

            if engine == "ve":
                seg_settings = stages.ve_segment_settings(settings, kind, ids)
                out = Path(target) if final_here else work / f"step{index}.{ext}"
                if not final_here:
                    seg_settings = stages.preview_settings(seg_settings, kind)
                    if last and not str(settings.get("codec", "")).startswith("FFV1"):
                        # only the export follows: ProRes HQ is visually lossless and far smaller than FFV1 RGB
                        seg_settings.update(codec="ProRes HQ", container="MOV")
                        out = work / f"step{index}.mov"
                result = _retrying(lambda: ve.render(str(current), str(out), seg_settings, name=name, cancel=cancel,
                                                     progress=sub, log=log),
                                   cancel=cancel, progress=sub, log=log, retries=retries)
                log_path = result.log_path or log_path
            else:
                stage = ids[0]
                raw = work / f"step{index}_raw.{ext}"
                stage_settings = dict(settings, _color_reference=str(reference)) if stage == "color_match" \
                    else settings

                def action(stage=stage, raw=raw, current=current, stage_settings=stage_settings):
                    raw.unlink(missing_ok=True)
                    return ai_engine.run_stage(stage, str(current), str(raw), stage_settings, kind, cancel=cancel,
                                               progress=sub, log=log)

                outcome = _retrying(action, cancel=cancel, progress=sub, log=log, retries=retries) or {}
                log_path = log_path or outcome.get("log_path", "")
                if kind == "video":
                    out = work / f"step{index}.{ext}"
                    media.mux_audio(raw, current, out)
                else:
                    out = raw
                if final_here:
                    sub(0.99, "Writing the final file")
                    media.encode_export(out, Path(target), settings, kind)
                    out = Path(target)
            current = out
            done += _cost(segment)
        if warm and plan is not None:
            if progress:
                progress(min(0.99, done / total), "Writing the final file")
            processed = media.probe(current)
            media.encode_export(Path(current), Path(target), settings, kind, audio_source=source,
                                pre_filter=shots.trim_filter(plan, Fraction(processed.fps)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if comparison:
        _comparison(source, target, settings, kind, log)
    if progress:
        progress(1.0, "Done")
    return ve.RenderResult(str(target), round(time.time() - started, 2), log_path)


def _comparison(source: str, target: str, settings: dict, kind: str, log) -> None:
    try:
        compare.make(source, target, settings, kind, log)
    except Exception as exc:  # noqa: BLE001 - the render itself succeeded
        log(f"Comparison copy failed: {exc}")
