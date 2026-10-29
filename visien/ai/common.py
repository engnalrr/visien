"""Shared helpers for Visien's AI runners (run in the AI runtime, a separate process).

Protocol on stdout (read by visien/ai_engine.py):
    @@VZ <percent> <message>     progress
    @@VZ-RESULT {json}           success
    @@VZ-ERROR <message>         failure (exit code 1)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from fractions import Fraction

import numpy as np

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_last = {"pct": -1.0, "msg": ""}


def progress(fraction: float, message: str = "") -> None:
    pct = max(0.0, min(100.0, fraction * 100.0))
    if abs(pct - _last["pct"]) >= 0.5 or message != _last["msg"]:
        _last.update(pct=pct, msg=message)
        print(f"@@VZ {pct:.1f} {message}", flush=True)


def result(**data) -> None:
    print("@@VZ-RESULT " + json.dumps(data), flush=True)


def fail(message: str) -> None:
    print("@@VZ-ERROR " + message.replace("\n", " ")[:2000], flush=True)
    sys.exit(1)


def probe(ffprobe: str, path: str) -> dict:
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=width,height,avg_frame_rate,r_frame_rate,nb_read_packets,nb_frames,color_space,"
                          "pix_fmt:stream_side_data=rotation", "-of", "json", path],
                         capture_output=True, text=True, creationflags=NO_WINDOW)
    stream = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "24/1"
    try:
        fps = Fraction(rate)
        if fps <= 0:
            fps = Fraction(24)
    except (ValueError, ZeroDivisionError):
        fps = Fraction(24)
    if fps.denominator > 1001 * 1000:
        fps = fps.limit_denominator(1001)
    frames = int(stream.get("nb_read_packets") or stream.get("nb_frames") or 0)
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(round(float(side["rotation"])))
    if abs(rotation) % 180 == 90:  # ffmpeg rotates while decoding, so the frames arrive turned
        width, height = height, width
    # YUV -> RGB matrix: the file's own tag, else BT.709 for HD and BT.601 for SD (what players assume)
    space = str(stream.get("color_space") or "")
    pix = str(stream.get("pix_fmt") or "")
    if pix.startswith(("rgb", "bgr", "gbr")) or space in ("rgb", "gbr"):
        matrix = ""
    elif space in ("bt709", "bt2020nc", "bt2020c", "smpte170m", "bt470bg", "fcc", "smpte240m"):
        matrix = {"bt2020nc": "bt2020", "bt2020c": "bt2020", "smpte170m": "bt601", "bt470bg": "bt601",
                  "fcc": "fcc", "smpte240m": "smpte240m"}.get(space, space)
    else:
        matrix = "bt709" if max(width, height) >= 1280 or min(width, height) >= 720 else "bt601"
    return {"width": width, "height": height, "fps": fps, "frames": frames, "matrix": matrix}


class FrameReader:
    """RGB24 frames from any video through ffmpeg, at a constant frame rate and with the right YUV matrix."""

    def __init__(self, ffmpeg: str, path: str, width: int, height: int, fps: Fraction | None = None,
                 matrix: str = ""):
        self.width, self.height = width, height
        self.size = width * height * 3
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-map", "0:v:0"]
        if fps:
            cmd += ["-fps_mode", "cfr", "-r", f"{fps.numerator}/{fps.denominator}"]
        if matrix:
            cmd += ["-vf", f"scale=in_color_matrix={matrix}:flags=bicubic+accurate_rnd+full_chroma_int"]
        cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)

    def read(self) -> np.ndarray | None:
        data = self.proc.stdout.read(self.size)
        if not data or len(data) < self.size:
            return None
        return np.frombuffer(data, np.uint8).reshape(self.height, self.width, 3)

    def close(self) -> None:
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait()


def reader(ffmpeg: str, path: str, info: dict) -> FrameReader:
    return FrameReader(ffmpeg, path, info["width"], info["height"], info["fps"], info.get("matrix", ""))


# Tags of Visual Enhancer's own lossless RGB files; untagged RGB makes Visual Enhancer render darker and cooler.
RGB_TAGS = "setparams=range=pc:colorspace=gbr:color_primaries=bt709:color_trc=bt709"
RGB_TAG_ARGS = ["-color_range", "pc", "-colorspace", "gbr", "-color_primaries", "bt709", "-color_trc", "bt709"]


class FrameWriter:
    """Lossless FFV1 (planar RGB) video from RGB24 frames."""

    def __init__(self, ffmpeg: str, path: str, width: int, height: int, fps: Fraction):
        self.proc = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                                      "-r", f"{fps.numerator}/{fps.denominator}", "-i", "-",
                                      "-vf", RGB_TAGS, "-c:v", "ffv1", "-level", "3", "-g", "1", "-pix_fmt", "gbrp",
                                      *RGB_TAG_ARGS, path],
                                     stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        self.width, self.height = width, height

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[0] != self.height or frame.shape[1] != self.width:
            raise ValueError(f"frame {frame.shape[1]}x{frame.shape[0]} != {self.width}x{self.height}")
        self.proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())

    def close(self) -> None:
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg could not write the result: " + err[-400:])


def read_image(path: str) -> np.ndarray:
    import cv2  # noqa: WPS433

    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Cannot read image: {path}")
    if image.dtype != np.uint8:
        image = (image / 257).astype(np.uint8)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    elif image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
    else:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image


def write_image(path: str, rgb: np.ndarray) -> None:
    import cv2  # noqa: WPS433

    ok, data = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise RuntimeError("Cannot encode PNG")
    data.tofile(path)


def even(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    return frame[: h - h % 2, : w - w % 2]


def torch_device():
    import torch  # noqa: WPS433

    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def rocm_fixes() -> None:
    """Work around kernels AMD's PyTorch for Windows picks but cannot run (no-op on NVIDIA).

    Its fused attention kernels (flash and memory-efficient scaled_dot_product_attention) fail with
    "invalid argument" on Radeon RX 9070 XT (ROCm 7.14), so attention uses PyTorch's plain (math) kernel.
    """
    import torch  # noqa: WPS433

    if not getattr(torch.version, "hip", None):
        return
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    torch.backends.cuda.enable_math_sdp(True)


def describe_cuda_error(exc: BaseException) -> str:
    text = str(exc)
    if "out of memory" in text.lower():
        return ("The graphics card ran out of memory (CUDA out of memory). Close other GPU programs, use a smaller "
                "model or output size, or raise Block Swap. " + text[:300])
    return text
