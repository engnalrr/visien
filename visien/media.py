"""Probing, frame grabs, preview segments and playback proxies (ffmpeg)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from .config import find_tool

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".mts", ".m2ts", ".wmv", ".flv"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def media_kind(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def run(cmd: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)


@dataclass
class MediaInfo:
    path: str
    name: str
    kind: str
    width: int
    height: int
    fps: str = "0/1"
    fps_value: float = 0.0
    frames: int = 1
    duration: float = 0.0
    codec: str = ""
    pix_fmt: str = ""
    bit_depth: int = 8
    hdr: bool = False
    has_audio: bool = False
    size: int = 0

    def to_json(self) -> dict:
        return asdict(self)


def _rate(text: str | None) -> Fraction | None:
    try:
        value = Fraction(text or "0/1")
        return value if value > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    kind = media_kind(path)
    if kind is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    result = run([find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                  str(path)], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-500:] or "ffprobe failed")
    data = json.loads(result.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("No picture stream in this file.")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = 0
    for side in video.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(round(float(side["rotation"])))
    if abs(rotation) % 180 == 90:
        width, height = height, width
    pix = video.get("pix_fmt", "") or ""
    depth = int(video.get("bits_per_raw_sample") or 0) or (10 if "10" in pix else 12 if "12" in pix else 8)
    transfer = video.get("color_transfer", "") or ""
    size = path.stat().st_size
    if kind == "image":
        return MediaInfo(str(path), path.name, "image", width, height, codec=video.get("codec_name", ""),
                         pix_fmt=pix, bit_depth=depth, size=size)
    rate = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")) or Fraction(25)
    if rate.denominator > 1001 * 1000:
        rate = rate.limit_denominator(1001)
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0.0)
    frames = int(video.get("nb_frames") or 0) or max(1, int(round(duration * float(rate))))
    return MediaInfo(str(path), path.name, "video", width, height, f"{rate.numerator}/{rate.denominator}",
                     float(rate), frames, duration, video.get("codec_name", ""), pix, depth,
                     transfer in ("smpte2084", "arib-std-b67"), audio is not None, size)


def _seek(seconds: float) -> list[str]:
    return ["-ss", f"{max(0.0, seconds):.6f}"] if seconds > 0 else []


def grab_jpeg(path: str, seconds: float = 0.0, width: int | None = None, quality: int = 3) -> bytes:
    """One frame as JPEG for thumbnails and the source viewer."""
    vf = "format=yuvj444p"
    if width:
        vf = f"scale='min({int(width)},iw)':-2:flags=bicubic,{vf}"
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", *_seek(seconds), "-i", path,
           "-map", "0:v:0", "-frames:v", "1", "-vf", vf, "-c:v", "mjpeg", "-q:v", str(quality), "-f", "image2pipe", "-"]
    result = run(cmd, timeout=60)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-300:] or "could not read frame")
    return result.stdout


def extract_png(path: str, seconds: float, target: Path, hdr: bool = False) -> Path:
    """Full-resolution lossless still (for pixel-level comparison)."""
    for vf in ([TONEMAP + "format=rgb24", "format=rgb24"] if hdr else ["format=rgb24"]):
        cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *_seek(seconds), "-i",
               path, "-map", "0:v:0", "-frames:v", "1", "-vf", vf, "-compression_level", "1", str(target)]
        result = run(cmd, timeout=120)
        if result.returncode == 0 and target.exists():
            return target
    raise RuntimeError(result.stderr.decode("utf-8", "replace")[-300:] or "could not extract frame")


BROWSER_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".bmp"}


def browser_image(path: str, target: Path) -> Path:
    """The file itself when WebView2 can show it, otherwise a PNG copy (TIFF, HEIC, RAW …)."""
    if Path(path).suffix.lower() in BROWSER_IMAGES:
        return Path(path)
    if not target.exists():
        extract_png(path, 0.0, target)
    return target


def cut_segment(info: MediaInfo, start: float, length: float, target: Path) -> Path:
    """Frame-accurate, lossless excerpt (FFV1 + PCM) so the preview sees the exact source pixels."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *_seek(start), "-i", info.path,
           "-t", f"{length:.6f}", "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "ffv1", "-level", "3", "-g", "1",
           "-c:a", "pcm_s16le", "-map_metadata", "0", str(target)]
    result = run(cmd, timeout=900)
    if result.returncode != 0 or not target.exists():
        raise RuntimeError("Could not cut the preview segment: " + result.stderr.decode("utf-8", "replace")[-400:])
    return target


