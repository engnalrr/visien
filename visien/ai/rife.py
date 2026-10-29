"""RIFE frame interpolation (Practical-RIFE 4.x weights, vendored IFNet)."""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from . import common

ARCH = {"rife426.pth": "4.26", "rife417.pth": "4.17", "rife49.pth": "4.7"}
EXACT = {"23.976": Fraction(24000, 1001), "29.97": Fraction(30000, 1001), "59.94": Fraction(60000, 1001),
         "119.88": Fraction(120000, 1001)}


def target_rate(params: dict, source: Fraction) -> Fraction:
    if params.get("rife_mode") == "Multiplier":
        return source * int(params.get("rife_multiplier") or 2)
    text = str(params.get("rife_target_fps") or "60").strip()
    if text in EXACT:
        return EXACT[text]
    return Fraction(text).limit_denominator(1001)


def _gray_small(frame: np.ndarray) -> np.ndarray:
    import cv2  # noqa: WPS433

    small = cv2.resize(frame, (96, 54), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0


def run(args, params: dict) -> None:
    import torch  # noqa: WPS433

    from .rife_arch import IFNet  # noqa: WPS433

    info = common.probe(args.ffprobe, args.input)
    width, height, fps_in = info["width"], info["height"], info["fps"]
    frames_in = info["frames"]
    fps_out = target_rate(params, fps_in)
    if fps_out <= fps_in:
        common.fail(f"RIFE: the target frame rate ({float(fps_out):.3f}) must be higher than the source "
                    f"({float(fps_in):.3f}).")
    model_name = params.get("rife_model") or "rife426.pth"
    arch = ARCH.get(model_name, "4.26")
    weights = args.models / "rife" / model_name
    if not weights.is_file():
        common.fail(f"RIFE model {model_name} is not installed (Settings > AI models).")

    device = common.torch_device()
    half = device.type == "cuda"
    common.progress(0.01, "Loading RIFE")
    model = IFNet(arch_ver=arch)
    state = torch.load(str(weights), map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    state = {k.replace("module.", ""): v for k, v in state.items()}
    missing, unexpected = model.load_state_dict(state, strict=False)
    if len(missing) > 4:
        common.fail(f"RIFE weights {model_name} do not match the {arch} architecture ({len(missing)} missing keys).")
    model.eval().to(device)
    if half:
        model.half()
    scale_mode = params.get("rife_scale") or "auto"
    scale = 0.5 if scale_mode == "half" or (scale_mode == "auto" and min(width, height) > 1440) else 1.0
    scale_list = ([16, 8, 4, 2, 1] if arch == "4.26" else [8, 4, 2, 1])
    scale_list = [s / scale for s in scale_list]
    detect = bool(params.get("rife_scene_detect", True))
    threshold = float(params.get("rife_scene_threshold") or 0.15)

    def tensor(frame: np.ndarray):
        t = torch.from_numpy(frame).to(device).permute(2, 0, 1).unsqueeze(0)
        return (t.half() if half else t.float()) / 255.0

    if not frames_in:
        common.fail("RIFE: could not count the input frames.")
    n_out = max(1, int(round(frames_in * fps_out / fps_in)))
    reader = common.reader(args.ffmpeg, args.input, info)
    writer = common.FrameWriter(args.ffmpeg, str(args.output), width, height, fps_out)
    frames: dict[int, np.ndarray] = {}
    tensors: dict = {}
    cut_cache: dict[int, bool] = {}
    loaded = -1               # highest frame index read so far
    ended = False
    cuts = 0
    try:
        for k in range(n_out):
            pos = Fraction(k) * fps_in / fps_out
            i = math.floor(pos)
            frac = float(pos - i)
            want = min(i + 1, frames_in - 1)
            while not ended and loaded < want:
                nxt = reader.read()
                if nxt is None:
                    ended = True
                    break
                loaded += 1
                frames[loaded] = nxt
            if loaded < 0:
                common.fail("RIFE: the input has no frames.")
            if i > loaded:
                i, frac = loaded, 0.0
            for old in [n for n in frames if n < i]:
                frames.pop(old)
                tensors.pop(old, None)
            f0 = frames[i]
            if frac < 1e-4 or i + 1 > loaded:
                out = f0
            else:
                f1 = frames[i + 1]
                is_cut = False
                if detect:
                    if i not in cut_cache:
                        diff = float(np.mean(np.abs(_gray_small(f0) - _gray_small(f1))))
                        cut_cache[i] = diff > threshold
                        cuts += int(cut_cache[i])
                    is_cut = cut_cache[i]
                if is_cut:
                    out = f0 if frac < 0.5 else f1
                else:
                    if i not in tensors:
                        tensors[i] = tensor(f0)
                    if i + 1 not in tensors:
                        tensors[i + 1] = tensor(f1)
                    with torch.inference_mode():
                        ts = torch.full((1, 1, 1, 1), frac, device=device,
                                        dtype=torch.float16 if half else torch.float32)
                        mid = model(tensors[i], tensors[i + 1], ts, scale_list, training=False, fastmode=True,
                                    ensemble=False)
                    out = (mid[0].clamp(0, 1) * 255.0).round().byte().permute(1, 2, 0).cpu().numpy()
            writer.write(out)
            common.progress((k + 1) / n_out, f"Interpolating {k + 1}/{n_out}")
    except torch.cuda.OutOfMemoryError as exc:  # type: ignore[attr-defined]
        reader.close()
        common.fail(common.describe_cuda_error(exc))
    reader.close()
    writer.close()
    common.result(width=width, height=height, fps=float(fps_out), frames=n_out, cuts=cuts)
