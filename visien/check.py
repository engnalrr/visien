"""Install check: python -m visien.check  (prints what works and what is missing)."""

from __future__ import annotations

import subprocess
import sys

from . import __version__
from .config import ensure_dirs, find_tool, output_dir


def main() -> int:
    ensure_dirs()
    problems = 0
    print(f"Visien {__version__} · Python {sys.version.split()[0]}")
    for module in ("fastapi", "uvicorn", "webview"):
        try:
            __import__(module)
            print(f"  [ok]   {module}")
        except Exception as exc:  # noqa: BLE001
            problems += 1
            print(f"  [FAIL] {module}: {exc}")
    try:
        ffmpeg = find_tool("ffmpeg")
        first = subprocess.run([ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True,
                               timeout=30).stdout.splitlines()[0]
        print(f"  [ok]   ffmpeg: {first[:70]}")
        from .media import h264_encoder  # noqa: WPS433

        encoder = h264_encoder()[1]
        print(f"  [ok]   preview encoder: {encoder}")
    except Exception as exc:  # noqa: BLE001
        problems += 1
        print(f"  [FAIL] ffmpeg: {exc}")
    from . import ve  # noqa: WPS433

    result = ve.scan(auto_select=True)
    status = ve.status()
    if status["ok"]:
        print(f"  [ok]   Visual Enhancer {status['version']}: {status['path']}")
        try:
            devices = ve.devices(refresh=True).get("devices", [])
            for device in devices:
                print(f"         GPU {device.get('index')}: {device.get('name')} "
                      f"(AI {'yes' if device.get('ai_compatible') else 'no'})")
            if ve.rtx_problem():
                print("  [warn] No NVIDIA RTX GPU: Visual Enhancer's DLSS / RTX cards are skipped on this PC; "
                      "Visien's AI cards still run.")
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] Visual Enhancer could not list GPUs: {exc}")
    else:
        print("  [todo] Visual Enhancer not connected yet:")
        print("         " + status["reason"].replace("\n", "\n         "))
        for item in result["found"]:
            print(f"         found: {item['path']} ({'complete' if item['complete'] else 'missing ' + ', '.join(item['missing'])})")
    from . import models  # noqa: WPS433

    if models.runtime_installed():
        info = models.runtime_check(refresh=True)
        if info.get("ok"):
            api = "ROCm" if info.get("backend") == "rocm" else "CUDA"
            gpu = f"{api} on {info.get('gpu')} ({info.get('vram_gb')} GB)" if info.get("cuda") else "no usable GPU found"
            tag = "[ok]  " if info.get("cuda") else "[warn]"
            print(f"  {tag} AI runtime: PyTorch {info.get('torch')}, {gpu}")
        else:
            print(f"  [warn] AI runtime does not start: {str(info.get('error', ''))[:200]}")
        ready = [c["title"] for c in models.COMPONENTS if c.get("file") and models.installed(c["id"])]
        print(f"         AI models: {', '.join(ready) if ready else 'none yet'}")
    elif models.backend_mismatch():
        card = models.gpu()
        print(f"  [todo] The AI runtime was built for the other GPU vendor; this PC has {card['name']}. "
              "Settings > AI models > AI runtime > Install switches it.")
    else:
        print("  [todo] AI models (SeedVR2, RIFE, Face Restore) not installed: Settings > AI models > Install recommended")
    print(f"  Output folder: {output_dir()}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