@lru_cache(maxsize=1)
def h264_encoder() -> list[str]:
    """GPU H.264 encoder for playback copies: NVIDIA NVENC, AMD AMF, else x264 on the CPU."""
    if encoder_works("h264_nvenc"):
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    if encoder_works("h264_amf"):
        return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "19", "-qp_p", "19", "-qp_b", "19"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]


TONEMAP = ("zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,")


def make_proxy(source: str | Path, target: Path, max_width: int = 3840, max_height: int = 2160,
               hdr: bool = False) -> Path:
    """Browser-playable H.264 copy for the compare player (display only; HDR is tone-mapped for SDR screens)."""
    scale = (f"scale='min({max_width},iw)':'min({max_height},ih)':force_original_aspect_ratio=decrease:"
             "force_divisible_by=2:flags=bicubic,format=yuv420p")

    def command(encoder: list[str], vf: str) -> list[str]:
        return [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source),
                "-map", "0:v:0", "-an", "-vf", vf, *encoder, "-movflags", "+faststart", str(target)]

    attempts = [(h264_encoder(), (TONEMAP if hdr else "") + scale)]
    if hdr:
        attempts.append((h264_encoder(), scale))
    if h264_encoder()[1] != "libx264":
        attempts.append((["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"], scale))
    for encoder, vf in attempts:
        result = run(command(encoder, vf), timeout=1800)
        if result.returncode == 0 and target.exists():
            break
    if result.returncode != 0 or not target.exists():
        raise RuntimeError("Could not build the playback proxy: " + result.stderr.decode("utf-8", "replace")[-400:])
    return target


def open_in_explorer(path: str | Path) -> None:
    import os  # noqa: WPS433

    path = Path(path)
    if os.name == "nt":
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path if path.exists() else path.parent))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


# ---------------------------------------------------------------- pipeline helpers (AI stages)


