"""Comparison copies: the source and the result in one labelled video or image.

Export › Comparison writes, next to the result, `<name>_compare.mp4` (or `.png` for images) with the source on
top (or left) and the result below (or right). The source is scaled to the result's size and, for video, to its
frame rate, so both halves stay frame-accurate even after frame generation. The source audio is kept.
"""

from __future__ import annotations

import os
import tempfile
from fractions import Fraction
from pathlib import Path

from . import media
from .config import CACHE_DIR, find_tool

MAX_FIT = 1920          # "Fit 1080p": each half at most this many pixels on its long side
H264_LIMIT = 4096       # larger comparisons are written as H.265


def find_font() -> str:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for path in (windows / "segoeuib.ttf", windows / "seguisb.ttf", windows / "arialbd.ttf", windows / "arial.ttf",
                 Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                 Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")):
        if path.is_file():
            return str(path)
    return ""


def _escape(path: str) -> str:
    """A file path as a drawtext option value."""
    return "'" + path.replace("\\", "/").replace(":", "\\:").replace("'", "") + "'"


def _even(value: float) -> int:
    number = max(2, int(round(value)))
    return number - number % 2


def target_for(output: str | Path, kind: str) -> Path:
    output = Path(output)
    return output.with_name(f"{output.stem}_compare{'.mp4' if kind == 'video' else '.png'}")


def make(source: str, output: str, settings: dict, kind: str, log=None) -> Path | None:
    layout = str(settings.get("vz_compare") or "off")
    if layout not in ("stack", "side"):
        return None
    log = log or (lambda _text: None)
    out_info, src_info = media.probe(output), media.probe(source)
    width, height = out_info.width, out_info.height
    if str(settings.get("vz_compare_size") or "fit") == "fit":
        factor = min(1.0, MAX_FIT / max(width, height))
        width, height = width * factor, height * factor
    width, height = _even(width), _even(height)
    font = find_font()
    size = max(14, round(min(width, height) * 0.042))
    margin = round(size * 0.75)
    before = (str(settings.get("vz_compare_before") or "RAW").strip() or "RAW")[:60]
    after = (str(settings.get("vz_compare_after") or "NEURAL ENHANCED").strip() or "NEURAL ENHANCED")[:60]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    texts = []
    for label in (before, after):
        handle = tempfile.NamedTemporaryFile("w", suffix=".txt", dir=CACHE_DIR, delete=False, encoding="utf-8")
        handle.write(label)
        handle.close()
        texts.append(handle.name)

    def label(index: int) -> str:
        font_opt = f"fontfile={_escape(font)}:" if font else ""
        return (f"drawtext={font_opt}textfile={_escape(texts[index])}:expansion=none:fontsize={size}:"
                f"fontcolor=white:x={margin}:y={margin}:box=1:boxcolor=black@0.55:boxborderw={round(size * 0.45)}")

    fit = (f"scale={width}:{height}:flags=lanczos:force_original_aspect_ratio=decrease,"
           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    rate = ""
    if kind == "video":
        fps = Fraction(out_info.fps)
        rate = f"fps={fps.numerator}/{fps.denominator},"
    tone_src = media.TONEMAP if src_info.hdr else ""
    tone_out = media.TONEMAP if out_info.hdr else ""
    line = ("drawbox=x=0:y=ih-2:w=iw:h=2:color=white@0.45:t=fill" if layout == "stack"
            else "drawbox=x=iw-2:y=0:w=2:h=ih:color=white@0.45:t=fill")
    stack = "vstack=inputs=2" if layout == "stack" else "hstack=inputs=2"
    graph = (f"[1:v]{rate}{tone_src}{fit},format=yuv444p,{label(0)},{line}[a];"
             f"[0:v]{tone_out}{fit},format=yuv444p,{label(1)}[b];"
             f"[a][b]{stack},format=yuv420p[v]")
    target = target_for(output, kind)
    ffmpeg = find_tool("ffmpeg")
    if kind == "video":
        total_w = width if layout == "stack" else width * 2
        total_h = height * 2 if layout == "stack" else height
        codec = "H.264" if max(total_w, total_h) <= H264_LIMIT else "H.265"
        video = media._video_codec_args({"codec": codec, "quality": "Best"})  # noqa: SLF001
        if "-pix_fmt" in video:
            video[video.index("-pix_fmt") + 1] = "yuv420p"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(output), "-i", str(source),
               "-filter_complex", graph, "-map", "[v]", "-map", "1:a:0?", *video, "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", str(target)]
    else:
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(output), "-i", str(source),
               "-filter_complex", graph.replace(",format=yuv420p[v]", ",format=rgb24[v]"), "-map", "[v]",
               "-frames:v", "1", str(target)]
    try:
        result = media.run(cmd, timeout=6 * 3600)
    finally:
        for name in texts:
            Path(name).unlink(missing_ok=True)
    if result.returncode != 0 or not target.exists():
        raise RuntimeError("Could not write the comparison copy: " + result.stderr.decode("utf-8", "replace")[-400:])
    log(f"Comparison copy: {target}")
    return target
