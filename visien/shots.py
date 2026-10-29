"""Clean shot starts for multi-shot videos.

Temporal models (DLSS 5 Neural Rendering, DLSS Super Resolution / Ray Reconstruction, RTX Video, SeedVR2) build
their result from the frames before the current one. At the first frame of the clip and right after every cut
they have nothing to work from, so the first 1-3 frames of each shot come out with different colours and detail,
as if they had not been processed.

Visien gives every shot a short run-up: before the first frame of a shot it inserts the shot's next frames in
reverse (a mirrored "pre-roll", so motion stays continuous), lets every card process that longer video, and then
cuts the pre-roll out again. Each shot's real frames therefore start with the models already settled. The audio
is taken from the source at the end, so it stays in sync.

Cuts are found with ffmpeg's scene detection (scdet); a false cut only costs a few extra frames.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .config import find_tool

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WARMUP_FRAMES = 8
CUT_SCORE = 10.0       # scdet score (0-100); hard cuts in AI multi-shot clips score 15-40
MIN_SHOT = 4           # frames; closer "cuts" are flashes or fast motion

# raw frame size in bytes for the pixel formats ffmpeg can pass through unchanged
_420 = ("yuv420p", "yuvj420p")
_422 = ("yuv422p", "yuvj422p")
_444 = ("yuv444p", "yuvj444p", "gbrp", "rgb24", "bgr24")
_DEEP_420 = ("yuv420p10le", "yuv420p12le", "yuv420p16le")
_DEEP_422 = ("yuv422p10le", "yuv422p12le", "yuv422p16le")
_DEEP_444 = ("yuv444p10le", "yuv444p12le", "yuv444p16le", "gbrp10le", "gbrp12le", "gbrp16le", "rgb48le")


def frame_bytes(pix_fmt: str, width: int, height: int) -> int | None:
    cw, ch = math.ceil(width / 2), math.ceil(height / 2)
    if pix_fmt in _420:
        return width * height + 2 * cw * ch
    if pix_fmt in _422:
        return width * height + 2 * cw * height
    if pix_fmt in _444:
        return 3 * width * height
    if pix_fmt in _DEEP_420:
        return 2 * (width * height + 2 * cw * ch)
    if pix_fmt in _DEEP_422:
        return 2 * (width * height + 2 * cw * height)
    if pix_fmt in _DEEP_444:
        return 6 * width * height
    return None


def raw_format(pix_fmt: str, bit_depth: int) -> str:
    """A format the frames can travel in without loss (the source's own one when possible)."""
    if frame_bytes(pix_fmt, 2, 2) is not None:
        return pix_fmt
    if pix_fmt in ("nv12", "nv21"):
        return "yuv420p"
    if pix_fmt in ("p010le", "p010be", "p016le"):
        return "yuv420p16le"
    return "yuv444p16le" if bit_depth > 8 else "yuv444p"


@dataclass
class Plan:
    """Where the pre-rolls are in the padded video (seconds), and how the padded video was made."""

    starts: list[int]
    intervals: list[tuple[float, float]] = field(default_factory=list)
    frames_in: int = 0
    frames_out: int = 0
    fps: Fraction = Fraction(24)

    @property
    def shots(self) -> int:
        return len(self.starts)


def detect_cuts(path: str, fps: Fraction, *, score: float = CUT_SCORE) -> list[int]:
    """Frame indices where a new shot starts (always includes 0)."""
    vf = f"fps={fps.numerator}/{fps.denominator},scale=320:-2:flags=area,scdet=threshold={score:g}"
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path), "-map", "0:v:0", "-an", "-vf", vf,
           "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, timeout=3600, creationflags=NO_WINDOW)
    text = result.stderr.decode("utf-8", "replace")
    starts = [0]
    for match in re.finditer(r"lavfi\.scd\.time:\s*([0-9.]+)", text):
        index = int(round(float(match.group(1)) * fps))
        if index - starts[-1] >= MIN_SHOT:
            starts.append(index)
    return starts