@lru_cache(maxsize=8)
@lru_cache(maxsize=16)
def encoder_works(name: str, pix_fmt: str = "yuv420p") -> bool:
    try:
        test = run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=black:s=256x256:d=0.1", "-pix_fmt", pix_fmt, "-c:v", name, "-f", "null", "-"], timeout=30)
        return test.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def mux_audio(video: Path, audio_source: str | Path, target: Path) -> Path:
    """Video stream of `video` with the audio of `audio_source` (if any), stream copy."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(video),
           "-i", str(audio_source), "-map", "0:v:0", "-map", "1:a:0?", "-c", "copy", str(target)]
    result = run(cmd, timeout=1800)
    if result.returncode != 0 or not target.exists():
        raise RuntimeError("Could not add the audio back: " + result.stderr.decode("utf-8", "replace")[-300:])
    return target


_CQ = {"h264": (26, 22, 18, 1), "hevc": (28, 24, 20, 1), "av1": (34, 29, 24, 1)}
_CRF = {"h264": (23, 20, 17, 0), "hevc": (26, 23, 20, 0), "av1": (30, 26, 22, 0)}
_QUALITY_INDEX = {"Auto (Default)": 0, "Good": 1, "Best": 2, "Max": 3}


def _video_codec_args(settings: dict) -> list[str]:
    codec = str(settings.get("codec") or "H.264")
    quality = _QUALITY_INDEX.get(str(settings.get("quality") or "Auto (Default)"), 0)
    family = "h264" if codec.startswith("H.264") else "hevc" if codec.startswith("H.265") else \
        "av1" if codec.startswith("AV1") else codec
    if family in _CQ:
        ten_bit = family != "h264"
        pix_fmt = "p010le" if ten_bit else "yuv420p"
        hw = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}[family]
        if encoder_works(hw, pix_fmt):
            args = ["-c:v", hw, "-preset", "p5", "-rc", "vbr", "-cq", str(_CQ[family][quality]), "-b:v", "0"]
            if quality == 3:
                args += ["-qmin", "0", "-qmax", "1"]
            return args + ["-pix_fmt", pix_fmt]
        amf = {"h264": "h264_amf", "hevc": "hevc_amf", "av1": "av1_amf"}[family]
        if encoder_works(amf, pix_fmt):  # AMD Radeon
            qp = str(_CQ[family][quality])
            args = ["-c:v", amf, "-quality", "quality", "-rc", "cqp", "-qp_i", qp, "-qp_p", qp]
            if family == "h264":
                args += ["-qp_b", qp]
            return args + ["-pix_fmt", pix_fmt]
        sw = {"h264": ["-c:v", "libx264", "-preset", "medium"], "hevc": ["-c:v", "libx265", "-preset", "medium"],
              "av1": ["-c:v", "libsvtav1", "-preset", "6"]}[family]
        return sw + ["-crf", str(_CRF[family][quality]), "-pix_fmt", "yuv420p10le" if ten_bit else "yuv420p"]
    if codec.startswith("ProRes"):
        return ["-c:v", "prores_ks", "-profile:v", "0" if "Proxy" in codec else "3", "-pix_fmt", "yuv422p10le"]
    return ["-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "gbrp10le"]


def encode_export(source: Path, target: Path, settings: dict, kind: str, *, pre_filter: str = "",
                  audio_source: str | Path | None = None) -> Path:
    """Final file from a lossless intermediate, following Visual Enhancer's export settings.

    pre_filter runs first (Clean Shot Starts removes its warm-up frames there); audio_source takes the audio from
    another file (the original source) instead of the intermediate.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_tool("ffmpeg")
    if kind == "image":
        fmt = str(settings.get("image_format") or "PNG")
        deep = int(settings.get("image_bit_depth") or 8) == 16
        quality = int(settings.get("image_quality") or 95)
        args = {"PNG": ["-c:v", "png", "-pix_fmt", "rgb48be" if deep else "rgb24"],
                "TIFF": ["-c:v", "tiff", "-pix_fmt", "rgb48le" if deep else "rgb24"],
                "JPEG": ["-c:v", "mjpeg", "-q:v", str(max(1, min(31, round(2 + (100 - quality) * 0.29)))),
                         "-pix_fmt", "yuvj444p"],
                "WebP": ["-c:v", "libwebp", "-quality", str(quality)],
                "AVIF": ["-c:v", "libaom-av1", "-still-picture", "1", "-crf", str(max(0, min(63, 63 - quality * 0.6))),
                         "-pix_fmt", "yuv444p"]}.get(fmt, ["-c:v", "png"])
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source), "-frames:v", "1",
               *args, str(target)]
    else:
        codec = str(settings.get("codec") or "H.264")
        container = target.suffix.lower()
        pre = f"{pre_filter}," if pre_filter else ""
        if codec.startswith("FFV1"):
            video = ["-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "gbrp10le"]
            vf = ["-vf", pre_filter] if pre_filter else []
        else:
            video = _video_codec_args(settings)
            vf = ["-vf", pre + "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic",
                  "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
        audio = ["-c:a", "copy"] if container == ".mkv" else ["-c:a", "aac", "-b:a", "320k"]
        extra = ["-movflags", "+faststart"] if container in (".mp4", ".mov") else []
        inputs = ["-i", str(source)] + (["-i", str(audio_source)] if audio_source else [])
        audio_map = "1:a:0?" if audio_source else "0:a:0?"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *inputs, "-map", "0:v:0",
               "-map", audio_map, *vf, *video, *audio, *extra, str(target)]
    result = run(cmd, timeout=6 * 3600)
    if result.returncode != 0 or not target.exists():
        raise RuntimeError("Could not write the final file: " + result.stderr.decode("utf-8", "replace")[-400:])
    return target
