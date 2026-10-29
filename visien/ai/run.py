"""Entry point of Visien's AI runners:

    python -m visien.ai.run <seedvr2|rife|face_restore> --input IN --output OUT --kind video|image
                            --params PARAMS.json --models MODELS_DIR --ffmpeg FFMPEG --ffprobe FFPROBE --root ROOT
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


class _Tee:
    """Copies everything a runner prints into a log file (used when the app does not keep the log itself)."""

    def __init__(self, stream, handle):
        self.stream, self.handle = stream, handle

    def write(self, text):
        self.handle.write(text)
        self.handle.flush()
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


_TRACE: dict = {}


def _tee(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "w", encoding="utf-8", errors="replace")
    except OSError:
        return
    sys.stdout = _Tee(sys.stdout, handle)
    sys.stderr = _Tee(sys.stderr, handle)
    _TRACE["handle"] = handle


def _bench(torch) -> dict:
    """Quick GPU timings (diagnostics)."""
    import torch.nn.functional as F  # noqa: WPS433

    def timed(fn, repeat=3):
        fn()
        torch.cuda.synchronize()
        began = time.perf_counter()
        for _ in range(repeat):
            fn()
        torch.cuda.synchronize()
        return round((time.perf_counter() - began) / repeat * 1000, 1)

    result = {}
    a = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
    ms = timed(lambda: a @ a)
    result["matmul_bf16_tflops"] = round(2 * 4096 ** 3 / (ms / 1000) / 1e12, 1)
    for dtype in (torch.bfloat16, torch.float16, torch.float32):
        x = torch.randn(1, 128, 5, 256, 256, device="cuda", dtype=dtype)
        w = torch.randn(128, 128, 3, 3, 3, device="cuda", dtype=dtype)
        name = str(dtype).split(".")[-1]
        for cudnn in (True, False):
            torch.backends.cudnn.enabled = cudnn
            try:
                result[f"conv3d_{name}_cudnn{int(cudnn)}_ms"] = timed(lambda: F.conv3d(x, w, padding=1), 2)
            except Exception as exc:  # noqa: BLE001
                result[f"conv3d_{name}_cudnn{int(cudnn)}_ms"] = str(exc)[:80]
        torch.backends.cudnn.enabled = True
        try:
            result[f"cudnn_direct_{name}_ms"] = timed(lambda: torch.cudnn_convolution(
                x, w, (1, 1, 1), (1, 1, 1), (1, 1, 1), 1, False, False, True), 2)
        except Exception as exc:  # noqa: BLE001
            result[f"cudnn_direct_{name}_ms"] = str(exc)[:80]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="visien.ai.run")
    parser.add_argument("stage", choices=["seedvr2", "rife", "face_restore", "color_match", "check"])
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--kind", default="video", choices=["video", "image"])
    parser.add_argument("--params", default="")
    parser.add_argument("--models", default="models")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    args.models = Path(args.models)
    args.output = Path(args.output) if args.output else None
    params = json.loads(Path(args.params).read_text(encoding="utf-8")) if args.params else {}
    import faulthandler  # noqa: WPS433

    faulthandler.enable()  # a native crash (driver, CUDA) still leaves a stack trace in the log
    diagnose = (Path(args.root) / "data" / "gpu_bench.flag").is_file()
    if args.stage != "check" and (diagnose or not os.environ.get("VISIEN_AI_LOGGED")):
        _tee(Path(args.root) / "data" / "logs" / f"ai-{args.stage}-{time.strftime('%Y%m%d-%H%M%S')}-trace.log")
        if diagnose and _TRACE.get("handle"):
            faulthandler.dump_traceback_later(6, repeat=True, file=_TRACE["handle"])

    from . import common  # noqa: WPS433

    try:
        if args.stage == "check":
            import torch  # noqa: WPS433

            hip = getattr(torch.version, "hip", None)
            info = {"torch": torch.__version__, "cuda": torch.cuda.is_available(),
                    "backend": "rocm" if hip else "cuda" if torch.version.cuda else "cpu",
                    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""}
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info(0)
                info["vram_gb"] = round(total / 1024 ** 3, 1)
                info["vram_free_gb"] = round(free / 1024 ** 3, 1)
                props = torch.cuda.get_device_properties(0)
                info["compute"] = getattr(props, "gcnArchName", "") if hip else f"{props.major}.{props.minor}"
            if torch.cuda.is_available() and (Path(args.root) / "data" / "gpu_bench.flag").is_file():
                info["bench"] = _bench(torch)
            try:
                import spandrel  # noqa: WPS433

                info["spandrel"] = spandrel.__version__
            except Exception as exc:  # noqa: BLE001
                info["spandrel_error"] = str(exc)
            common.result(**info)
            return
        if args.stage == "rife":
            from . import rife as module  # noqa: WPS433
        elif args.stage == "face_restore":
            from . import face as module  # noqa: WPS433
        elif args.stage == "color_match":
            from . import colormatch as module  # noqa: WPS433
        else:
            from . import seedvr2 as module  # noqa: WPS433
        module.run(args, params)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        common.fail(f"{type(exc).__name__}: {common.describe_cuda_error(exc)}")


if __name__ == "__main__":
    main()
