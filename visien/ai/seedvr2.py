"""SeedVR2 restoration through the vendored numz/ComfyUI-SeedVR2_VideoUpscaler CLI (Apache 2.0)."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from . import common

PHASES = (("encode_all_batches", 0.00, 0.18, "Encoding"), ("upscale_all_batches", 0.18, 0.80, "Restoring"),
          ("decode_all_batches", 0.80, 0.97, "Decoding"), ("postprocess_all_batches", 0.97, 1.00, "Finishing"))


def _target(params: dict, width: int, height: int) -> int:
    short = min(width, height)
    mode = params.get("seedvr2_size_mode")
    if mode == "short":
        target = int(params.get("seedvr2_short_side") or 1080)
    elif mode == "min":  # bring small sources up to the short side, keep bigger ones at their size
        target = max(short, int(params.get("seedvr2_short_side") or 1080))
    else:
        target = int(round(short * float(params.get("seedvr2_scale") or 1.0)))
    return target - target % 2


def _install_progress(cli, chunks: int, span: tuple[float, float]) -> dict:
    state = {"chunk": 0}

    def wrap(name: str, low: float, high: float, label: str):
        original = getattr(cli, name)

        def call(*args, **kwargs):
            if name == "encode_all_batches":
                state["chunk"] += 1

            def report(current, total, _frames=None, _phase=None):
                inner = low + (high - low) * (current / max(total, 1))
                overall = (state["chunk"] - 1 + inner) / max(chunks, 1)
                common.progress(span[0] + (span[1] - span[0]) * overall,
                                f"{label} {state['chunk']}/{chunks}" if chunks > 1 else label)

            kwargs["progress_callback"] = report
            began = time.time()
            print(f"[visien] {label} {state['chunk']}/{chunks} started", flush=True)
            value = original(*args, **kwargs)
            print(f"[visien] {label} {state['chunk']}/{chunks} took {time.time() - began:.1f} s", flush=True)
            return value

        setattr(cli, name, call)

    for name, low, high, label in PHASES:
        wrap(name, low, high, label)
    return state


def _tuning(root: Path) -> dict:
    import json  # noqa: WPS433

    try:
        return json.loads((root / "data" / "seedvr2_tuning.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _tune(root: Path) -> None:
    """GPU settings for the VAE's 3D convolutions.

    The vendored code routes Conv3d through torch.cudnn_convolution (benchmark off) on PyTorch >= 2.9 to dodge
    a memory bug. On some GPUs (seen on RTX 50 / Blackwell) that path is extremely slow, so Visien uses the normal
    path with cuDNN autotuning unless data/seedvr2_tuning.json says otherwise.
    """
    import torch  # noqa: WPS433

    config = _tuning(root)
    conv = config.get("conv3d", "workaround")
    if getattr(torch.version, "hip", None):
        conv = "native"  # the workaround calls cuDNN directly; AMD (ROCm/MIOpen) uses the normal path
    if conv != "workaround":
        try:
            import src.models.video_vae_v3.modules.causal_inflation_lib as inflation  # noqa: WPS433

            inflation.NVIDIA_CONV3D_MEMORY_BUG_WORKAROUND = False
        except Exception as exc:  # noqa: BLE001
            print(f"[visien] could not switch the Conv3d path: {exc}", flush=True)
    torch.backends.cudnn.benchmark = bool(config.get("benchmark", False))
    if "cudnn" in config:
        torch.backends.cudnn.enabled = bool(config["cudnn"])
    print(f"[visien] conv3d={conv} cudnn.benchmark={torch.backends.cudnn.benchmark} "
          f"cudnn={torch.backends.cudnn.enabled} ({torch.backends.cudnn.version()})", flush=True)


def _memory_plans(params: dict, pixels: float, dit: str, tuning: dict, vram_gb: float) -> list[dict]:
    """Settings to try in order; each later one uses less GPU memory (and is slower).

    Measured on a 16 GB RTX 5070 Ti: 3B FP8 at 1080p runs with 768 px VAE tiles; without tiles the VAE runs out of
    memory. Bigger cards start with bigger tiles.
    """
    swap = int(params.get("seedvr2_blocks_to_swap") or 0)
    tiling = bool(params.get("seedvr2_vae_tiling", True))
    big = "7b" in dit
    max_swap = 36 if big else 32
    if big and vram_gb and vram_gb < 20:
        swap = max(swap, 16)

    def make(label: str, tiled: bool, tile: int, blocks: int, io: bool = False) -> dict:
        extra: list[str] = []
        if tiled:
            overlap = max(64, tile // 8)
            extra += ["--vae_encode_tiled", "--vae_decode_tiled", "--vae_encode_tile_size", str(tile),
                      "--vae_decode_tile_size", str(tile), "--vae_encode_tile_overlap", str(overlap),
                      "--vae_decode_tile_overlap", str(overlap)]
        if blocks:
            extra += ["--blocks_to_swap", str(min(blocks, max_swap)), "--dit_offload_device", "cpu"]
            if io:
                extra.append("--swap_io_components")
        name = (f"VAE tiles {tile}" if tiled else "no VAE tiles") + (f", Block Swap {min(blocks, max_swap)}" if blocks else "")
        return {"label": name, "args": extra}

    roomy = vram_gb >= 20
    # frames above ~2.5 MP (e.g. 3380×1440) need small VAE tiles on 16 GB cards
    tile = int(tuning.get("tile", 1024 if roomy else (512 if pixels > 2_500_000 else 768)))
    above = float(tuning.get("tile_above", 2_100_000 if roomy else 900_000))
    plans = [make(label="", tiled=tiling and pixels > above, tile=tile, blocks=swap)]
    plans.append(make(label="", tiled=True, tile=min(tile, 640) if tile > 512 else 384, blocks=max(swap, 16)))
    plans.append(make(label="", tiled=True, tile=512, blocks=max_swap, io=True))
    return plans


def _is_oom(exc) -> bool:
    if exc is None:
        return False
    text = f"{type(exc).__name__} {exc}".lower()
    return "outofmemory" in text or "out of memory" in text or "allocation on device" in text


def _free_memory(torch) -> None:
    import gc  # noqa: WPS433

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    time.sleep(1.0)


def run(args, params: dict) -> None:
    vendor = Path(args.root) / "vendor" / "seedvr2"
    model_dir = args.models / "seedvr2"
    dit = params.get("seedvr2_model") or "seedvr2_ema_3b_fp8_e4m3fn.safetensors"
    for needed in (model_dir / dit, model_dir / "ema_vae_fp16.safetensors"):
        if not needed.is_file():
            common.fail(f"SeedVR2 file {needed.name} is not installed (Settings > AI models).")

    # The vendored CLI reads and writes with OpenCV, which assumes BT.601, cannot open non-ASCII paths on Windows
    # and mishandles 16-bit or grey images. So it always gets a clean copy: 8-bit RGB PNG, or lossless RGB FFV1
    # made by ffmpeg with the right colour matrix, rotation and a constant frame rate.
    work = Path(tempfile.mkdtemp(prefix="seedvr2_", dir=str(Path(args.output).parent)))
    (work / "src").mkdir()
    out_dir = work / "out"
    common.progress(0.005, "Preparing")
    if args.kind == "image":
        source = common.read_image(args.input)
        height, width = source.shape[:2]
        frames, fps = 1, None
        clean = work / "src" / "input.png"
        common.write_image(str(clean), source)
    else:
        info = common.probe(args.ffprobe, args.input)
        width, height, fps = info["width"], info["height"], info["fps"]
        clean = work / "src" / "input.mkv"
        vf = (f"scale=in_color_matrix={info['matrix']}:flags=bicubic+accurate_rnd+full_chroma_int,"
              if info.get("matrix") else "") + "format=gbrp"
        made = subprocess.run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", args.input,
                               "-map", "0:v:0", "-an", "-fps_mode", "cfr", "-r", f"{fps.numerator}/{fps.denominator}",
                               "-vf", vf, "-c:v", "ffv1", "-level", "3", "-g", "1", str(clean)],
                              capture_output=True, text=True, creationflags=common.NO_WINDOW)
        if made.returncode != 0 or not clean.is_file():
            common.fail("SeedVR2: could not prepare the input: " + made.stderr[-300:])
        frames = common.probe(args.ffprobe, str(clean))["frames"]
    target = _target(params, width, height)
    batch = 1 if args.kind == "image" else int(params.get("seedvr2_batch") or 5)
    pixels = target * target * (max(width, height) / max(min(width, height), 1))
    # Bound memory: chunks of whole batches; smaller chunks for bigger frames.
    per_chunk = max(batch, (int(40 * (1920 * 1080) / max(pixels, 1)) // batch) * batch)
    chunk = 0 if frames <= per_chunk else per_chunk
    chunks = 1 if not chunk else math.ceil(frames / chunk)

    base = ["inference_cli.py", str(clean), "--output", str(out_dir), "--output_format", "png",
            "--model_dir", str(model_dir), "--dit_model", dit, "--resolution", str(target),
            "--batch_size", str(batch), "--seed", str(int(params.get("seedvr2_seed", 42))),
            "--color_correction", str(params.get("seedvr2_color") or "lab"),
            "--input_noise_scale", str(float(params.get("seedvr2_input_noise") or 0.0)),
            "--latent_noise_scale", str(float(params.get("seedvr2_latent_noise") or 0.0)),
            "--cuda_device", "0", "--debug"]  # --debug: memory and timing details go to the log file
    if chunk:
        base += ["--chunk_size", str(chunk)]
    if args.kind == "video" and batch > 1:
        # blend 2 frames across batch (and chunk) borders, and pad the last batch, so texture does not jump
        overlap = max(0, min(int(params.get("seedvr2_overlap", 2)), batch - 1))
        base += ["--uniform_batch_size"] + (["--temporal_overlap", str(overlap)] if overlap else [])
    tuning = _tuning(Path(args.root))

    common.progress(0.01, "Loading SeedVR2")
    import torch  # noqa: WPS433

    common.rocm_fixes()

    vram_gb = 0.0
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info(0)
        vram_gb = total / 2 ** 30
        # Keep PyTorch inside the card's own memory: on Windows the driver otherwise spills into system RAM
        # (shared GPU memory), which makes SeedVR2 50-100× slower instead of failing cleanly.
        cap = max(0.5, min(0.9, (free - 1.0 * 2 ** 30) / total))
        torch.cuda.set_per_process_memory_fraction(cap, 0)
        print(f"[visien] GPU {torch.cuda.get_device_name(0)}: {free / 2 ** 30:.1f} of {total / 2 ** 30:.1f} GB free, "
              f"PyTorch limited to {cap * total / 2 ** 30:.1f} GB; target short side {target}, batch {batch}, "
              f"chunk {chunk or frames}, frames {frames}", flush=True)
    plans = _memory_plans(params, pixels, dit, tuning, vram_gb)
    sys.path.insert(0, str(vendor))
    old_cwd, old_argv = os.getcwd(), sys.argv
    try:
        os.chdir(str(vendor))
        import inference_cli as cli  # noqa: WPS433

        _tune(Path(args.root))
        progress_state = _install_progress(cli, chunks, (0.02, 0.92))
        failure: dict = {}
        original = cli.process_single_file

        def watched(*a, **k):
            try:
                return original(*a, **k)
            except BaseException as exc:  # noqa: BLE001 - recorded, then handled by the CLI
                failure["exc"] = exc
                raise

        cli.process_single_file = watched
        for attempt, plan in enumerate(plans):
            failure.clear()
            progress_state["chunk"] = 0
            shutil.rmtree(out_dir, ignore_errors=True)
            sys.argv = base + plan["args"]
            print(f"[visien] attempt {attempt + 1}/{len(plans)}: {plan['label']}", flush=True)
            if attempt:
                common.progress(0.02, f"Out of GPU memory - retrying ({plan['label']})")
            try:
                cli.main()
                break
            except SystemExit as exc:
                if exc.code in (0, None):
                    break
                reason = failure.pop("exc", None)
                if _is_oom(reason) and attempt + 1 < len(plans):
                    exc.__context__ = None  # drop references to the failed run's tensors before freeing memory
                    del reason
                    _free_memory(torch)
                    continue
                common.fail("SeedVR2: " + (common.describe_cuda_error(reason) if reason else f"stopped (exit {exc.code})."))
    except Exception as exc:  # noqa: BLE001
        common.fail("SeedVR2: " + common.describe_cuda_error(exc))
    finally:
        os.chdir(old_cwd)
        sys.argv = old_argv

    outputs = sorted(p for p in out_dir.rglob("*.png"))
    if not outputs:
        common.fail("SeedVR2 produced no frames.")
    if args.kind == "video" and frames and len(outputs) < frames:
        common.fail(f"SeedVR2 produced {len(outputs)} of {frames} frames.")
    outputs = outputs[:frames] if args.kind == "video" and frames else outputs
    blend = float(params.get("seedvr2_blend", 100)) / 100.0
    import cv2  # noqa: WPS433

    def mix(restored: np.ndarray, original: np.ndarray) -> np.ndarray:
        if blend >= 0.999:
            return restored
        base = cv2.resize(original, (restored.shape[1], restored.shape[0]), interpolation=cv2.INTER_CUBIC)
        return cv2.addWeighted(restored, blend, base, 1.0 - blend, 0)

    common.progress(0.93, "Assembling")
    if args.kind == "image":
        result = common.even(mix(common.read_image(str(outputs[0])), source))
        common.write_image(str(args.output), result)
        shutil.rmtree(work, ignore_errors=True)
        common.result(width=result.shape[1], height=result.shape[0], frames=1)
        return
    first = common.read_image(str(outputs[0]))
    out_h, out_w = first.shape[0] - first.shape[0] % 2, first.shape[1] - first.shape[1] % 2
    reader = common.FrameReader(args.ffmpeg, str(clean), width, height) if blend < 0.999 else None
    writer = common.FrameWriter(args.ffmpeg, str(args.output), out_w, out_h, fps)
    for index, path in enumerate(outputs):
        restored = first if index == 0 else common.read_image(str(path))
        original = reader.read() if reader else None
        frame = mix(restored, original) if original is not None else restored
        writer.write(frame[:out_h, :out_w])
        common.progress(0.93 + 0.07 * (index + 1) / len(outputs), "Assembling")
    if reader:
        reader.close()
    writer.close()
    shutil.rmtree(work, ignore_errors=True)
    common.result(width=out_w, height=out_h, frames=len(outputs))