def _probe_colour(path: str) -> list[str]:
    """Colour tags of the source, so the padded copy is read exactly like the original.

    Visual Enhancer reads the transfer and primaries tags: an untagged copy comes out darker and cooler. Raw frames
    carry no tags, so they are set on the frames (setparams) as well as on the stream.
    """
    out = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=color_range,color_space,color_primaries,color_transfer", "-of",
                          "default=nw=1", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    tags = {k.strip(): v.strip() for k, v in (line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)}
    args, params = [], []
    for key, option, param in (("color_range", "-color_range", "range"), ("color_space", "-colorspace", "colorspace"),
                               ("color_primaries", "-color_primaries", "color_primaries"),
                               ("color_transfer", "-color_trc", "color_trc")):
        value = tags.get(key, "")
        if value and value not in ("unknown", "reserved"):
            args += [option, value]
            params.append(f"{param}={value}")
    return (["-vf", "setparams=" + ":".join(params)] if params else []) + args


def pad(source: str, target: Path, *, width: int, height: int, fps: Fraction, pix_fmt: str, bit_depth: int,
        starts: list[int], warmup: int = WARMUP_FRAMES, cancel=None) -> Plan:
    """Writes `target` (lossless FFV1, no audio) with a mirrored pre-roll before every shot start."""
    fmt = raw_format(pix_fmt, bit_depth)
    size = frame_bytes(fmt, width, height)
    if not size:
        raise RuntimeError(f"Clean Shot Starts: unsupported pixel format {pix_fmt}.")
    rate = f"{fps.numerator}/{fps.denominator}"
    ffmpeg = find_tool("ffmpeg")
    decoder = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source),
                                "-map", "0:v:0", "-an", "-vf", f"fps={rate}", "-f", "rawvideo", "-pix_fmt", fmt, "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    encoder = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "rawvideo",
                                "-pix_fmt", fmt, "-s", f"{width}x{height}", "-r", rate, "-i", "-",
                                "-c:v", "ffv1", "-level", "3", "-g", "1", "-slices", "12", "-threads", "0",
                                *_probe_colour(source), str(target)],
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    plan = Plan(starts=list(starts), fps=fps)
    pending = set(starts)
    written = index = 0
    ahead: list[bytes] = []

    def read() -> bytes | None:
        if ahead:
            return ahead.pop(0)
        data = decoder.stdout.read(size)
        return data if data and len(data) == size else None

    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Cancelled.")
            frame = read()
            if frame is None:
                break
            if index in pending:
                # look ahead inside this shot, then write those frames mirrored as the pre-roll
                nxt = min([s for s in starts if s > index] or [math.inf])
                look = [frame]
                while len(look) <= warmup and index + len(look) < nxt:
                    data = decoder.stdout.read(size)
                    if not data or len(data) < size:
                        break
                    look.append(data)
                pre = list(reversed(look[1:])) or [frame] * min(2, warmup)
                begin = written
                for data in pre:
                    encoder.stdin.write(data)
                written += len(pre)
                plan.intervals.append((float(begin / fps), float(written / fps)))
                ahead = look[1:] + ahead
            encoder.stdin.write(frame)
            written += 1
            index += 1
    finally:
        decoder.stdout.close()
        decoder.kill()
        decoder.wait()
        encoder.stdin.close()
        err = encoder.stderr.read().decode("utf-8", "replace")
        code = encoder.wait()
    if code != 0:
        raise RuntimeError("Clean Shot Starts: could not write the padded copy: " + err[-300:])
    plan.frames_in, plan.frames_out = index, written
    return plan


def trim_filter(plan: Plan, fps_out: Fraction) -> str:
    """ffmpeg filter that removes the pre-rolls from a processed padded video at any frame rate."""
    half = 0.5 / float(fps_out)
    terms = "+".join(f"gte(t\\,{a - half:.6f})*lt(t\\,{b - half:.6f})" for a, b in plan.intervals)
    rate = f"{fps_out.numerator}/{fps_out.denominator}"
    return f"select='not({terms})',setpts=N/({rate})/TB" if terms else "null"


def trim(source: Path, target: Path, plan: Plan, fps_out: Fraction) -> Path:
    """Cuts the pre-rolls out of a processed padded video (any frame rate) and restores the original timeline."""
    rate = f"{fps_out.numerator}/{fps_out.denominator}"
    vf = trim_filter(plan, fps_out)
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source),
           "-map", "0:v:0", "-an", "-vf", vf, "-r", rate,
           "-c:v", "ffv1", "-level", "3", "-g", "1", "-slices", "12", "-threads", "0", str(target)]
    result = subprocess.run(cmd, capture_output=True, timeout=6 * 3600, creationflags=NO_WINDOW)
    if result.returncode != 0 or not target.exists():
        raise RuntimeError("Clean Shot Starts: could not remove the pre-roll frames: "
                           + result.stderr.decode("utf-8", "replace")[-300:])
    return target
